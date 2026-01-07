
define create-dev-user
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_user.py
endef

dev-cpu: down
	rm -f metrics/metrics.db
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml \
	--profile stripe up -d --build
	$(call create-dev-user)

dev-gpu: down
	rm -f metrics/metrics.db
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-gpu.yml \
	--profile stripe up -d --build

dev-mac: down
	rm -f metrics/metrics.db
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml -f docker-compose.mac.yml \
	--profile stripe up -d --build
	$(call create-dev-user)

dev-ci: down
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.kokoro-cpu.yml \
	up -d --build --wait --wait-timeout 300

down:
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml down -v --remove-orphans

dev-user:
	$(call create-dev-user)

token: dev-user
	@curl -s -X POST http://localhost:8102/api/v1/auth/password/sign-in \
	  -H "X-Stack-Access-Type: client" \
	  -H "X-Stack-Project-Id: $$(grep STACK_AUTH_PROJECT_ID .env.dev | cut -d= -f2)" \
	  -H "X-Stack-Publishable-Client-Key: $$(grep STACK_AUTH_CLIENT_KEY .env.dev | cut -d= -f2)" \
	  -H "Content-Type: application/json" \
	  -d '{"email": "dev@example.com", "password": "dev-password-123"}' | jq -r '.access_token'

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
# Resets DB to migration state, generates migration, auto-fixes known issues, and tests it
# Usage: make migration-new MSG="add user preferences"
# Uses yapit_test database for final verification to avoid conflicts with Stack Auth tables
migration-new:
ifndef MSG
	$(error MSG is required. Usage: make migration-new MSG="description")
endif
	@docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml ps postgres --format '{{.Status}}' | grep -q "Up" || \
		(echo "Starting postgres..." && docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d postgres --wait)
	@echo "Resetting database to migration state..."
	@docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U yapit -d yapit -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" > /dev/null
	@cd yapit/gateway && DATABASE_URL="postgresql://yapit:yapit@localhost:5432/yapit" uv run alembic upgrade head
	@echo "Generating migration..."
	@cd yapit/gateway && DATABASE_URL="postgresql://yapit:yapit@localhost:5432/yapit" uv run alembic revision --autogenerate -m "$(MSG)"
	@echo "Auto-fixing sqlmodel types..."
	@find yapit/gateway/migrations/versions -name "*.py" -exec sed -i 's/sqlmodel\.sql\.sqltypes\.AutoString()/sa.String()/g' {} \;
	@echo "Testing migration on fresh DB (yapit_test)..."
	@docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U yapit -d postgres -c "DROP DATABASE IF EXISTS yapit_test;" -c "CREATE DATABASE yapit_test;" > /dev/null
	@cd yapit/gateway && DATABASE_URL="postgresql://yapit:yapit@localhost:5432/yapit_test" uv run alembic upgrade head
	@echo "✓ Migration generated and verified"
	@echo "Review: yapit/gateway/migrations/versions/"
	@echo "Restart dev: make dev-cpu"

# Decrypt .env.sops for dev
# - Removes comments and _PREFIXED vars (safekeeping, not active)
# - Removes STACK_* (dev uses separate Stack Auth via .env.dev)
# - Removes DATABASE_URL and POSTGRES_PASSWORD (dev uses public creds from .env.dev)
# - Transforms *_TEST vars to main var names (STRIPE_SECRET_KEY_TEST -> STRIPE_SECRET_KEY)
# - Removes *_LIVE vars (not needed in dev)
dev-env:
	@if [ -z "$$YAPIT_SOPS_AGE_KEY_FILE" ]; then \
		echo "Error: Set YAPIT_SOPS_AGE_KEY_FILE to the yapit age key path"; exit 1; \
	fi
	@SOPS_AGE_KEY_FILE=$$YAPIT_SOPS_AGE_KEY_FILE sops -d .env.sops \
		| grep -v "^#" \
		| grep -v "^_" \
		| grep -v "^STACK_" \
		| grep -v "^DATABASE_URL=" \
		| grep -v "^POSTGRES_PASSWORD=" \
		| grep -v "_LIVE=" \
		| sed 's/_TEST=/=/' \
		> .env
	@echo "Created .env (dev-ready: test keys, no prod Stack Auth)"

# Decrypt .env.sops for prod operations (e.g., stripe_setup.py --prod)
# - Transforms *_LIVE vars to main var names (STRIPE_SECRET_KEY_LIVE -> STRIPE_SECRET_KEY)
# - Removes *_TEST vars
# - Keeps STACK_* (prod Stack Auth)
# WARNING: Run `make dev-env` after you're done with prod operations!
prod-env:
	@if [ -z "$$YAPIT_SOPS_AGE_KEY_FILE" ]; then \
		echo "Error: Set YAPIT_SOPS_AGE_KEY_FILE to the yapit age key path"; exit 1; \
	fi
	@SOPS_AGE_KEY_FILE=$$YAPIT_SOPS_AGE_KEY_FILE sops -d .env.sops \
		| grep -v "_TEST=" \
		| sed 's/_LIVE=/=/' \
		> .env
	@echo "⚠️  Created .env with PROD keys - run 'make dev-env' when done!"
	@echo "You can now run: uv run --env-file=.env python scripts/stripe_setup.py --prod"

check: check-backend check-frontend

check-backend:
	uvx ty@latest check yapit/gateway/

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

# Metrics dashboard (runs on prod via SSH tunnel)
# One-time setup: ssh $(PROD_HOST) 'mkdir -p /opt/yapit-dashboard && (command -v ~/.local/bin/uv || curl -LsSf https://astral.sh/uv/install.sh | sh)'
PROD_HOST := root@46.224.195.97

dashboard:
	@echo "Syncing dashboard.py to prod..."
	@scp scripts/dashboard.py $(PROD_HOST):/opt/yapit-dashboard/
	@echo "Starting dashboard on prod (Ctrl+C to stop)..."
	@(sleep 3 && xdg-open http://localhost:8502 2>/dev/null || open http://localhost:8502 2>/dev/null || true) &
	@ssh -t -L 8502:localhost:8502 $(PROD_HOST) '\
		METRICS_DB=$$(docker inspect $$(docker ps -qf name=gateway) --format '\''{{range .Mounts}}{{if eq .Destination "/data/metrics"}}{{.Source}}{{end}}{{end}}'\'')/metrics.db \
		~/.local/bin/uv run --with streamlit,pandas,plotly streamlit run /opt/yapit-dashboard/dashboard.py --server.port 8502 --server.headless true'

