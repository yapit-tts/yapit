
# -------- build ------

build:
	docker compose build --parallel

build-cpu:
	docker compose build gateway kokoro-cpu stack-auth --parallel

build-gpu:
	docker compose build kokoro-gpu --parallel

# -------- runtime ------

dev-cpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml \
	--profile self-host \
	up -d kokoro-cpu gateway redis postgres stack-auth --build

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
	docker compose down -v --remove-orphans

logs:
	docker compose logs -f

# -------- repomix -------

repomix:
	repomix -i "frontend/src/components/ui,.gitignore,**/*.data,**/*sql"

repomix-backend:
	repomix -i "frontend,.gitignore,**/*.data,**/*sql"

access-token:
	uv run --env-file=.env -m scripts.access_token

# -------- development -------

.PHONY: test
test:
	uv run pytest

.PHONY: lint
lint:
	uv run ruff check .

.PHONY: format
format:
	uv run ruff format .
