#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["psycopg"]
# ///
"""Calculate storage usage for documents.

Usage:
  uv run scripts/document_storage.py --id <uuid>
  uv run scripts/document_storage.py --all
  uv run scripts/document_storage.py --all --summary
  uv run scripts/document_storage.py --id <uuid> --json

Requires VPS_HOST env var (e.g., root@46.224.195.97) when running locally.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass
class DocumentStorage:
    id: str
    content_hash: str | None
    document_row_bytes: int
    original_text_bytes: int
    structured_content_bytes: int
    metadata_bytes: int
    block_count: int
    blocks_total_bytes: int
    blocks_text_bytes: int
    image_count: int
    images_total_bytes: int
    image_files: list[tuple[str, int]]  # (filename, size)

    @property
    def db_total_bytes(self) -> int:
        return self.document_row_bytes + self.blocks_total_bytes

    @property
    def total_bytes(self) -> int:
        return self.db_total_bytes + self.images_total_bytes

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content_hash": self.content_hash,
            "db": {
                "document_row_bytes": self.document_row_bytes,
                "original_text_bytes": self.original_text_bytes,
                "structured_content_bytes": self.structured_content_bytes,
                "metadata_bytes": self.metadata_bytes,
                "block_count": self.block_count,
                "blocks_total_bytes": self.blocks_total_bytes,
                "blocks_text_bytes": self.blocks_text_bytes,
                "total_bytes": self.db_total_bytes,
            },
            "images": {
                "count": self.image_count,
                "total_bytes": self.images_total_bytes,
                "files": [{"name": f, "bytes": s} for f, s in self.image_files],
            },
            "total_bytes": self.total_bytes,
        }


def format_bytes(b: int) -> str:
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b / (1024 * 1024):.2f} MB"


def get_document_storage(conn, doc_id: str, images_dir: Path) -> DocumentStorage | None:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                id::text,
                content_hash,
                pg_column_size(d.*) as document_row_bytes,
                pg_column_size(original_text) as original_text_bytes,
                pg_column_size(structured_content) as structured_content_bytes,
                COALESCE(pg_column_size(metadata), 0) as metadata_bytes
            FROM document d
            WHERE id = %s::uuid
            """,
            (doc_id,),
        )
        doc = cur.fetchone()
        if not doc:
            return None

        cur.execute(
            """
            SELECT
                COUNT(*) as block_count,
                COALESCE(SUM(pg_column_size(b.*)), 0) as blocks_total_bytes,
                COALESCE(SUM(pg_column_size(text)), 0) as blocks_text_bytes
            FROM block b
            WHERE document_id = %s::uuid
            """,
            (doc_id,),
        )
        blocks = cur.fetchone()

    image_files: list[tuple[str, int]] = []
    images_total = 0
    if doc["content_hash"]:
        doc_images_dir = images_dir / doc["content_hash"]
        if doc_images_dir.exists():
            for f in sorted(doc_images_dir.iterdir()):
                if f.is_file():
                    size = f.stat().st_size
                    image_files.append((f.name, size))
                    images_total += size

    return DocumentStorage(
        id=doc["id"],
        content_hash=doc["content_hash"],
        document_row_bytes=doc["document_row_bytes"],
        original_text_bytes=doc["original_text_bytes"],
        structured_content_bytes=doc["structured_content_bytes"],
        metadata_bytes=doc["metadata_bytes"],
        block_count=blocks["block_count"],
        blocks_total_bytes=blocks["blocks_total_bytes"],
        blocks_text_bytes=blocks["blocks_text_bytes"],
        image_count=len(image_files),
        images_total_bytes=images_total,
        image_files=image_files,
    )


