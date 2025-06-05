
build: build-cpu

build-cpu:
	docker compose --env-file .env.dev build gateway kokoro-cpu stack-auth --parallel

build-gpu:
	docker compose --env-file .env.dev build kokoro-gpu --parallel

prod-build:
	docker compose --env-file .env.prod build --parallel

dev-cpu: down
	docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-cpu gateway redis postgres stack-auth --build --wait
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_dev_user.py

dev-gpu: down
	docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-gpu gateway redis postgres stack-auth --build

dev-mac: down
	docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.mac.yml \
	--profile self-host \
	up -d gateway redis postgres --build

down:
	docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml --profile self-host down -v --remove-orphans

prod-up:
	docker compose --env-file .env.prod up -d gateway redis postgres stack-auth # remote workers

prod-down:
	docker compose --env-file .env.prod down -v --remove-orphans

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

