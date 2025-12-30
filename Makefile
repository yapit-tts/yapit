
define create-dev-user
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_user.py
endef

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
	$(call create-dev-user)

dev-gpu: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-gpu.yml \
	up -d --build

dev-mac: down
	docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml -f docker-compose.mac.yml \
	up -d --build --wait
	$(call create-dev-user)

down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v --remove-orphans

dev-user:
	$(call create-dev-user)

token: dev-user
	@curl -s -X POST http://localhost:8102/api/v1/auth/password/sign-in \
	  -H "X-Stack-Access-Type: client" \
	  -H "X-Stack-Project-Id: $$(grep STACK_AUTH_PROJECT_ID .env.dev | cut -d= -f2)" \
	  -H "X-Stack-Publishable-Client-Key: $$(grep STACK_AUTH_CLIENT_KEY .env.dev | cut -d= -f2)" \
	  -H "Content-Type: application/json" \
	  -d '{"email": "dev@example.com", "password": "dev-password-123"}' | jq -r '.access_token'

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

test-local: test-unit test-integration-local

test-unit:
	uv run --env-file=.env.dev pytest tests --ignore=tests/integration -v -m "not mistral and not runpod and not inworld"

test-integration:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v

test-integration-local:
	uv run --env-file=.env.dev pytest tests/integration -v -m "not runpod and not mistral and not inworld"

test-runpod:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v -m "runpod"

test-mistral:
	uv run --env-file=.env.dev --env-file=.env pytest tests -v -m "mistral"

test-inworld:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v -m "inworld"

# Database migrations (for prod schema changes)
# Resets DB to migration state, then generates migration from model diff
# Requires postgres to be running. Restart dev afterward to recreate tables.
# Usage: make migration-new MSG="add user preferences"
migration-new:
ifndef MSG
	$(error MSG is required. Usage: make migration-new MSG="description")
endif
	@docker compose -f docker-compose.yml -f docker-compose.dev.yml ps postgres --format '{{.Status}}' | grep -q "Up" || \
		(echo "Error: postgres not running. Start with: make dev-cpu" && exit 1)
	@echo "Resetting database to migration state..."
	@docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U yapit -d yapit -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" > /dev/null
	@cd yapit/gateway && DATABASE_URL="postgresql://yapit:yapit@localhost:5432/yapit" uv run alembic upgrade head
	@echo "Generating migration..."
	@cd yapit/gateway && DATABASE_URL="postgresql://yapit:yapit@localhost:5432/yapit" uv run alembic revision --autogenerate -m "$(MSG)"
	@echo "Done. Review migration in yapit/gateway/migrations/versions/"
	@echo "Restart dev to recreate tables: make dev-cpu"

# Decrypt .env.sops for dev (removes prod Stack Auth credentials)
# Prefers YAPIT_SOPS_AGE_KEY_FILE over SOPS_AGE_KEY_FILE (yapit key may differ from global)
env-dev:
	@if [ -z "$$YAPIT_SOPS_AGE_KEY_FILE" ]; then \
		echo "Error: Set YAPIT_SOPS_AGE_KEY_FILE to the yapit age key path"; exit 1; \
	fi
	@SOPS_AGE_KEY_FILE=$$YAPIT_SOPS_AGE_KEY_FILE sops -d .env.sops | grep -v "^STACK_" > .env
	@echo "Created .env (prod Stack Auth credentials removed)"

check: check-backend check-frontend

check-backend:
	ty check yapit/gateway/

check-frontend:
	cd frontend && npm run lint && npx tsc --noEmit

lint:
	uv run ruff check .

format:
	uv run ruff format .

repomix:
	repomix -i "frontend/src/components/ui,.gitignore,**/*.data,**/*sql"

repomix-backend:
	repomix -i "frontend,.gitignore,**/*.data,**/*sql"

# RunPod deployment
HIGGS_TAG := $(shell date +%Y%m%d-%H%M%S)
HIGGS_IMAGE := maxw01/higgs-worker:$(HIGGS_TAG)

deploy-higgs: deploy-higgs-build deploy-higgs-push deploy-higgs-runpod

deploy-higgs-build:
	docker build -t $(HIGGS_IMAGE) -f yapit/workers/higgs_audio_v2_native/Dockerfile .

deploy-higgs-push:
	docker push $(HIGGS_IMAGE)

deploy-higgs-runpod:
	uv run --env-file=.env python infra/runpod/deploy.py higgs-native --image-tag $(HIGGS_TAG)
