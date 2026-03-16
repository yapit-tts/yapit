<div align="center">

<img src="frontend/public/favicon.svg" width="80" height="80">

**yapit**: Listen to anything. Open-source TTS for documents, web pages, and text.

<h3>

[Website](https://yapit.md) | [CLI](https://github.com/yapit-tts/yapit-cli) | [Self-Host](#self-hosting) | [Architecture](docs/architecture.md)

</h3>

[![GitHub Repo stars](https://img.shields.io/github/stars/yapit-tts/yapit)](https://github.com/yapit-tts/yapit/stargazers)
[![CI/CD](https://github.com/yapit-tts/yapit/actions/workflows/deploy.yml/badge.svg)](https://github.com/yapit-tts/yapit/actions/workflows/deploy.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

</div>

<img width="3840" height="2880" alt="image" src="https://github.com/user-attachments/assets/706fcf0d-896b-4bae-b826-0d1e49262383" />

---

Paste a URL or upload a PDF. Yapit renders the document and reads it aloud.

- Handles the documents other TTS tools can't: academic papers with math, citations, figures, tables, messy formatting. Equations get spoken descriptions, citations become prose, page noise is skipped. The original content displays faithfully.
- 170+ voices across 15 languages. Premium voices or free local synthesis that runs entirely in your browser, no account needed.
- Vim-style keyboard shortcuts, document outliner, media key support, adjustable speed, dark mode, share by link.
- Markdown export: append `/md` to any document URL to get clean markdown via curl. `/md-annotated` includes TTS annotations.

Powered by [Gemini](https://ai.google.dev/gemini-api), [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), [Inworld TTS](https://inworld.ai), [DocLayout-YOLO](https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench), [defuddle](https://github.com/kepano/defuddle).

## Self-hosting

```bash
git clone https://github.com/yapit-tts/yapit.git && cd yapit
cp .env.selfhost.example .env.selfhost
make self-host
```

Open [http://localhost](http://localhost) and create an account. Data persists across restarts.

`.env.selfhost` is self-documenting — see the comments for optional features (Gemini extraction, Inworld voices, RunPod overflow).

**Multi-worker GPU setup:** 

Workers are pull-based — any machine with Redis access can run them. Connect from the local network or via Tailscale, for example. GPU and CPU workers run side-by-side; faster workers naturally pull more jobs. Scale by running more containers on any machine that can reach Redis.

Prereq: Docker 25+, [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) with [CDI enabled](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html), network access to the Redis instance.

```bash
# One-time GPU setup: generate CDI spec + enable CDI in Docker
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
# Add {"features": {"cdi": true}} to /etc/docker/daemon.json, then:
sudo systemctl restart docker

git clone --depth 1 https://github.com/yapit-tts/yapit.git && cd yapit

# Pull only the images you need
docker compose -f docker-compose.worker.yml pull kokoro-gpu yolo-gpu

# Start 2 Kokoro + 1 YOLO worker
REDIS_URL=redis://<host>:6379/0 docker compose -f docker-compose.worker.yml up -d \
  --scale kokoro-gpu=2 --scale yolo-gpu=1 kokoro-gpu yolo-gpu
```

Adjust `--scale` to your GPU. A 4GB card fits 2 Kokoro + 1 YOLO comfortably.

<details>
<summary>NVIDIA MPS (recommended for multiple workers per GPU)</summary>

[MPS](https://docs.nvidia.com/deploy/mps/) lets multiple workers share one GPU context — less VRAM overhead, no context switching. Without MPS, each worker gets its own CUDA context (~300MB each). The compose file mounts the MPS pipe automatically; just start the daemon.

```bash
sudo tee /etc/systemd/system/nvidia-mps.service > /dev/null <<'EOF'
[Unit]
Description=NVIDIA Multi-Process Service (MPS)
After=nvidia-persistenced.service

[Service]
Type=forking
ExecStart=/usr/bin/nvidia-cuda-mps-control -d
ExecStop=/bin/sh -c 'echo quit | /usr/bin/nvidia-cuda-mps-control'
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now nvidia-mps
```

</details>

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
- Support thinking parameter for Gemini
- Support temperature parameter for Inworld


## Development

```bash
uv sync                              # install Python dependencies
npm install --prefix frontend        # install frontend dependencies
make dev-env 2>/dev/null || touch .env  # decrypt secrets, or create empty .env
make dev-cpu                         # start backend services (Docker Compose)
cd frontend && npm run dev           # start frontend
make test-local                      # run tests
```

See [agent/knowledge/dev-setup.md](agent/knowledge/dev-setup.md) for full setup instructions.

The `agent/knowledge/` directory is the project's in-depth knowledge base, maintained jointly with Claude during development.

