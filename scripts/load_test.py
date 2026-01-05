# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich", "websockets", "httpx"]
# ///
"""Load test for TTS synthesis — simulate concurrent users with realistic playback.

Usage:
    # Realistic playback simulation (default)
    uv run scripts/load_test.py

    # Burst mode (old behavior - hammer all requests)
    uv run scripts/load_test.py --burst

    # Heavy load: 20 users, 50 blocks each
    uv run scripts/load_test.py --users 20 --blocks 50

    # Custom buffering params (mirrors frontend algorithm)
    uv run scripts/load_test.py --initial-buffer 4 --prefetch-threshold 8 --prefetch-batch 8

After running, analyze results with:
    uv run scripts/analyze_metrics.py --since "5 minutes"
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import tyro
import websockets
from rich import box
from rich.console import Console
from rich.progress import Progress, TaskID
from rich.table import Table


@dataclass
class UserResult:
    """Results from a single simulated user."""

    user_id: int
    blocks_requested: int
    blocks_completed: int
    blocks_failed: int
    total_time_ms: float
    request_times: list[float]  # Time from request to cached status per block
    buffer_underruns: int = 0  # Times playback caught up to buffer
    min_buffer_size: int = 0  # Lowest buffer level during playback


async def get_auth_token(base_url: str, env_file: Path) -> str:
    """Get auth token using dev credentials."""
    env = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()

    project_id = env.get("STACK_AUTH_PROJECT_ID", "")
    client_key = env.get("STACK_AUTH_CLIENT_KEY", "")

    if not project_id or not client_key:
        raise ValueError("Could not find Stack Auth config in .env.dev")

    async with httpx.AsyncClient() as client:
        stack_url = base_url.replace(":8000", ":8102")
        resp = await client.post(
            f"{stack_url}/api/v1/auth/password/sign-in",
            headers={
                "X-Stack-Access-Type": "client",
                "X-Stack-Project-Id": project_id,
                "X-Stack-Publishable-Client-Key": client_key,
                "Content-Type": "application/json",
            },
            json={"email": "dev@example.com", "password": "dev-password-123"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def create_test_document(base_url: str, token: str, num_blocks: int, user_idx: int = 0) -> uuid.UUID:
    """Create a test document with dummy blocks."""
    # Generate unique content per user (different text = different variant_hash)
    # Use short single-sentence paragraphs to avoid parser splitting
    paragraphs = [
        f"User {user_idx} paragraph {i} with unique content for load testing synthesis." for i in range(num_blocks)
    ]
    content = "\n\n".join(paragraphs)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/v1/documents/text",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": content, "title": f"Load Test User {user_idx}"},
        )
        resp.raise_for_status()
        doc_id = resp.json()["id"]
        return uuid.UUID(doc_id)


async def get_document_blocks(base_url: str, token: str, doc_id: uuid.UUID) -> int:
    """Get number of blocks in a document."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/v1/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return len(resp.json().get("blocks", []))


async def simulate_user_burst(
    user_id: int,
    ws_url: str,
    token: str,
    doc_id: uuid.UUID,
    num_blocks: int,
    model: str,
    voice: str,
    progress: Progress,
    task: TaskID,
) -> UserResult:
    """Burst mode: request all blocks as fast as possible (old behavior)."""
    request_times: list[float] = []
    blocks_completed = 0
    blocks_failed = 0
    pending_blocks: dict[int, float] = {}

    start_time = time.time()

    try:
        async with websockets.connect(f"{ws_url}?token={token}") as ws:

            async def handle_messages():
                nonlocal blocks_completed, blocks_failed
                try:
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("type") == "status":
                            block_idx = data.get("block_idx")
                            status = data.get("status")
                            if block_idx in pending_blocks and status in ("cached", "error"):
                                elapsed = (time.time() - pending_blocks[block_idx]) * 1000
                                del pending_blocks[block_idx]
                                if status == "cached":
                                    blocks_completed += 1
                                    request_times.append(elapsed)
                                else:
                                    blocks_failed += 1
                                progress.update(task, advance=1)
                except websockets.exceptions.ConnectionClosed:
                    pass

            msg_task = asyncio.create_task(handle_messages())

            # Blast all requests
            for block_idx in range(num_blocks):
                pending_blocks[block_idx] = time.time()
                await ws.send(
                    json.dumps(
                        {
                            "type": "synthesize",
                            "document_id": str(doc_id),
                            "block_indices": [block_idx],
                            "cursor": block_idx,
                            "model": model,
                            "voice": voice,
                            "synthesis_mode": "server",
                        }
                    )
                )

            while pending_blocks:
                await asyncio.sleep(0.5)
            msg_task.cancel()
            try:
                await msg_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"User {user_id} error: {e}")

    return UserResult(
        user_id=user_id,
        blocks_requested=num_blocks,
        blocks_completed=blocks_completed,
        blocks_failed=blocks_failed,
        total_time_ms=(time.time() - start_time) * 1000,
        request_times=request_times,
    )


