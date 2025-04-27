
# -------- build ------

build:
	docker compose build --parallel

build-cpu:
	docker compose build gateway kokoro-cpu --parallel

build-gpu:
	docker compose build kokoro-gpu --parallel

# -------- runtime ------

dev-cpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-cpu gateway redis postgres --build

dev-gpu: down
	docker compose  -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-gpu gateway redis postgres --build

up:
	docker compose up -d gateway redis postgres # remote workers

down:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

logs-gpu:
	docker compose logs -f kokoro-gpu

# -------- test ------

test-ws-curl:
	curl -X POST localhost:8000/v1/models/kokoro/tts \
		 -H 'Content-Type: application/json' \
		 -d '{"text":"Hello world!"}'

test-cpu-wav: dev-cpu
	python scripts/smoke_test.py --model kokoro-cpu

test-gpu-wav: dev-gpu
	python scripts/smoke_test.py --model kokoro-gpu

# -------- repomix -------

repomix:
	repomix -i ".gitignore"

repomix-backend:
	repomix -i "frontend,.gitignore"
