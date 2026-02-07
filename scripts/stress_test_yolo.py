# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "rich", "httpx", "reportlab"]
# ///
"""YOLO stress test — submit large synthetic PDFs to trigger overflow.

Usage:
    uv run scripts/stress_test_yolo.py --pages 300
    uv run scripts/stress_test_yolo.py --token TOKEN --pages 300
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import tyro
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from rich.console import Console


def _load_env_file(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def _load_stack_auth_creds() -> tuple[str, str]:
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
class YoloTestResult:
    pages: int
    concurrent_docs: int
    ai_transform: bool
    upload_times_ms: list[float]
    processing_times_ms: list[float]
    failed_pages: list[list[int]]
    errors: list[str]
    started_at: str
    finished_at: str

    def to_dict(self) -> dict:
        return {
            "pages": self.pages,
            "concurrent_docs": self.concurrent_docs,
            "ai_transform": self.ai_transform,
            "upload_times_ms": self.upload_times_ms,
            "processing_times_ms": self.processing_times_ms,
            "failed_pages": self.failed_pages,
            "errors": self.errors,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}_yolo_{self.pages}pages_{self.concurrent_docs}docs.json"
        path = output_dir / filename
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


def generate_synthetic_pdf(num_pages: int) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    for i in range(num_pages):
        c.drawString(100, height - 100, f"Page {i + 1}")
        c.drawString(100, height - 130, "Synthetic test content for YOLO stress testing.")
        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer.read()


async def upload_and_process(
    base_url: str,
    token: str,
    pdf_bytes: bytes,
    doc_idx: int,
    ai_transform: bool,
) -> tuple[float, float, list[int], str | None]:
    auth = {"Authorization": f"Bearer {token}"}
    error = None
    failed_pages: list[int] = []

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            # Step 1: prepare/upload — caches the file, returns hash
            upload_start = time.time()
            files = {"file": (f"stress_test_{doc_idx}.pdf", pdf_bytes, "application/pdf")}
            resp = await client.post(
                f"{base_url}/api/v1/documents/prepare/upload",
                headers=auth,
                files=files,
            )
            resp.raise_for_status()
            file_hash = resp.json()["hash"]
            upload_ms = (time.time() - upload_start) * 1000

            # Step 2: create document — blocks until extraction completes (YOLO + Gemini)
            process_start = time.time()
            resp = await client.post(
                f"{base_url}/api/v1/documents/document",
                headers={**auth, "Content-Type": "application/json"},
                json={"hash": file_hash, "ai_transform": ai_transform},
            )
            resp.raise_for_status()
            data = resp.json()
            doc_id = data["id"]
            failed_pages = data.get("failed_pages", [])
            processing_ms = (time.time() - process_start) * 1000

            await client.delete(
                f"{base_url}/api/v1/documents/{doc_id}",
                headers=auth,
            )

    except Exception as e:
        upload_ms = (time.time() - upload_start) * 1000
        processing_ms = 0
        error = str(e)

    return upload_ms, processing_ms, failed_pages, error


async def run_yolo_test(
    base_url: str,
    token: str,
    pages: int,
    concurrent: int,
    ai_transform: bool,
    console: Console,
) -> YoloTestResult:
    result = YoloTestResult(
        pages=pages,
        concurrent_docs=concurrent,
        ai_transform=ai_transform,
        upload_times_ms=[],
        processing_times_ms=[],
        failed_pages=[],
        errors=[],
        started_at=datetime.now().isoformat(),
        finished_at="",
    )

    console.print(f"[dim]Generating {pages}-page synthetic PDF...[/dim]")
    pdf_bytes = generate_synthetic_pdf(pages)
    console.print(f"[dim]PDF size: {len(pdf_bytes) / 1024:.1f} KB[/dim]")

    console.print(f"[dim]Uploading {concurrent} documents concurrently...[/dim]")
    tasks = [upload_and_process(base_url, token, pdf_bytes, i, ai_transform) for i in range(concurrent)]
    results = await asyncio.gather(*tasks)

    for upload_ms, processing_ms, failed, error in results:
        result.upload_times_ms.append(upload_ms)
        result.processing_times_ms.append(processing_ms)
        result.failed_pages.append(failed)
        if error:
            result.errors.append(error)

    result.finished_at = datetime.now().isoformat()
    return result


def main(
    base_url: str = "https://yapit.md",
    token: str = "",
    pages: int = 300,
    concurrent: int = 1,
    ai_transform: bool = True,
    output_dir: Path = Path("scripts/stress_test_results"),
    env_file: Path = Path(".env"),
) -> None:
    """YOLO stress test — submit large synthetic PDFs to trigger overflow processing.

    Auth: add PROD_TEST_EMAIL/PROD_TEST_PASSWORD to .env.sops, run make prod-env.
    Or pass --token directly.

    Args:
        base_url: API base URL
        token: Auth token (alternative to env file credentials)
        pages: Pages per PDF
        concurrent: Number of PDFs to upload concurrently
        ai_transform: Use Gemini+YOLO extraction (True) or free markitdown (False)
        output_dir: Directory for results
        env_file: Env file with TEST_EMAIL/TEST_PASSWORD (run make prod-env first)
    """
    env = _load_env_file(env_file)
    email = env.get("TEST_EMAIL", "")
    password = env.get("TEST_PASSWORD", "")

    if not token and email and password:
        token = get_auth_token(base_url, email, password)

    if not token:
        print("Error: Provide --token OR add TEST_EMAIL/TEST_PASSWORD to env file (run make prod-env)")
        return

    console = Console()
    console.print("\n[bold]YOLO Stress Test[/bold]")
    console.print(f"  Pages: {pages}")
    console.print(f"  Concurrent docs: {concurrent}")
    console.print(f"  AI transform: {ai_transform}")
    console.print()

    result = asyncio.run(run_yolo_test(base_url, token, pages, concurrent, ai_transform, console))

    console.print()
    if result.upload_times_ms:
        console.print(f"Upload times: {[f'{t:.0f}ms' for t in result.upload_times_ms]}")
    if result.processing_times_ms:
        console.print(f"Processing times: {[f'{t:.0f}ms' for t in result.processing_times_ms]}")
    total_failed = sum(len(fp) for fp in result.failed_pages)
    if total_failed:
        console.print(f"[yellow]Failed pages: {total_failed}[/yellow]")
    if result.errors:
        console.print(f"[red]Errors: {result.errors}[/red]")

    output_path = result.save(output_dir)
    console.print(f"\n[dim]Results saved to: {output_path}[/dim]")


if __name__ == "__main__":
    tyro.cli(main)
