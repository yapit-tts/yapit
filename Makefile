# ───────── variables ──────────────────────────────────────────
COMPOSE = docker compose
PWD     := $(shell pwd)

# ───────── targets ────────────────────────────────────────────
.PHONY: help
help:
	@echo "make build           – build all images"
	@echo "make build-cpu       – build only cpu images"
	@echo "make build-gpu       – build only gpu images"
	@echo "make up              – up everything"
	@echo "make up-cpu          – up w/o gpu services"
	@echo "make down            – stop & remove containers"
	@echo "make logs            – live logs (all)"
	@echo "make logs-gpu        – gpu worker log"
	@echo "make test-cpu        - generate sample wav with cpu worker"
	@echo "make test-gpu        - generate sample wav with gpu worker"

# -------- build -----------
build:
	$(COMPOSE) build --parallel

build-cpu:
	$(COMPOSE) build gateway kokoro-cpu-worker

build-gpu:
	$(COMPOSE) build kokoro-gpu-worker

# -------- runtime ---------
up:
	$(COMPOSE) up -d

up-cpu:
	$(COMPOSE) up -d redis postgres minio gateway kokoro-cpu-worker

down:
	$(COMPOSE) down -v --remove-orphans

logs:
	$(COMPOSE) logs -f

logs-gpu:
	$(COMPOSE) logs -f kokoro-gpu-worker

# -------- smoke test ------

test-cpu: up-cpu
	curl -X POST localhost:8000/v1/tts \
     -H 'Content-Type: application/json' \
     -d '{"model":"kokoro-cpu","text":"CPU"}'

test-gpu: up
	curl -X POST localhost:8000/v1/tts \
	 -H 'Content-Type: application/json' \
	 -d '{"model":"kokoro","text":" GPU"}'

test-cpu-wav: up-cpu
	python scripts/smoke_test.py --model kokoro-cpu

test-gpu-wav: up
	python scripts/smoke_test.py --model kokoro-gpu
