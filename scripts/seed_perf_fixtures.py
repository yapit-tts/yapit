# /// script
# requires-python = ">=3.11"
# dependencies = ["tyro", "httpx"]
# ///
"""Seed test documents for frontend performance benchmarking.

Creates documents at escalating block counts with different section structures.
Idempotent — skips documents whose titles already exist.

Usage:
    uv run scripts/seed_perf_fixtures.py
    uv run scripts/seed_perf_fixtures.py --base-url https://staging.example.com
    uv run scripts/seed_perf_fixtures.py --sizes 100 500 1000  # custom sizes
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import tyro

# --- Auth ---


def _load_stack_auth_creds(env: str = "development") -> tuple[str, str]:
    env_file = Path(__file__).parent.parent / "frontend" / f".env.{env}"
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

    # In dev, Stack Auth is at localhost:8102 directly.
    # In prod, it's proxied at {base_url}/auth/.
    if "localhost" in base_url:
        auth_url = "http://localhost:8102/api/v1/auth/password/sign-in"
    else:
        auth_url = f"{base_url}/auth/api/v1/auth/password/sign-in"

    resp = httpx.post(
        auth_url,
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


# --- Markdown generators ---

TITLE_PREFIX = "[perf]"

# Sentences to cycle through (varied lengths to produce realistic block sizes)
SENTENCES = [
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "Advances in machine learning have transformed how we approach complex optimization problems across many domains.",
    "She opened the door to find an empty room, save for a single chair facing the window.",
    "The committee reviewed the proposal and determined that further analysis would be required before proceeding.",
    "Rain fell steadily through the afternoon, pooling in the gutters and running in thin streams down the hill.",
    "According to recent studies, the correlation between sleep quality and cognitive performance is stronger than previously thought.",
    "He picked up the phone, hesitated, then set it back down on the counter without dialing.",
    "The architecture of distributed systems requires careful consideration of failure modes, network partitions, and data consistency.",
    "Sunlight filtered through the canopy, casting dappled shadows across the forest floor where mushrooms grew in clusters.",
    "The fundamental theorem establishes that every continuous function on a closed interval attains its maximum and minimum values.",
]


def _paragraph(block_idx: int, max_chars: int = 0) -> str:
    """Generate a paragraph, optionally truncated to fit within content limits."""
    s1 = SENTENCES[block_idx % len(SENTENCES)]
    s2 = SENTENCES[(block_idx * 3 + 1) % len(SENTENCES)]
    full = f"{s1} {s2}"
    if max_chars > 0 and len(full) > max_chars:
        return full[:max_chars]
    return full


MAX_CONTENT_CHARS = 490_000  # API limit is 500k, leave headroom
SEPARATOR_CHARS = 2  # "\n\n" between paragraphs


def _chars_per_paragraph(n_blocks: int, heading_overhead: int = 0) -> int:
    """Max chars per paragraph to stay under API limit. 0 = no limit."""
    available = MAX_CONTENT_CHARS - heading_overhead - n_blocks * SEPARATOR_CHARS
    budget = available // max(n_blocks, 1)
    # No need to truncate if budget exceeds typical paragraph length
    return 0 if budget >= 220 else max(20, budget)


def generate_flat(n_blocks: int) -> str:
    """No headings, just paragraphs. Pure block-count stress test."""
    max_chars = _chars_per_paragraph(n_blocks)
    return "\n\n".join(_paragraph(i, max_chars) for i in range(n_blocks))


def generate_sectioned(n_blocks: int) -> str:
    """H1 heading every ~20 blocks. Tests section-aware code paths."""
    section_interval = 20
    n_headings = n_blocks // section_interval + 1
    max_chars = _chars_per_paragraph(n_blocks, heading_overhead=n_headings * 20)
    parts: list[str] = []
    section_num = 0
    for i in range(n_blocks):
        if i % section_interval == 0:
            section_num += 1
            parts.append(f"# Section {section_num}")
        parts.append(_paragraph(i, max_chars))
    return "\n\n".join(parts)


def generate_dense_sections(n_blocks: int) -> str:
    """H2 heading every ~5 blocks. Worst case for section scanning."""
    section_interval = 5
    n_headings = n_blocks // section_interval + 1
    max_chars = _chars_per_paragraph(n_blocks, heading_overhead=n_headings * 25)
    parts: list[str] = ["# Document with Dense Sections"]
    section_num = 0
    for i in range(n_blocks):
        if i % section_interval == 0:
            section_num += 1
            parts.append(f"## Subsection {section_num}")
        parts.append(_paragraph(i, max_chars))
    return "\n\n".join(parts)


VARIANTS: dict[str, callable] = {
    "flat": generate_flat,
    "sectioned": generate_sectioned,
    "dense": generate_dense_sections,
}


def fixture_title(variant: str, n_blocks: int) -> str:
    return f"{TITLE_PREFIX} {variant} {n_blocks}b"


# --- API ---


def get_existing_titles(client: httpx.Client) -> set[str]:
    resp = client.get("/v1/documents")
    resp.raise_for_status()
    return {doc["title"] for doc in resp.json() if doc.get("title")}


def create_document(client: httpx.Client, title: str, content: str) -> str:
    resp = client.post(
        "/v1/documents/text",
        json={"title": title, "content": content},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"]


# --- Main ---


@dataclass
class Args:
    """Seed performance test fixtures into the dev environment."""

    base_url: str = "http://localhost:8000"
    email: str = "dev@example.com"
    password: str = "dev-password-123"
    sizes: tuple[int, ...] = (100, 500, 1000, 2000, 5000, 10000)
    variants: tuple[str, ...] = ("flat", "sectioned", "dense")
    dry_run: bool = False


def main(args: Args) -> None:
    print(f"Authenticating as {args.email}...")
    token = get_auth_token(args.base_url, args.email, args.password)

    client = httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": f"Bearer {token}"},
    )

    existing = get_existing_titles(client)
    print(f"Found {len(existing)} existing documents")

    created = 0
    skipped = 0

    for variant in args.variants:
        generator = VARIANTS[variant]
        for size in args.sizes:
            title = fixture_title(variant, size)

            if title in existing:
                print(f"  skip  {title}")
                skipped += 1
                continue

            if args.dry_run:
                content = generator(size)
                print(f"  [dry] {title}  ({len(content):,} chars)")
                continue

            content = generator(size)
            print(f"  seed  {title}  ({len(content):,} chars)...", end=" ", flush=True)
            try:
                doc_id = create_document(client, title, content)
                print(f"→ {doc_id}")
                created += 1
            except httpx.HTTPStatusError as e:
                print(f"FAILED ({e.response.status_code})")
                if e.response.status_code == 422:
                    print(f"         Content too long? {len(content):,} chars")
                continue

    print(f"\nDone. Created {created}, skipped {skipped}.")


if __name__ == "__main__":
    main(tyro.cli(Args))
