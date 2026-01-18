#!/usr/bin/env python3
"""Interactive block splitting visualization server.

Usage:
    python scripts/block_viz_server.py [--port 8765]

Then open http://localhost:8765 in your browser.
"""

import argparse
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from yapit.gateway.markdown import parse_markdown, transform_to_document

app = FastAPI(title="Block Splitter Viz")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_block_info(block, idx: int) -> dict:
    """Extract block info for visualization."""
    info = {
        "idx": idx,
        "type": block.type,
        "plain_text": getattr(block, "plain_text", ""),
        "html": getattr(block, "html", ""),
        "audio_block_idx": getattr(block, "audio_block_idx", None),
        "visual_group_id": getattr(block, "visual_group_id", None),
    }

    if block.type == "heading":
        info["level"] = block.level
    elif block.type == "list":
        info["ordered"] = block.ordered
        info["items"] = [
            {"plain_text": item.plain_text, "html": item.html, "audio_block_idx": item.audio_block_idx}
            for item in block.items
        ]
    elif block.type == "code":
        info["language"] = block.language
        info["content"] = block.content
    elif block.type == "blockquote":
        info["nested_blocks"] = [get_block_info(b, i) for i, b in enumerate(block.blocks)]
    elif block.type == "table":
        info["headers"] = block.headers
        info["rows"] = block.rows

    return info


# Store loaded document
_current_doc: str | None = None


