<div align="center">

<img src="frontend/public/favicon.svg" width="80" height="80">

**yapit**: Listen to anything. Open-source TTS for documents, web pages, and text.

<h3>

[Website](https://yapit.md) | [Self-Host](#self-hosting) | [Architecture](docs/architecture.md)

</h3>

[![GitHub Repo stars](https://img.shields.io/github/stars/yapit-tts/yapit)](https://github.com/yapit-tts/yapit/stargazers)
[![CI/CD](https://github.com/yapit-tts/yapit/actions/workflows/deploy.yml/badge.svg)](https://github.com/yapit-tts/yapit/actions/workflows/deploy.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

</div>

---

Paste a URL or upload a PDF. Yapit renders the document and reads it aloud.

- Handles the documents other TTS tools can't: academic papers with math, citations, figures, tables, messy formatting. Equations get spoken descriptions, citations become prose, page noise is skipped. The original content displays faithfully.
- 170+ voices across 15 languages. Premium voices or free local synthesis that runs entirely in your browser, no account needed.
- Vim-style keyboard shortcuts, document outliner, media key support, adjustable speed, dark mode, share by link.

Powered by [Gemini](https://ai.google.dev/gemini-api), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [Inworld TTS](https://inworld.ai), [DocLayout-YOLO](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench), [Markxiv](https://github.com/tonydavis629/markxiv).

## Self-hosting

```bash
git clone https://github.com/yapit-tts/yapit.git && cd yapit
cp .env.selfhost.example .env.selfhost
make self-host
```

Open [http://localhost](http://localhost) and create an account. Data persists across restarts.

`.env.selfhost` is self-documenting — see the comments for optional features (Gemini extraction, Inworld voices, RunPod overflow).

**Scaling workers:** Workers are pull-based — any machine with Redis access can run them, no gateway config needed. Connect from the local network or via Tailscale, for example.

```bash
# Kokoro TTS (GPU)
docker run --gpus all -e REDIS_URL=redis://<host>:6379 ghcr.io/yapit-tts/kokoro-gpu:latest
# Kokoro TTS (CPU)
docker run -e REDIS_URL=redis://<host>:6379 ghcr.io/yapit-tts/kokoro-cpu:latest
# YOLO figure detection (GPU)
docker run --gpus all -e REDIS_URL=redis://<host>:6379 ghcr.io/yapit-tts/yolo-gpu:latest
# YOLO figure detection (CPU)
docker run -e REDIS_URL=redis://<host>:6379 ghcr.io/yapit-tts/yolo-cpu:latest
```

GPU and CPU workers run side-by-side; faster workers naturally pull more jobs. Scale by running more containers on any machine that can reach Redis.

To stop: `make self-host-down`.


## Roadmap

Now:
- Launch

Next:
- Support uploading images, EPUB.
- Support AI-transform for websites.
- Support exporting audio as MP3.

Later:
- Better support for self-hosting (better modularity for adding voices, extraction methods, documentation)


## Development

```bash
make dev-cpu    # start backend services (Docker Compose)
cd frontend && npm run dev  # start frontend
make test-local # run tests
```

See [agent/knowledge/dev-setup.md](agent/knowledge/dev-setup.md) for full setup instructions.

The `agent/knowledge/` directory is the project's in-depth knowledge base, maintained jointly with Claude during development.

