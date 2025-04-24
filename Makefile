
# -------- build ------
build:
	docker compose build --parallel

build-cpu:
	docker compose build gateway kokoro-cpu --parallel

build-gpu:
	docker compose build kokoro-gpu --parallel

# -------- runtime ------

up-dev-cpu:
	docker compose --profile local-tts up -d kokoro-cpu gateway redis postgres

up-dev-gpu:
	docker compose --profile local-tts up -d kokoro-gpu gateway redis postgres

up:
	docker compose up -d gateway redis postgres # remote workers

down:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

logs-gpu:
	docker compose logs -f kokoro-gpu-worker

# -------- test ------

test-cpu: up-dev-cpu
	curl -X POST localhost:8000/v1/tts \
     -H 'Content-Type: application/json' \
     -d '{"model":"kokoro-cpu","text":"CPU"}'

test-gpu: up-dev-gpu
	curl -X POST localhost:8000/v1/tts \
	 -H 'Content-Type: application/json' \
	 -d '{"model":"kokoro","text":" GPU"}'

test-cpu-wav: up-dev-cpu
	python scripts/smoke_test.py --model kokoro-cpu

test-gpu-wav: up-dev-gpu
	python scripts/smoke_test.py --model kokoro-gpu

# -------- repomix -------

repomix:
	repomix -i ".gitignore"

repomix-backend:
	repomix -i "frontend,.gitignore"
