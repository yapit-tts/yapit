# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich", "websockets", "httpx", "mutagen"]
# ///

from __future__ import annotations

import asyncio
import io
import json
import random
import string
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import tyro
import websockets
from mutagen.oggopus import OggOpus
from rich.console import Console
from rich.progress import Progress, TaskID
from rich.table import Table


def get_audio_duration_ms(audio_bytes: bytes) -> float:
    return OggOpus(io.BytesIO(audio_bytes)).info.length * 1000


def _load_stack_auth_creds() -> tuple[str, str]:
    """Load Stack Auth public credentials from frontend/.env.production."""
    env_file = Path(__file__).parent.parent / "frontend" / ".env.production"
    project_id, client_key = None, None
    for line in env_file.read_text().splitlines():
        if line.startswith("VITE_STACK_AUTH_PROJECT_ID="):
            project_id = line.split("=", 1)[1]
        elif line.startswith("VITE_STACK_AUTH_CLIENT_KEY="):
            client_key = line.split("=", 1)[1]
    assert project_id and client_key, f"Missing Stack Auth creds in {env_file}"
    return project_id, client_key


def get_auth_token(base_url: str, email: str, password: str) -> str:
    project_id, client_key = _load_stack_auth_creds()
    resp = httpx.post(
        f"{base_url}/auth/api/v1/auth/password/sign-in",
        headers={
            "Content-Type": "application/json",
            "X-Stack-Access-Type": "client",
            "X-Stack-Project-Id": project_id,
            "X-Stack-Publishable-Client-Key": client_key,
        },
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@dataclass
class BlockArrival:
    idx: int
    requested_ms: float
    arrived_ms: float
    status: str
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def round_trip_ms(self) -> float:
        return self.arrived_ms - self.requested_ms


@dataclass
class Underrun:
    at_block: int
    waited_ms: float


@dataclass
class UserSession:
    user_id: int
    document_id: str
    blocks_requested: int
    block_arrivals: list[BlockArrival] = field(default_factory=list)
    underruns: list[Underrun] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "document_id": self.document_id,
            "blocks_requested": self.blocks_requested,
            "block_arrivals": [
                {
                    "idx": b.idx,
                    "requested_ms": b.requested_ms,
                    "arrived_ms": b.arrived_ms,
                    "round_trip_ms": b.round_trip_ms,
                    "status": b.status,
                    "duration_ms": b.duration_ms,
                }
                for b in self.block_arrivals
            ],
            "underruns": [{"at_block": u.at_block, "waited_ms": u.waited_ms} for u in self.underruns],
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


# Matches frontend playbackEngine.ts
BATCH_SIZE = 8
REFILL_THRESHOLD = 8
DEFAULT_MIN_BUFFER_TO_START = 2

MODEL_DEFAULT_VOICES = {
    "kokoro": "af_heart",
    "inworld-1.5": "alex",
    "inworld-1.5-max": "alex",
}


async def run_user_session(
    user_id: int,
    base_url: str,
    ws_url: str,
    token: str,
    document_id: str,
    num_blocks: int,
    model: str,
    voice: str,
    speed: float,
    min_buffer: int = DEFAULT_MIN_BUFFER_TO_START,
    on_progress: callable | None = None,
) -> UserSession:
    session = UserSession(
        user_id=user_id,
        document_id=document_id,
        blocks_requested=num_blocks,
    )

    pending: set[int] = set()
    request_times: dict[int, float] = {}
    cached: set[int] = set()
    failed: set[int] = set()
    block_durations: dict[int, float] = {}
    next_to_request = 0
    playback_position = 0

    session.start_time = time.time()
    http_client = httpx.AsyncClient(
        base_url=f"{base_url}/api",
        timeout=30,
        headers={"Authorization": f"Bearer {token}"},
    )

    try:
        async with websockets.connect(f"{ws_url}?token={token}") as ws:
            ws_dead = False

            async def handle_messages():
                nonlocal ws_dead
                try:
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("type") == "status":
                            if data.get("document_id") != document_id:
                                continue
                            block_idx = data.get("block_idx")
                            block_status = data.get("status")
                            if block_idx in pending and block_status in ("cached", "error", "skipped"):
                                pending.discard(block_idx)
                                arrived_ms = (time.time() - session.start_time) * 1000
                                requested_ms = request_times.get(block_idx, 0.0)
                                duration_ms = 0.0

                                if block_status == "cached":
                                    audio_url = data.get("audio_url")
                                    assert audio_url, f"Block {block_idx} cached but no audio_url"
                                    resp = await http_client.get(audio_url)
                                    resp.raise_for_status()
                                    duration_ms = get_audio_duration_ms(resp.content)
                                    block_durations[block_idx] = duration_ms

                                session.block_arrivals.append(
                                    BlockArrival(
                                        idx=block_idx,
                                        requested_ms=requested_ms,
                                        arrived_ms=arrived_ms,
                                        status=block_status,
                                        duration_ms=duration_ms,
                                    )
                                )
                                if block_status == "cached":
                                    cached.add(block_idx)
                                else:
                                    failed.add(block_idx)
                        elif data.get("type") == "error":
                            error_msg = data.get("error", "unknown error")
                            session.errors.append(error_msg)
                            for idx in list(pending):
                                pending.discard(idx)
                                arrived_ms = (time.time() - session.start_time) * 1000
                                session.block_arrivals.append(
                                    BlockArrival(
                                        idx=idx,
                                        requested_ms=request_times.get(idx, 0.0),
                                        arrived_ms=arrived_ms,
                                        status="error",
                                        error=error_msg,
                                    )
                                )
                                failed.add(idx)
                            return
                except websockets.exceptions.ConnectionClosed:
                    pass
                except Exception as e:
                    session.errors.append(f"Message handler crashed: {e}")
                    raise
                finally:
                    ws_dead = True

            msg_task = asyncio.create_task(handle_messages())

            async def request_blocks(count: int):
                nonlocal next_to_request
                for _ in range(count):
                    if next_to_request >= num_blocks:
                        break
                    block_idx = next_to_request
                    next_to_request += 1
                    now = (time.time() - session.start_time) * 1000
                    pending.add(block_idx)
                    request_times[block_idx] = now
                    await ws.send(
                        json.dumps(
                            {
                                "type": "synthesize",
                                "document_id": document_id,
                                "block_indices": [block_idx],
                                "cursor": block_idx,
                                "model": model,
                                "voice": voice,
                                "synthesis_mode": "server",
                            }
                        )
                    )

            await request_blocks(BATCH_SIZE)

            while len(cached) < min_buffer and len(cached) + len(failed) < num_blocks:
                if ws_dead:
                    session.errors.append("WebSocket disconnected during initial buffer")
                    break
                await asyncio.sleep(0.05)

            while playback_position < num_blocks and not ws_dead:
                await asyncio.sleep(0)

                if playback_position in failed:
                    playback_position += 1
                    if on_progress:
                        on_progress(playback_position)
                    continue

                buffer_ahead = len([b for b in cached if b >= playback_position])

                if buffer_ahead < REFILL_THRESHOLD and next_to_request < num_blocks:
                    await request_blocks(BATCH_SIZE)

                if playback_position not in cached:
                    if playback_position in pending or next_to_request > playback_position:
                        underrun_start = time.time()
                        while playback_position not in cached and playback_position not in failed:
                            if ws_dead:
                                session.errors.append(f"WebSocket disconnected waiting for block {playback_position}")
                                failed.add(playback_position)
                                break
                            await asyncio.sleep(0.05)
                        if playback_position not in failed:
                            waited_ms = (time.time() - underrun_start) * 1000
                            if waited_ms > 100:
                                session.underruns.append(Underrun(at_block=playback_position, waited_ms=waited_ms))
                    else:
                        await request_blocks(1)
                        continue

                if playback_position in failed:
                    playback_position += 1
                    if on_progress:
                        on_progress(playback_position)
                    continue

                assert playback_position in block_durations, f"Block {playback_position} cached but duration unknown"
                await asyncio.sleep(block_durations[playback_position] / speed / 1000)
                playback_position += 1
                if on_progress:
                    on_progress(playback_position)

            wait_start = time.time()
            while pending and time.time() - wait_start < 30:
                await asyncio.sleep(0.1)

            msg_task.cancel()
            try:
                await msg_task
            except asyncio.CancelledError:
                pass

    except Exception:
        session.errors.append(traceback.format_exc())
    finally:
        await http_client.aclose()

    session.end_time = time.time()
    return session


@dataclass
class StressTestResult:
    users: int
    blocks_per_user: int
    model: str
    voice: str
    speed: float
    sessions: list[UserSession] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "config": {
                "users": self.users,
                "blocks_per_user": self.blocks_per_user,
                "model": self.model,
                "voice": self.voice,
                "speed": self.speed,
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "document_ids": self.document_ids,
            "sessions": [s.to_dict() for s in self.sessions],
        }

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}_{self.users}users_{self.speed}x.json"
        path = output_dir / filename
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