@app.get("/api/parse")
def parse_document(
    max_chars: int = Query(150, ge=50, le=500),
    soft_limit_mult: float = Query(1.2, ge=1.0, le=2.0),
    min_chunk_size: int = Query(30, ge=10, le=100),
):
    """Parse the current document with given parameters."""
    if not _current_doc:
        return {"error": "No document loaded"}

    ast = parse_markdown(_current_doc)
    doc = transform_to_document(
        ast,
        max_block_chars=max_chars,
        soft_limit_mult=soft_limit_mult,
        min_chunk_size=min_chunk_size,
    )
    blocks = [get_block_info(block, i) for i, block in enumerate(doc.blocks)]

    # Collect audio block sizes
    audio_sizes = []
    for block in doc.blocks:
        if block.type == "list":
            for item in block.items:
                if item.audio_block_idx is not None:
                    audio_sizes.append(len(item.plain_text))
        elif block.audio_block_idx is not None:
            audio_sizes.append(len(block.plain_text))

    return {
        "blocks": blocks,
        "stats": {
            "total_blocks": len(blocks),
            "audio_blocks": len(audio_sizes),
            "avg_size": round(sum(audio_sizes) / len(audio_sizes)) if audio_sizes else 0,
            "min_size": min(audio_sizes) if audio_sizes else 0,
            "max_size": max(audio_sizes) if audio_sizes else 0,
        },
    }


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the interactive visualization page."""
    return HTML_PAGE


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Block Splitter - Interactive</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <style>
        [x-cloak] { display: none !important; }
        .block-heading { background-color: #dcfce7; }
        .block-paragraph { background-color: #dbeafe; }
        .block-list { background-color: #f3e8ff; }
        .block-code { background-color: #f1f5f9; font-family: monospace; }
        .block-blockquote { background-color: #fce7f3; border-left: 4px solid #ec4899; }
        .block-table { background-color: #ccfbf1; }
        .block-hr { background-color: #e5e7eb; }
        .block-image { background-color: #fef9c3; }
        .block-math { background-color: #e0e7ff; }
        .visual-group { border: 2px dashed #94a3b8; }
        .list-item { background-color: #ede9fe; margin: 2px 0; padding: 4px 8px; border-radius: 4px; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen" x-data="vizApp()" x-init="fetchBlocks()" x-cloak>
    <div class="max-w-7xl mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">Block Splitter - Interactive</h1>
        <p class="text-gray-600 mb-8">Adjust parameters and see real-time changes</p>

        <div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <!-- Controls -->
            <div class="lg:col-span-1 bg-white rounded-lg shadow p-6 h-fit sticky top-4">
                <h2 class="text-lg font-semibold mb-4">Parameters</h2>

                <div class="mb-6">
                    <label class="block text-sm font-medium text-gray-700 mb-1">
                        Max Block Chars: <span class="font-bold" x-text="maxChars"></span>
                    </label>
                    <input type="range" min="50" max="300" step="10" x-model="maxChars"
                           @input="debouncedFetch()"
                           class="w-full h-2 bg-gray-200 rounded-lg cursor-pointer">
                    <div class="flex justify-between text-xs text-gray-500">
                        <span>50</span><span>300</span>
                    </div>
                </div>

                <div class="mb-6">
                    <label class="block text-sm font-medium text-gray-700 mb-1">
                        Soft Limit Mult: <span class="font-bold" x-text="softLimitMult.toFixed(2)"></span>x
                    </label>
                    <input type="range" min="1.0" max="1.5" step="0.05" x-model="softLimitMult"
                           @input="debouncedFetch()"
                           class="w-full h-2 bg-gray-200 rounded-lg cursor-pointer">
                    <div class="flex justify-between text-xs text-gray-500">
                        <span>1.0x</span><span>1.5x</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-1">
                        Soft max: <span x-text="Math.round(maxChars * softLimitMult)"></span> chars
                    </p>
                </div>

                <div class="mb-6">
                    <label class="block text-sm font-medium text-gray-700 mb-1">
                        Min Chunk Size: <span class="font-bold" x-text="minChunkSize"></span>
                    </label>
                    <input type="range" min="10" max="80" step="5" x-model="minChunkSize"
                           @input="debouncedFetch()"
                           class="w-full h-2 bg-gray-200 rounded-lg cursor-pointer">
                    <div class="flex justify-between text-xs text-gray-500">
                        <span>10</span><span>80</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-1">Avoids tiny orphan chunks</p>
                </div>

                <!-- Stats -->
                <div class="pt-4 border-t">
                    <h3 class="text-sm font-semibold text-gray-700 mb-3">Statistics</h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between">
                            <span class="text-gray-600">Total blocks:</span>
                            <span class="font-medium" x-text="stats.total_blocks"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Audio blocks:</span>
                            <span class="font-medium" x-text="stats.audio_blocks"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Avg size:</span>
                            <span class="font-medium" x-text="stats.avg_size + ' chars'"></span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-gray-600">Min / Max:</span>
                            <span class="font-medium" x-text="stats.min_size + ' / ' + stats.max_size"></span>
                        </div>
                    </div>
                </div>

                <!-- Filter -->
                <div class="mt-6 pt-4 border-t">
                    <label class="block text-sm font-medium text-gray-700 mb-2">Filter by type</label>
                    <select x-model="filterType" class="w-full text-sm border rounded p-2">
                        <option value="">All types</option>
                        <template x-for="type in uniqueTypes" :key="type">
                            <option :value="type" x-text="type"></option>
                        </template>
                    </select>
                </div>

                <div class="mt-4">
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" x-model="audioOnly" class="rounded">
                        <span>Audio blocks only</span>
                    </label>
                </div>

                <div class="mt-4">
                    <label class="flex items-center gap-2 text-sm">
                        <input type="checkbox" x-model="showVisualGroups" class="rounded">
                        <span>Highlight visual groups</span>
                    </label>
                </div>
            </div>

            <!-- Blocks -->
            <div class="lg:col-span-3 bg-white rounded-lg shadow p-6">
                <h2 class="text-lg font-semibold mb-4">Document Blocks</h2>

                <div x-show="loading" class="text-center py-8 text-gray-500">Loading...</div>

                <div x-show="!loading" class="space-y-2">
                    <template x-for="block in filteredBlocks" :key="block.idx">
                        <div :class="getBlockClass(block)" class="p-3 rounded-lg border">
                            <!-- Header -->
                            <div class="flex items-center gap-2 mb-2 text-xs text-gray-500">
                                <span class="font-mono bg-gray-200 px-1 rounded" x-text="\'#\' + block.idx"></span>
                                <span class="font-medium" x-text="block.type"></span>
                                <template x-if="block.type === \'heading\'">
                                    <span x-text="\'H\' + block.level"></span>
                                </template>
                                <template x-if="block.audio_block_idx !== null">
                                    <span class="bg-green-100 text-green-700 px-1 rounded"
                                          x-text="\'audio:\' + block.audio_block_idx"></span>
                                </template>
                                <template x-if="block.visual_group_id">
                                    <span class="bg-blue-100 text-blue-700 px-1 rounded"
                                          x-text="block.visual_group_id"></span>
                                </template>
                                <span class="ml-auto" x-text="(block.plain_text?.length || 0) + \' chars\'"></span>
                            </div>

                            <!-- Content -->
                            <div class="text-sm">
                                <template x-if="block.type === \'paragraph\' || block.type === \'heading\'">
                                    <p x-html="block.html || block.plain_text"></p>
                                </template>

                                <template x-if="block.type === \'list\'">
                                    <div>
                                        <template x-for="(item, i) in block.items" :key="i">
                                            <div class="list-item flex items-start gap-2">
                                                <span class="text-xs text-gray-400" x-text="block.ordered ? (i+1)+\'.\' : \'•\'"></span>
                                                <div class="flex-1">
                                                    <span x-html="item.html"></span>
                                                    <span class="text-xs text-green-600 ml-2"
                                                          x-text="\'[audio:\' + item.audio_block_idx + \', \' + item.plain_text.length + \'ch]\'"></span>
                                                </div>
                                            </div>
                                        </template>
                                    </div>
                                </template>

                                <template x-if="block.type === \'code\'">
                                    <pre class="text-xs overflow-x-auto bg-gray-800 text-green-400 p-2 rounded max-h-32"><code x-text="block.content"></code></pre>
                                </template>

                                <template x-if="block.type === \'blockquote\'">
                                    <div class="pl-4 border-l-2 border-pink-300">
                                        <template x-for="nested in block.nested_blocks" :key="nested.idx">
                                            <p class="text-gray-700 mb-1" x-html="nested.html || nested.plain_text"></p>
                                        </template>
                                    </div>
                                </template>

                                <template x-if="block.type === \'hr\'">
                                    <hr class="border-gray-400">
                                </template>
                            </div>
                        </div>
                    </template>
                </div>
            </div>
        </div>
    </div>

    <script>
        function vizApp() {
            return {
                maxChars: 150,
                softLimitMult: 1.2,
                minChunkSize: 30,
                blocks: [],
                stats: { total_blocks: 0, audio_blocks: 0 },
                loading: false,
                filterType: '',
                audioOnly: false,
                showVisualGroups: true,
                _debounceTimer: null,

                debouncedFetch() {
                    clearTimeout(this._debounceTimer);
                    this._debounceTimer = setTimeout(() => this.fetchBlocks(), 150);
                },

                async fetchBlocks() {
                    this.loading = true;
                    try {
                        const params = new URLSearchParams({
                            max_chars: this.maxChars,
                            soft_limit_mult: this.softLimitMult,
                            min_chunk_size: this.minChunkSize,
                        });
                        const res = await fetch(`/api/parse?${params}`);
                        const data = await res.json();
                        this.blocks = data.blocks || [];
                        this.stats = data.stats || {};
                    } catch (e) {
                        console.error(e);
                    }
                    this.loading = false;
                },

                get filteredBlocks() {
                    let result = this.blocks;
                    if (this.filterType) {
                        result = result.filter(b => b.type === this.filterType);
                    }
                    if (this.audioOnly) {
                        result = result.filter(b => b.audio_block_idx !== null || b.type === 'list');
                    }
                    return result;
                },

                get uniqueTypes() {
                    return [...new Set(this.blocks.map(b => b.type))];
                },

                getBlockClass(block) {
                    let cls = 'block-' + block.type;
                    if (this.showVisualGroups && block.visual_group_id) {
                        cls += ' visual-group';
                    }
                    return cls;
                }
            };
        }
    </script>
</body>
</html>
"""


def main():
    global _current_doc

    parser = argparse.ArgumentParser(description="Interactive block splitting visualization")
    parser.add_argument("file", type=Path, nargs="?", help="Markdown file to visualize")
    parser.add_argument("--port", type=int, default=8765, help="Port to run server on")
    args = parser.parse_args()

    if args.file:
        _current_doc = args.file.read_text()
        print(f"Loaded: {args.file} ({len(_current_doc)} chars)")
    else:
        # Default sample text
        _current_doc = """# Sample Document

This is a paragraph that demonstrates the block splitting functionality.

## A Section

Here's a longer paragraph that might get split if it exceeds the maximum block character limit, depending on the parameters you choose.

- First list item
- Second list item with more text
- Third item

> A blockquote with some text inside it.

Another paragraph after the quote.
"""
        print("Using default sample text. Pass a file path to load a document.")

    print(f"\nStarting server at http://localhost:{args.port}")
    print("Adjust the slider to see how blocks change with different max_chars values.\n")

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