def get_all_document_ids(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT id::text FROM document ORDER BY created DESC")
        return [row[0] for row in cur.fetchall()]


def print_storage(storage: DocumentStorage, verbose: bool = False) -> None:
    print(f"Document: {storage.id}")
    print(f"  Content hash: {storage.content_hash or 'none'}")
    print(f"  Database: {format_bytes(storage.db_total_bytes)}")
    print(f"    Document row: {format_bytes(storage.document_row_bytes)}")
    print(f"      original_text: {format_bytes(storage.original_text_bytes)}")
    print(f"      structured_content: {format_bytes(storage.structured_content_bytes)}")
    print(f"      metadata: {format_bytes(storage.metadata_bytes)}")
    print(f"    Blocks ({storage.block_count}): {format_bytes(storage.blocks_total_bytes)}")
    print(f"      text content: {format_bytes(storage.blocks_text_bytes)}")
    print(f"  Images ({storage.image_count}): {format_bytes(storage.images_total_bytes)}")
    if verbose and storage.image_files:
        for name, size in storage.image_files:
            print(f"    {name}: {format_bytes(size)}")
    print(f"  TOTAL: {format_bytes(storage.total_bytes)}")


def run_remote(vps_host: str, args: list[str]) -> int:
    """SSH to VPS and run this script inside the gateway container."""
    script_path = Path(__file__)
    script_content = script_path.read_text()

    # Build the remote command
    remote_cmd = f'docker exec -i $(docker ps -qf "name=yapit_gateway") python - {" ".join(args)}'
    ssh_cmd = ["ssh", vps_host, remote_cmd]

    result = subprocess.run(ssh_cmd, input=script_content, text=True)
    return result.returncode


def run_local(args: argparse.Namespace) -> int:
    """Run directly (inside container with DB access)."""
    import psycopg

    database_url = os.environ.get("DATABASE_URL")
    images_dir = Path(os.environ.get("IMAGES_DIR", "/data/images"))

    if not database_url:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        return 1

    # Convert async driver URL to sync format for psycopg
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    with psycopg.connect(database_url) as conn:
        if args.id:
            try:
                UUID(args.id)
            except ValueError:
                print(f"Error: Invalid UUID format: {args.id}", file=sys.stderr)
                return 1

            storage = get_document_storage(conn, args.id, images_dir)
            if not storage:
                print(f"Document not found: {args.id}", file=sys.stderr)
                return 1

            if args.json:
                print(json.dumps(storage.to_dict(), indent=2))
            else:
                print_storage(storage, verbose=args.verbose)

        else:  # --all
            doc_ids = get_all_document_ids(conn)
            results = []
            totals = {"db": 0, "images": 0, "total": 0, "count": 0}

            for doc_id in doc_ids:
                storage = get_document_storage(conn, doc_id, images_dir)
                if storage:
                    results.append(storage)
                    totals["db"] += storage.db_total_bytes
                    totals["images"] += storage.images_total_bytes
                    totals["total"] += storage.total_bytes
                    totals["count"] += 1

            if args.json:
                output = {
                    "documents": [s.to_dict() for s in results],
                    "totals": {
                        "document_count": totals["count"],
                        "db_bytes": totals["db"],
                        "images_bytes": totals["images"],
                        "total_bytes": totals["total"],
                    },
                }
                print(json.dumps(output, indent=2))
            elif args.summary:
                print(f"Documents: {totals['count']}")
                print(f"Database: {format_bytes(totals['db'])}")
                print(f"Images: {format_bytes(totals['images'])}")
                print(f"TOTAL: {format_bytes(totals['total'])}")
            else:
                for storage in results:
                    print_storage(storage, verbose=args.verbose)
                    print()
                print("=" * 40)
                print(f"TOTALS ({totals['count']} documents)")
                print(f"  Database: {format_bytes(totals['db'])}")
                print(f"  Images: {format_bytes(totals['images'])}")
                print(f"  TOTAL: {format_bytes(totals['total'])}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Calculate document storage usage")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="Document UUID")
    group.add_argument("--all", action="store_true", help="Calculate for all documents")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show individual image files")
    parser.add_argument("--summary", "-s", action="store_true", help="With --all, show only totals")
    args = parser.parse_args()

    # If DATABASE_URL is set, we're running inside the container
    if os.environ.get("DATABASE_URL"):
        return run_local(args)

    # Otherwise, SSH to VPS and run there
    vps_host = os.environ.get("VPS_HOST")
    if not vps_host:
        print("Error: VPS_HOST not set (e.g., root@46.224.195.97)", file=sys.stderr)
        return 1

    # Rebuild args for remote execution
    remote_args = []
    if args.id:
        remote_args.extend(["--id", args.id])
    if args.all:
        remote_args.append("--all")
    if args.json:
        remote_args.append("--json")
    if args.verbose:
        remote_args.append("--verbose")
    if args.summary:
        remote_args.append("--summary")

    return run_remote(vps_host, remote_args)


if __name__ == "__main__":
    sys.exit(main())
