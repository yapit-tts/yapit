#!/usr/bin/env python3
"""Visualize parsed markdown document structure.

Parses a markdown file through the processor and outputs an HTML visualization
showing block structure, types, audio indices, and content.

Usage:
    uv run scripts/dev/visualize_parsed_document.py [input.md] [output.html]

    Defaults to scripts/dev/test_document.md -> /tmp/parsed_document.html
"""
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

import html
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from yapit.gateway.processors.markdown import parse_markdown, transform_to_document


def escape(text: str) -> str:
    """HTML escape text."""
    return html.escape(text) if text else ""


def render_block_html(block, depth: int = 0) -> str:
    """Render a single block as HTML visualization."""
    indent = "  " * depth
    block_type = block.type
    block_id = block.id
    audio_idx = block.audio_block_idx

    # Color coding by block type
    colors = {
        "heading": "#4a9eff",
        "paragraph": "#6dd66d",
        "list": "#ffa64a",
        "blockquote": "#d966d9",
        "code": "#888888",
        "math": "#888888",
        "table": "#888888",
        "hr": "#cccccc",
        "image": "#888888",
    }
    color = colors.get(block_type, "#999999")
    has_audio = audio_idx is not None

    parts = [f'{indent}<div class="block" style="border-left: 4px solid {color};">']
    parts.append(f'{indent}  <div class="block-header">')
    parts.append(f'{indent}    <span class="block-type" style="background: {color};">{block_type}</span>')
    parts.append(f'{indent}    <span class="block-id">{block_id}</span>')

    if has_audio:
        parts.append(f'{indent}    <span class="audio-idx">🔊 audio[{audio_idx}]</span>')
    else:
        parts.append(f'{indent}    <span class="no-audio">🔇 no audio</span>')

    parts.append(f"{indent}  </div>")

    # Content rendering based on type
    if block_type == "heading":
        parts.append(f'{indent}  <div class="block-meta">Level: h{block.level}</div>')
        parts.append(f'{indent}  <div class="block-html">{block.html}</div>')
        parts.append(f'{indent}  <div class="block-plain">Plain: {escape(block.plain_text)}</div>')

    elif block_type == "paragraph":
        parts.append(f'{indent}  <div class="block-html">{block.html}</div>')
        parts.append(
            f'{indent}  <div class="block-plain">Plain: {escape(block.plain_text[:200])}{"..." if len(block.plain_text) > 200 else ""}</div>'
        )

    elif block_type == "code":
        lang = block.language or "plain"
        parts.append(f'{indent}  <div class="block-meta">Language: {lang}</div>')
        preview = block.content[:200] + ("..." if len(block.content) > 200 else "")
        parts.append(f'{indent}  <pre class="code-preview">{escape(preview)}</pre>')

    elif block_type == "math":
        parts.append(f'{indent}  <div class="block-meta">Display mode: {block.display_mode}</div>')
        parts.append(f'{indent}  <pre class="math-preview">{escape(block.content)}</pre>')

    elif block_type == "list":
        list_type = "ordered" if block.ordered else "unordered"
        parts.append(f'{indent}  <div class="block-meta">{list_type}, {len(block.items)} items</div>')
        parts.append(f'{indent}  <ul class="list-preview">')
        for item in block.items[:5]:
            parts.append(f"{indent}    <li>{item.html}</li>")
        if len(block.items) > 5:
            parts.append(f"{indent}    <li>... and {len(block.items) - 5} more</li>")
        parts.append(f"{indent}  </ul>")
        parts.append(f'{indent}  <div class="block-plain">Plain: {escape(block.plain_text[:150])}...</div>')

    elif block_type == "blockquote":
        parts.append(f'{indent}  <div class="block-meta">{len(block.blocks)} nested blocks</div>')
        parts.append(f'{indent}  <div class="nested-blocks">')
        for nested in block.blocks:
            parts.append(render_block_html(nested, depth + 2))
        parts.append(f"{indent}  </div>")
        parts.append(f'{indent}  <div class="block-plain">Plain: {escape(block.plain_text[:150])}...</div>')

    elif block_type == "table":
        parts.append(f'{indent}  <div class="block-meta">{len(block.headers)} cols, {len(block.rows)} rows</div>')
        parts.append(f'{indent}  <table class="table-preview">')
        parts.append(f"{indent}    <tr>")
        for h in block.headers:
            parts.append(f"{indent}      <th>{h}</th>")
        parts.append(f"{indent}    </tr>")
        for row in block.rows[:3]:
            parts.append(f"{indent}    <tr>")
            for cell in row:
                parts.append(f"{indent}      <td>{cell}</td>")
            parts.append(f"{indent}    </tr>")
        if len(block.rows) > 3:
            parts.append(
                f'{indent}    <tr><td colspan="{len(block.headers)}">... {len(block.rows) - 3} more rows</td></tr>'
            )
        parts.append(f"{indent}  </table>")

    elif block_type == "hr":
        parts.append(f'{indent}  <hr class="hr-preview" />')

    parts.append(f"{indent}</div>")
    return "\n".join(parts)


