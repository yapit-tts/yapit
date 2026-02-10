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

Paste a URL or upload a PDF. Yapit renders the document faithfully and reads it aloud with natural voices. Math, figures, tables, and citations display correctly while the audio adapts for a natural listening experience: citations become prose, equations get spoken descriptions, page noise is skipped. Choose between server-side premium voices or free synthesis that runs entirely in your browser.

---

## Features

Core features:

- **[Gemini 3 Flash](https://ai.google.dev/gemini-api) extraction**: Each page is processed as an image with figure context from [DocLayout-YOLO](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench). Page noise (page numbers, headers, watermarks) is filtered. Results are cached per-page, so re-processing a large document only touches changed pages.

- **Display and speech routing**: Custom tags (`<yap-show>`, `<yap-speak>`, `<yap-cap>`) route content between visual display and audio. Math renders but stays silent unless Gemini adds a spoken description. Figures display with cropped images; captions are spoken. In-text citations are naturalized for listening.

- **Free browser-local TTS**: [Kokoro](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX) runs in a Web Worker via WASM/WebGPU. No server round-trip, no cost, fully private.

Additional:

- Multiple input paths: URLs, PDFs, images, file uploads, raw text
- [Inworld TTS 1.5](https://inworld.ai) premium voices for server-side synthesis
- arXiv papers via [Markxiv](https://github.com/tonydavis629/markxiv) (LaTeX source to markdown, better handling of formulas without needing Gemini)
- Document sharing by link
- Keyboard and media controls (hjkl, space, volume; OS media session with lock screen and headphone support)
- Document outliner for navigating large documents
- ...and much more!

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

## Development

```bash
make dev-cpu    # start backend services (Docker Compose)
cd frontend && npm run dev  # start frontend
make test-local # run tests
```

See [agent/knowledge/dev-setup.md](agent/knowledge/dev-setup.md) for full setup instructions.

The `agent/knowledge/` directory is the project's in-depth knowledge base, maintained jointly with Claude during development.
