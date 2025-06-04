
build:
	docker compose build --parallel

build-cpu:
	docker compose build gateway kokoro-cpu stack-auth --parallel

build-gpu:
	docker compose build kokoro-gpu --parallel

dev-cpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-cpu gateway redis postgres stack-auth --build --wait
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_dev_user.py

dev-gpu: down
	docker compose  -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-gpu gateway redis postgres stack-auth --build

dev-mac: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mac.yml \
	--profile self-host \
	up -d gateway redis postgres --build

up:
	docker compose up -d gateway redis postgres stack-auth # remote workers

down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile self-host down -v --remove-orphans || \
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

test: test-unit test-integration

test-unit:
	uv run --env-file=.env.dev pytest tests --ignore=tests/integration

test-integration: dev-cpu
	uv run --env-file=.env.dev pytest tests/integration -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

repomix:
	repomix -i "frontend/src/components/ui,.gitignore,**/*.data,**/*sql"

repomix-backend:
	repomix -i "frontend,.gitignore,**/*.data,**/*sql"