async def simulate_user_playback(
    user_id: int,
    ws_url: str,
    token: str,
    doc_id: uuid.UUID,
    num_blocks: int,
    model: str,
    voice: str,
    initial_buffer: int,
    prefetch_threshold: int,
    prefetch_batch: int,
    audio_duration_ms: float,
    progress: Progress,
    task: TaskID,
) -> UserResult:
    """Playback mode: simulate realistic user with buffering algorithm.

    Mirrors frontend behavior:
    1. Buffer initial_buffer blocks before "starting playback"
    2. When cached < prefetch_threshold, request next prefetch_batch blocks
    3. Consume blocks at audio_duration_ms rate (simulated playback)
    4. Track buffer underruns (playback catches up to synthesis)
    """
    request_times: list[float] = []
    blocks_completed = 0
    blocks_failed = 0
    buffer_underruns = 0
    min_buffer_size = num_blocks  # Track lowest buffer level

    pending_blocks: dict[int, float] = {}  # block_idx -> request_time
    cached_blocks: set[int] = set()  # blocks ready for playback
    failed_blocks: set[int] = set()  # blocks that failed (skip during playback)
    next_to_request = 0  # next block index to request
    playback_position = 0  # current "playback" position

    start_time = time.time()

    try:
        async with websockets.connect(f"{ws_url}?token={token}") as ws:

            async def handle_messages():
                nonlocal blocks_completed, blocks_failed
                try:
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("type") == "status":
                            block_idx = data.get("block_idx")
                            status = data.get("status")
                            if block_idx in pending_blocks and status in ("cached", "error"):
                                elapsed = (time.time() - pending_blocks[block_idx]) * 1000
                                del pending_blocks[block_idx]
                                if status == "cached":
                                    blocks_completed += 1
                                    cached_blocks.add(block_idx)
                                    request_times.append(elapsed)
                                else:
                                    blocks_failed += 1
                                    failed_blocks.add(block_idx)  # Track so playback can skip
                                progress.update(task, advance=1)
                except websockets.exceptions.ConnectionClosed:
                    pass

            msg_task = asyncio.create_task(handle_messages())

            async def request_blocks(count: int):
                """Request next `count` blocks."""
                nonlocal next_to_request
                for _ in range(count):
                    if next_to_request >= num_blocks:
                        break
                    block_idx = next_to_request
                    next_to_request += 1
                    pending_blocks[block_idx] = time.time()
                    await ws.send(
                        json.dumps(
                            {
                                "type": "synthesize",
                                "document_id": str(doc_id),
                                "block_indices": [block_idx],
                                "cursor": block_idx,
                                "model": model,
                                "voice": voice,
                                "synthesis_mode": "server",
                            }
                        )
                    )

            # Phase 1: Request initial buffer
            await request_blocks(initial_buffer)

            # Wait for initial buffer to fill before "starting playback"
            # Also proceed if all initial blocks failed or completed
            wait_start = time.time()
            while len(cached_blocks) < initial_buffer and len(cached_blocks) + len(failed_blocks) < num_blocks:
                await asyncio.sleep(0.1)
                if time.time() - wait_start > 60:  # 60s timeout for initial buffer
                    break

            # Phase 2: Simulate playback with prefetching
            while playback_position < num_blocks:
                # Skip failed blocks
                if playback_position in failed_blocks:
                    playback_position += 1
                    continue

                # Check buffer level (blocks ahead of playback)
                buffer_ahead = len([b for b in cached_blocks if b >= playback_position])
                min_buffer_size = min(min_buffer_size, buffer_ahead)

                # Prefetch if buffer is low
                if buffer_ahead < prefetch_threshold and next_to_request < num_blocks:
                    await request_blocks(prefetch_batch)

                # Check for buffer underrun
                if playback_position not in cached_blocks:
                    if playback_position in pending_blocks or next_to_request > playback_position:
                        # Block is pending, wait for it (underrun) - but with timeout
                        buffer_underruns += 1
                        wait_start = time.time()
                        while playback_position not in cached_blocks and playback_position not in failed_blocks:
                            await asyncio.sleep(0.05)
                            if time.time() - wait_start > 30:  # 30s timeout
                                break
                        if playback_position in failed_blocks:
                            playback_position += 1
                            continue
                    else:
                        # Block not requested yet, request it
                        await request_blocks(1)
                        wait_start = time.time()
                        while playback_position not in cached_blocks and playback_position not in failed_blocks:
                            await asyncio.sleep(0.05)
                            if time.time() - wait_start > 30:
                                break

                # "Play" the block (wait for audio duration)
                await asyncio.sleep(audio_duration_ms / 1000)
                playback_position += 1

            # Wait for any remaining pending blocks
            while pending_blocks:
                await asyncio.sleep(0.1)

            msg_task.cancel()
            try:
                await msg_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"User {user_id} error: {e}")

    return UserResult(
        user_id=user_id,
        blocks_requested=num_blocks,
        blocks_completed=blocks_completed,
        blocks_failed=blocks_failed,
        total_time_ms=(time.time() - start_time) * 1000,
        request_times=request_times,
        buffer_underruns=buffer_underruns,
        min_buffer_size=min_buffer_size,
    )