def generate_html(doc, source_path: str) -> str:
    """Generate full HTML document visualization."""
    # Count stats
    total_blocks = len(doc.blocks)
    audio_blocks = [b for b in doc.blocks if b.audio_block_idx is not None]
    block_types = {}
    for b in doc.blocks:
        block_types[b.type] = block_types.get(b.type, 0) + 1

    blocks_html = "\n".join(render_block_html(b) for b in doc.blocks)

    # Build type counts HTML
    type_colors = {
        "heading": "#4a9eff",
        "paragraph": "#6dd66d",
        "list": "#ffa64a",
        "blockquote": "#d966d9",
        "code": "#555",
        "math": "#555",
        "table": "#555",
        "hr": "#444",
    }
    type_counts_html = "".join(
        f'<span class="type-count" style="background: {type_colors.get(t, "#666")}; color: #000;">{t}: {c}</span>'
        for t, c in sorted(block_types.items())
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Parsed Document Visualization</title>
    <style>
        :root {{
            --bg: #1a1a2e;
            --surface: #16213e;
            --text: #eee;
            --text-muted: #888;
            --border: #333;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'SF Mono', 'Fira Code', monospace;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
            line-height: 1.5;
        }}
        h1 {{ color: #4a9eff; margin-bottom: 10px; }}
        .stats {{
            background: var(--surface);
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
        }}
        .stat {{ display: flex; flex-direction: column; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #4a9eff; }}
        .stat-label {{ font-size: 12px; color: var(--text-muted); }}
        .type-counts {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }}
        .type-count {{
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .blocks-container {{ display: flex; flex-direction: column; gap: 10px; }}
        .block {{
            background: var(--surface);
            border-radius: 8px;
            padding: 12px 15px;
            margin-left: 20px;
        }}
        .nested-blocks {{ margin-top: 10px; }}
        .nested-blocks .block {{ margin-left: 0; }}
        .block-header {{
            display: flex;
            gap: 10px;
            align-items: center;
            margin-bottom: 8px;
        }}
        .block-type {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            color: #000;
        }}
        .block-id {{
            font-size: 11px;
            color: var(--text-muted);
        }}
        .audio-idx {{
            font-size: 11px;
            color: #6dd66d;
        }}
        .no-audio {{
            font-size: 11px;
            color: #666;
        }}
        .block-meta {{
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 5px;
        }}
        .block-html {{
            padding: 8px;
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
            margin-bottom: 5px;
        }}
        .block-html a {{ color: #4a9eff; }}
        .block-html strong {{ color: #ffa64a; }}
        .block-html em {{ color: #d966d9; }}
        .block-html code {{
            background: rgba(255,255,255,0.1);
            padding: 1px 4px;
            border-radius: 3px;
            font-size: 12px;
        }}
        .block-plain {{
            font-size: 11px;
            color: var(--text-muted);
            font-style: italic;
        }}
        pre.code-preview, pre.math-preview {{
            background: #0d1117;
            padding: 10px;
            border-radius: 4px;
            font-size: 12px;
            overflow-x: auto;
            margin: 5px 0;
        }}
        .list-preview {{
            margin: 5px 0;
            padding-left: 25px;
            font-size: 13px;
        }}
        .table-preview {{
            border-collapse: collapse;
            font-size: 12px;
            margin: 5px 0;
        }}
        .table-preview th, .table-preview td {{
            border: 1px solid var(--border);
            padding: 5px 10px;
        }}
        .table-preview th {{
            background: rgba(255,255,255,0.1);
        }}
        hr.hr-preview {{
            border: none;
            border-top: 2px dashed var(--border);
            margin: 5px 0;
        }}
        .source {{ font-size: 12px; color: var(--text-muted); margin-bottom: 20px; }}
    </style>
</head>
<body>
    <h1>📄 Parsed Document Visualization</h1>
    <div class="source">Source: {escape(source_path)}</div>

    <div class="stats">
        <div class="stat">
            <span class="stat-value">{total_blocks}</span>
            <span class="stat-label">Total Blocks</span>
        </div>
        <div class="stat">
            <span class="stat-value">{len(audio_blocks)}</span>
            <span class="stat-label">Audio Blocks</span>
        </div>
        <div class="stat">
            <span class="stat-value">{total_blocks - len(audio_blocks)}</span>
            <span class="stat-label">Non-Audio Blocks</span>
        </div>
    </div>

    <div class="type-counts">
        {type_counts_html}
    </div>

    <div class="blocks-container">
{blocks_html}
    </div>
</body>
</html>
"""


def main():
    # Parse arguments
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "test_document.md"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/parsed_document.html")

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    # Read and parse
    print(f"Reading: {input_path}")
    markdown_text = input_path.read_text()

    print("Parsing markdown...")
    ast = parse_markdown(markdown_text)

    print("Transforming to structured document...")
    doc = transform_to_document(ast)

    # Generate HTML
    print("Generating visualization...")
    html_content = generate_html(doc, str(input_path))

    # Write output
    output_path.write_text(html_content)
    print(f"✅ Written to: {output_path}")
    print(f"   Open in browser: file://{output_path.absolute()}")

    # Print summary
    print("\nSummary:")
    print(f"  Total blocks: {len(doc.blocks)}")
    audio_count = sum(1 for b in doc.blocks if b.audio_block_idx is not None)
    print(f"  Audio blocks: {audio_count}")
    print(f"  Non-audio blocks: {len(doc.blocks) - audio_count}")


if __name__ == "__main__":
    main()
