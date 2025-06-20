
build: build-cpu

build-cpu:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml build --parallel

build-gpu:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-gpu.yml build --parallel

prod-build:
	docker compose build --parallel

dev-cpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml \
	up -d --build --wait
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_dev_user.py

dev-gpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-gpu.yml \
	up -d --build

dev-mac: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mac.yml \
	up -d --build

down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v --remove-orphans

# Production targets
prod-up:
	docker compose up -d

prod-up-cpu:
	docker compose -f docker-compose.yml -f docker-compose.kokoro-cpu.yml up -d

prod-up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.kokoro-gpu.yml up -d

prod-down:
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

test: test-unit test-integration

test-unit:
	uv run --env-file=.env.dev pytest tests --ignore=tests/integration

test-integration:
	uv run --env-file=.env.dev pytest tests/integration -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

repomix:
	repomix -i "frontend/src/components/ui,.gitignore,**/*.data,**/*sql"

repomix-backend:
	repomix -i "frontend,.gitignore,**/*.data,**/*sql"

