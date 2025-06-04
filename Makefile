
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
	@bash -c "set -a && source .env.dev && set +a && uv run python scripts/create_dev_user.py"

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

access-token:
	@bash -c "set -a && source .env.dev && set +a && uv run python scripts/create_dev_user.py --print-token 2>/dev/null"

test: test-unit test-integration

test-unit:
	uv run pytest tests --ignore=tests/integration

test-integration: dev-cpu
	@echo "Getting access token..."
	@TOKEN=$(cd $(shell pwd) && bash -c "set -a && source .env.dev && set +a && uv run python scripts/create_dev_user.py --print-token 2>&1 | grep -E '^[a-zA-Z0-9_.-]+$' | tail -n 1") && \
	if [ -z "$TOKEN" ]; then \
		echo "Failed to get access token" >&2; \
		exit 1; \
	fi && \
	echo "Token obtained (length: ${#TOKEN}), running tests..." && \
	export TEST_AUTH_TOKEN="$TOKEN" && \
	uv run pytest tests/integration -v

lint:
	uv run ruff check .

format:
	uv run ruff format .

repomix:
	repomix -i "frontend/src/components/ui,.gitignore,**/*.data,**/*sql"

repomix-backend:
	repomix -i "frontend,.gitignore,**/*.data,**/*sql"