def print_results(results: list[UserResult], console: Console, playback_mode: bool) -> None:
    """Print load test results."""
    all_times = [t for r in results for t in r.request_times]

    table = Table(title="Load Test Results", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    total_requested = sum(r.blocks_requested for r in results)
    total_completed = sum(r.blocks_completed for r in results)
    total_failed = sum(r.blocks_failed for r in results)

    table.add_row("Users", str(len(results)))
    table.add_row("Blocks Requested", str(total_requested))
    table.add_row("Blocks Completed", str(total_completed))
    table.add_row("Blocks Failed", str(total_failed))
    table.add_row("Success Rate", f"{total_completed / total_requested * 100:.1f}%" if total_requested else "-")

    if playback_mode:
        total_underruns = sum(r.buffer_underruns for r in results)
        min_buffer = min(r.min_buffer_size for r in results)
        table.add_row("", "")
        table.add_row("Buffer Underruns", str(total_underruns))
        table.add_row("Min Buffer Size", str(min_buffer))
        if total_underruns == 0:
            table.add_row("Playback Quality", "[green]Smooth[/green]")
        elif total_underruns < len(results):
            table.add_row("Playback Quality", "[yellow]Minor stutters[/yellow]")
        else:
            table.add_row("Playback Quality", "[red]Frequent buffering[/red]")

    if all_times:
        table.add_row("", "")
        table.add_row("P50 Latency (ms)", f"{sorted(all_times)[len(all_times) // 2]:.0f}")
        table.add_row("P95 Latency (ms)", f"{sorted(all_times)[int(len(all_times) * 0.95)]:.0f}")
        table.add_row("Max Latency (ms)", f"{max(all_times):.0f}")
        table.add_row("Min Latency (ms)", f"{min(all_times):.0f}")

        total_duration = max(r.total_time_ms for r in results) / 1000
        throughput = total_completed / total_duration if total_duration > 0 else 0
        table.add_row("", "")
        table.add_row("Test Duration (s)", f"{total_duration:.1f}")
        table.add_row("Throughput (blocks/s)", f"{throughput:.1f}")

    console.print(table)


async def run_load_test(
    users: int,
    blocks: int,
    model: str,
    voice: str,
    burst: bool,
    initial_buffer: int,
    prefetch_threshold: int,
    prefetch_batch: int,
    audio_duration_ms: float,
    base_url: str,
    token: str | None,
    document_id: str | None,
    env_file: Path,
) -> None:
    console = Console()

    if not token:
        console.print("[dim]Getting auth token...[/dim]")
        try:
            token = await get_auth_token(base_url, env_file)
        except Exception as e:
            console.print(f"[red]Failed to get auth token: {e}[/red]")
            console.print("[yellow]Try: uv run scripts/load_test.py --token $(make token)[/yellow]")
            return

    if document_id:
        doc_id = uuid.UUID(document_id)
        num_blocks = await get_document_blocks(base_url, token, doc_id)
        if blocks > num_blocks:
            console.print(f"[yellow]Document has only {num_blocks} blocks, using that[/yellow]")
            blocks_per_user = num_blocks
        else:
            blocks_per_user = blocks
        doc_ids = [doc_id] * users
        console.print("[yellow]Shared document mode — users will get cache hits[/yellow]")
    else:
        console.print(f"[dim]Creating {users} test documents ({blocks} blocks each)...[/dim]")
        doc_ids = []
        for i in range(users):
            doc_id = await create_test_document(base_url, token, blocks, user_idx=i)
            doc_ids.append(doc_id)
        blocks_per_user = blocks
        console.print(f"[dim]Created {len(doc_ids)} documents[/dim]")

    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/v1/ws/tts"

    mode_str = "burst" if burst else "playback"
    console.print(f"\n[bold]Starting load test ({mode_str} mode)[/bold]")
    console.print(f"  Users: {users}")
    console.print(f"  Blocks per user: {blocks_per_user}")
    console.print(f"  Model: {model}")
    console.print(f"  Documents: {len(set(doc_ids))} unique")
    if not burst:
        console.print(f"  Initial buffer: {initial_buffer}")
        console.print(f"  Prefetch threshold: {prefetch_threshold}")
        console.print(f"  Prefetch batch: {prefetch_batch}")
        console.print(f"  Simulated audio duration: {audio_duration_ms}ms/block")
    console.print()

    with Progress() as progress:
        tasks = []
        for i in range(users):
            task = progress.add_task(f"User {i + 1}", total=blocks_per_user)
            if burst:
                tasks.append(
                    simulate_user_burst(
                        user_id=i,
                        ws_url=ws_url,
                        token=token,
                        doc_id=doc_ids[i],
                        num_blocks=blocks_per_user,
                        model=model,
                        voice=voice,
                        progress=progress,
                        task=task,
                    )
                )
            else:
                tasks.append(
                    simulate_user_playback(
                        user_id=i,
                        ws_url=ws_url,
                        token=token,
                        doc_id=doc_ids[i],
                        num_blocks=blocks_per_user,
                        model=model,
                        voice=voice,
                        initial_buffer=initial_buffer,
                        prefetch_threshold=prefetch_threshold,
                        prefetch_batch=prefetch_batch,
                        audio_duration_ms=audio_duration_ms,
                        progress=progress,
                        task=task,
                    )
                )

        results = await asyncio.gather(*tasks)

    console.print()
    print_results(results, console, playback_mode=not burst)

    console.print("\n[dim]Analyze detailed metrics with:[/dim]")
    console.print("[cyan]uv run scripts/analyze_metrics.py --since '5 minutes' --plot[/cyan]")


def main(
    users: int = 5,
    blocks: int = 20,
    model: str = "kokoro",
    voice: str = "af_heart",
    burst: bool = False,
    initial_buffer: int = 4,
    prefetch_threshold: int = 8,
    prefetch_batch: int = 8,
    audio_duration_ms: float = 4000.0,
    base_url: str = "http://localhost:8000",
    token: str | None = None,
    document_id: str | None = None,
    env_file: Path = Path(".env.dev"),
) -> None:
    """Load test for TTS synthesis — simulate concurrent users with realistic playback.

    Args:
        users: Number of concurrent simulated users.
        blocks: Number of blocks each user requests.
        model: TTS model to use.
        voice: Voice to use.
        burst: Burst mode (old behavior) — request all blocks immediately.
        initial_buffer: Blocks to buffer before starting playback.
        prefetch_threshold: Request more blocks when buffer falls below this.
        prefetch_batch: How many blocks to request when prefetching.
        audio_duration_ms: Simulated audio duration per block (playback speed).
        base_url: Backend base URL.
        token: Auth token (if not provided, will attempt to get one).
        document_id: Existing document ID to use (shared mode, cache hits).
        env_file: Path to .env.dev for auth config.
    """
    asyncio.run(
        run_load_test(
            users=users,
            blocks=blocks,
            model=model,
            voice=voice,
            burst=burst,
            initial_buffer=initial_buffer,
            prefetch_threshold=prefetch_threshold,
            prefetch_batch=prefetch_batch,
            audio_duration_ms=audio_duration_ms,
            base_url=base_url,
            token=token,
            document_id=document_id,
            env_file=env_file,
        )
    )


if __name__ == "__main__":
    tyro.cli(main)
