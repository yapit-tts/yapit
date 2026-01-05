# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich", "websockets", "httpx"]
# ///
"""Load test for TTS synthesis — simulate concurrent users.

Usage:
    # Quick test with 5 users, 10 blocks each
    uv run scripts/load_test.py

    # Heavy load: 20 users, 50 blocks each
    uv run scripts/load_test.py --users 20 --blocks 50

    # With auth token (required for actual synthesis)
    uv run scripts/load_test.py --token $(make token)

    # Create test document first
    uv run scripts/load_test.py --create-document

After running, analyze results with:
    uv run scripts/analyze_metrics.py --since "5 minutes"
"""

import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass, field
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


async def get_auth_token(base_url: str, env_file: Path) -> str:
    """Get auth token using dev credentials."""
    # Read env file to get Stack Auth config
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
        # Stack Auth runs on port 8102 in dev
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
    paragraphs = [
        f"User {user_idx} test paragraph {i}. This text generates unique audio for load testing. "
        f"The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs."
        for i in range(num_blocks)
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


async def simulate_user(
    user_id: int,
    ws_url: str,
    token: str,
    doc_id: uuid.UUID,
    num_blocks: int,
    model: str,
    voice: str,
    delay_range: tuple[float, float],
    progress: Progress,
    task: TaskID,
) -> UserResult:
    """Simulate a single user requesting synthesis."""
    request_times: list[float] = []
    blocks_completed = 0
    blocks_failed = 0
    pending_blocks: dict[int, float] = {}  # block_idx -> request_time

    start_time = time.time()

    try:
        async with websockets.connect(
            ws_url,
            additional_headers={"Authorization": f"Bearer {token}"},
        ) as ws:
            # Task to handle incoming messages
            async def handle_messages():
                nonlocal blocks_completed, blocks_failed
                try:
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("type") == "status":
                            block_idx = data.get("block_idx")
                            status = data.get("status")

                            if block_idx in pending_blocks:
                                elapsed = (time.time() - pending_blocks[block_idx]) * 1000
                                del pending_blocks[block_idx]

                                if status == "cached":
                                    blocks_completed += 1
                                    request_times.append(elapsed)
                                elif status == "error":
                                    blocks_failed += 1

                                progress.update(task, advance=1)
                except websockets.exceptions.ConnectionClosed:
                    pass

            # Start message handler
            msg_task = asyncio.create_task(handle_messages())

            # Send synthesis requests with delays
            for block_idx in range(num_blocks):
                # Random delay between requests (simulate user scrolling/reading)
                await asyncio.sleep(random.uniform(*delay_range))

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

            # Wait for remaining responses (with timeout)
            timeout = 60  # seconds
            wait_start = time.time()
            while pending_blocks and (time.time() - wait_start) < timeout:
                await asyncio.sleep(0.1)

            msg_task.cancel()
            try:
                await msg_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"User {user_id} error: {e}")

    total_time = (time.time() - start_time) * 1000

    return UserResult(
        user_id=user_id,
        blocks_requested=num_blocks,
        blocks_completed=blocks_completed,
        blocks_failed=blocks_failed,
        total_time_ms=total_time,
        request_times=request_times,
    )


def print_results(results: list[UserResult], console: Console) -> None:
    """Print load test results."""
    all_times = [t for r in results for t in r.request_times]

    # Summary table
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


@dataclass
class Config:
    """Load test configuration."""

    users: int = 5
    """Number of concurrent simulated users."""

    blocks: int = 20
    """Number of blocks each user requests."""

    model: str = "kokoro-cpu"
    """TTS model to use."""

    voice: str = "af_heart"
    """Voice to use."""

    delay_min: float = 0.1
    """Minimum delay between block requests (seconds)."""

    delay_max: float = 0.5
    """Maximum delay between block requests (seconds)."""

    base_url: str = "http://localhost:8000"
    """Backend base URL."""

    token: str | None = None
    """Auth token (if not provided, will attempt to get one)."""

    document_id: str | None = None
    """Existing document ID to use (if not provided, creates test document)."""

    env_file: Path = field(default_factory=lambda: Path(".env.dev"))
    """Path to .env.dev for auth config."""


async def run_load_test(config: Config) -> None:
    console = Console()

    # Get auth token
    token = config.token
    if not token:
        console.print("[dim]Getting auth token...[/dim]")
        try:
            token = await get_auth_token(config.base_url, config.env_file)
        except Exception as e:
            console.print(f"[red]Failed to get auth token: {e}[/red]")
            console.print("[yellow]Try: uv run scripts/load_test.py --token $(make token)[/yellow]")
            return

    # Create documents — one per user to avoid cache hits between users
    if config.document_id:
        # Shared doc mode (for cache behavior testing)
        doc_id = uuid.UUID(config.document_id)
        num_blocks = await get_document_blocks(config.base_url, token, doc_id)
        if config.blocks > num_blocks:
            console.print(f"[yellow]Document has only {num_blocks} blocks, using that[/yellow]")
            blocks_per_user = num_blocks
        else:
            blocks_per_user = config.blocks
        doc_ids = [doc_id] * config.users  # All users share same doc
        console.print("[yellow]Shared document mode — users will get cache hits[/yellow]")
    else:
        # Real load test: each user gets unique document
        console.print(f"[dim]Creating {config.users} test documents ({config.blocks} blocks each)...[/dim]")
        doc_ids = []
        for i in range(config.users):
            doc_id = await create_test_document(config.base_url, token, config.blocks, user_idx=i)
            doc_ids.append(doc_id)
        blocks_per_user = config.blocks
        console.print(f"[dim]Created {len(doc_ids)} documents[/dim]")

    ws_url = config.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/v1/ws/tts"

    console.print("\n[bold]Starting load test[/bold]")
    console.print(f"  Users: {config.users}")
    console.print(f"  Blocks per user: {blocks_per_user}")
    console.print(f"  Model: {config.model}")
    console.print(f"  Documents: {len(set(doc_ids))} unique")
    console.print()

    # Run concurrent users
    with Progress() as progress:
        tasks = []
        for i in range(config.users):
            task = progress.add_task(f"User {i + 1}", total=blocks_per_user)
            tasks.append(
                simulate_user(
                    user_id=i,
                    ws_url=ws_url,
                    token=token,
                    doc_id=doc_ids[i],
                    num_blocks=blocks_per_user,
                    model=config.model,
                    voice=config.voice,
                    delay_range=(config.delay_min, config.delay_max),
                    progress=progress,
                    task=task,
                )
            )

        results = await asyncio.gather(*tasks)

    console.print()
    print_results(results, console)

    console.print("\n[dim]Analyze detailed metrics with:[/dim]")
    console.print("[cyan]uv run scripts/analyze_metrics.py --since '5 minutes' --plot[/cyan]")


def main(config: Config) -> None:
    asyncio.run(run_load_test(config))


if __name__ == "__main__":
    tyro.cli(main)