async def create_test_document(
    base_url: str, token: str, num_blocks: int, user_idx: int, use_cached: bool = False
) -> str:
    if use_cached:
        paragraphs = ["test"] * num_blocks
    else:
        nonce = "".join(random.choices(string.ascii_lowercase, k=8))
        paragraphs = [
            f"Block {i} {nonce}. This is test content for stress testing the synthesis pipeline."
            for i in range(num_blocks)
        ]
    content = "\n\n".join(paragraphs)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/api/v1/documents/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": content, "title": f"Stress Test {user_idx}"},
        )
        resp.raise_for_status()
        return resp.json()["id"]


async def delete_document(base_url: str, token: str, doc_id: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(
            f"{base_url}/api/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()


def _percentile(values: list[float], pct: float) -> float:
    idx = int(len(values) * pct / 100)
    return values[min(idx, len(values) - 1)]


def print_summary(result: StressTestResult, console: Console) -> None:
    table = Table(title="Stress Test Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    total_blocks = result.users * result.blocks_per_user
    total_cached = sum(1 for s in result.sessions for b in s.block_arrivals if b.status == "cached")
    total_errors = sum(len(s.errors) for s in result.sessions)
    total_underruns = sum(len(s.underruns) for s in result.sessions)
    total_underrun_ms = sum(u.waited_ms for s in result.sessions for u in s.underruns)

    # Wall time from ISO timestamps
    if result.started_at and result.finished_at:
        started = datetime.fromisoformat(result.started_at)
        finished = datetime.fromisoformat(result.finished_at)
        wall_s = (finished - started).total_seconds()
    else:
        wall_s = 0

    table.add_row("Users", str(result.users))
    table.add_row("Blocks per user", str(result.blocks_per_user))
    table.add_row("Speed", f"{result.speed}x")
    table.add_row("Model", result.model)
    table.add_row("Wall time", f"{wall_s:.1f}s")
    table.add_row("", "")
    table.add_row("Blocks completed", f"{total_cached}/{total_blocks}")
    table.add_row("Errors", str(total_errors))
    table.add_row(
        "Underruns",
        f"{total_underruns} ({total_underrun_ms:.0f}ms total, {total_underrun_ms / max(result.users, 1):.0f}ms/user avg)",
    )

    round_trips = sorted(b.round_trip_ms for s in result.sessions for b in s.block_arrivals if b.status == "cached")
    if round_trips:
        table.add_row("", "")
        table.add_row("Round trip avg (ms)", f"{sum(round_trips) / len(round_trips):.0f}")
        table.add_row("Round trip p50 (ms)", f"{_percentile(round_trips, 50):.0f}")
        table.add_row("Round trip p95 (ms)", f"{_percentile(round_trips, 95):.0f}")
        table.add_row("Round trip max (ms)", f"{max(round_trips):.0f}")

    ttfa_values = []
    for s in result.sessions:
        arrivals_sorted = sorted(s.block_arrivals, key=lambda b: b.idx)
        cached_arrivals = [b for b in arrivals_sorted if b.status == "cached"]
        if len(cached_arrivals) >= 2:
            ttfa_values.append(cached_arrivals[1].arrived_ms)

    if ttfa_values:
        ttfa_sorted = sorted(ttfa_values)
        table.add_row("", "")
        table.add_row("TTFA p50 (ms)", f"{_percentile(ttfa_sorted, 50):.0f}")
        table.add_row("TTFA p95 (ms)", f"{_percentile(ttfa_sorted, 95):.0f}")
        table.add_row("TTFA max (ms)", f"{max(ttfa_values):.0f}")

    first_block_times = []
    for s in result.sessions:
        cached_arrivals = [b for b in s.block_arrivals if b.status == "cached"]
        if cached_arrivals:
            first_block_times.append(min(b.arrived_ms for b in cached_arrivals))

    if first_block_times:
        fbt_sorted = sorted(first_block_times)
        table.add_row("", "")
        table.add_row("First block p50 (ms)", f"{_percentile(fbt_sorted, 50):.0f}")
        table.add_row("First block max (ms)", f"{max(first_block_times):.0f}")

    audio_durations = [b.duration_ms for s in result.sessions for b in s.block_arrivals if b.duration_ms > 0]
    if audio_durations:
        dur_sorted = sorted(audio_durations)
        total_audio_s = sum(audio_durations) / 1000
        table.add_row("", "")
        table.add_row("Audio duration avg (ms)", f"{sum(audio_durations) / len(audio_durations):.0f}")
        table.add_row("Audio duration p50 (ms)", f"{_percentile(dur_sorted, 50):.0f}")
        table.add_row("Audio duration p95 (ms)", f"{_percentile(dur_sorted, 95):.0f}")
        table.add_row("Total audio", f"{total_audio_s:.1f}s ({total_audio_s / 60:.1f}min)")

    console.print(table)


async def run_stress_test(
    base_url: str,
    token: str,
    users: int,
    blocks: int,
    model: str,
    voice: str,
    speed: float,
    use_cached: bool,
    stagger: float,
    min_buffer: int,
    console: Console,
    progress: Progress,
) -> StressTestResult:
    result = StressTestResult(
        users=users,
        blocks_per_user=blocks,
        model=model,
        voice=voice,
        speed=speed,
    )
    result.started_at = datetime.now().isoformat()

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/v1/ws/tts"

    console.print(f"[dim]Creating {users} test documents...[/dim]")
    doc_ids = []
    for i in range(users):
        doc_id = await create_test_document(base_url, token, blocks, i, use_cached=use_cached)
        doc_ids.append(doc_id)
    result.document_ids = doc_ids

    console.print(f"[dim]Running {users} concurrent users at {speed}x speed...[/dim]")

    user_tasks: dict[int, TaskID] = {}
    for i in range(users):
        user_tasks[i] = progress.add_task(f"User {i}", total=blocks)

    def make_progress_callback(user_idx: int):
        def callback(completed: int):
            progress.update(user_tasks[user_idx], completed=completed)

        return callback

    async def run_with_stagger(i: int) -> UserSession:
        if stagger > 0 and i > 0:
            await asyncio.sleep(i * stagger / (users - 1) if users > 1 else 0)
        return await run_user_session(
            user_id=i,
            base_url=base_url,
            ws_url=ws_url,
            token=token,
            document_id=doc_ids[i],
            num_blocks=blocks,
            model=model,
            voice=voice,
            speed=speed,
            min_buffer=min_buffer,
            on_progress=make_progress_callback(i),
        )

    sessions = await asyncio.gather(*(run_with_stagger(i) for i in range(users)))
    result.sessions = list(sessions)
    result.finished_at = datetime.now().isoformat()

    console.print("[dim]Cleaning up test documents...[/dim]")
    for doc_id in doc_ids:
        try:
            await delete_document(base_url, token, doc_id)
        except Exception as e:
            console.print(f"[yellow]Warning: failed to delete {doc_id}: {e}[/yellow]")

    return result


def _load_env_file(path: Path) -> dict[str, str]:
    """Load key=value pairs from an env file."""
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def main(
    base_url: str = "https://yapit.md",
    token: str = "",
    users: int = 5,
    blocks: int = 20,
    model: str = "kokoro",
    speed: float = 1.0,
    use_cached: bool = False,
    stagger: float = 0.0,
    min_buffer: int = DEFAULT_MIN_BUFFER_TO_START,
    output_dir: Path = Path("scripts/stress_test_results"),
    env_file: Path = Path(".env"),
) -> None:
    """Stress test for TTS synthesis pipeline. Simulates concurrent users with
    realistic playback (prefetching, buffering) matching the frontend algorithm.
    Captures per-block timing for TTFA analysis.

    Auth: add PROD_TEST_EMAIL/PROD_TEST_PASSWORD to .env.sops, run make prod-env.
    Or pass --token directly. Use --use-cached to test without credits.

    Examples::

        uv run scripts/stress_test.py --users 5
        uv run scripts/stress_test.py --users 3 --speed 2 --min-buffer 1
        uv run scripts/stress_test.py --users 10 --stagger 2.0

    Args:
        base_url: API base URL
        token: Auth token (alternative to env file credentials)
        users: Number of concurrent simulated playback sessions
        blocks: Number of blocks per session
        model: TTS model slug (voice auto-selected per model)
        speed: Playback speed multiplier applied to actual audio duration from OGG headers
        use_cached: Use 'test' content (likely cached) instead of unique content
        stagger: Spread user starts over this many seconds (0=all start together)
        min_buffer: Blocks to buffer before starting playback (1=play immediately, 2=default)
        output_dir: Directory for JSON results
        env_file: Env file with TEST_EMAIL/TEST_PASSWORD (run make prod-env first)
    """
    voice = MODEL_DEFAULT_VOICES.get(model)
    if not voice:
        print(f"Error: Unknown model '{model}'. Known models: {', '.join(MODEL_DEFAULT_VOICES)}")
        return

    env = _load_env_file(env_file)
    email = env.get("TEST_EMAIL", "")
    password = env.get("TEST_PASSWORD", "")

    if not token and email and password:
        token = get_auth_token(base_url, email, password)

    if not token:
        print("Error: Provide --token OR add TEST_EMAIL/TEST_PASSWORD to env file (run make prod-env)")
        return

    console = Console()

    console.print("\n[bold]TTS Stress Test[/bold]")
    console.print(f"  Target: {base_url}")
    console.print(f"  Users: {users}")
    console.print(f"  Blocks/user: {blocks}")
    console.print(f"  Speed: {speed}x")
    console.print(f"  Model: {model} (voice: {voice})")
    if min_buffer != DEFAULT_MIN_BUFFER_TO_START:
        console.print(f"  Min buffer: {min_buffer} blocks")
    if stagger > 0:
        console.print(f"  Stagger: {stagger}s between users")
    console.print()

    with Progress() as progress:
        result = asyncio.run(
            run_stress_test(
                base_url, token, users, blocks, model, voice, speed, use_cached, stagger, min_buffer, console, progress
            )
        )

    console.print()
    print_summary(result, console)

    output_path = result.save(output_dir)
    console.print(f"\n[dim]Results saved to: {output_path}[/dim]")


if __name__ == "__main__":
    tyro.cli(main)
