
-include .env

DEV_COMPOSE = docker compose -p yapit-dev --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml
SELFHOST_COMPOSE = docker compose --env-file .env.selfhost -f docker-compose.yml -f docker-compose.selfhost.yml

define create-dev-user
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_user.py
endef

check-dev-env:
	@if grep -q "^ENV_MARKER=prod" .env 2>/dev/null; then \
		echo "Error: .env has prod secrets! Run 'make dev-env' first."; exit 1; \
	fi

dev-cpu: check-dev-env down
	$(DEV_COMPOSE) --profile stripe up -d --build
	$(call create-dev-user)

dev-ci: down
	$(DEV_COMPOSE) up -d --build --wait --wait-timeout 300

down:
	$(DEV_COMPOSE) --profile stripe down -v --remove-orphans

self-host:
	$(SELFHOST_COMPOSE) up -d --build

self-host-down:
	$(SELFHOST_COMPOSE) down

dev-user:
	$(call create-dev-user)

token: dev-user
	@curl -s -X POST http://localhost:8102/api/v1/auth/password/sign-in \
	  -H "X-Stack-Access-Type: client" \
	  -H "X-Stack-Project-Id: $$(grep STACK_AUTH_PROJECT_ID .env.dev | cut -d= -f2)" \
	  -H "X-Stack-Publishable-Client-Key: $$(grep STACK_AUTH_CLIENT_KEY .env.dev | cut -d= -f2)" \
	  -H "Content-Type: application/json" \
	  -d '{"email": "dev@example.com", "password": "dev-password-123"}' | jq -r '.access_token'

test: test-unit test-frontend test-integration

test-local: test-unit test-frontend test-integration-local

test-unit:
	uv run pytest tests --ignore=tests/integration -v -m "not inworld and not gemini"

test-frontend:
	npm test --prefix frontend

test-integration:
	uv run pytest tests/integration -v

test-integration-local:
	uv run pytest tests/integration -v -m "not inworld and not gemini"

test-inworld:
	uv run pytest tests/integration -v -m "inworld"

test-gemini:
	uv run pytest tests -v -m "gemini"

# Database migrations (for prod schema changes)
# Resets DB to migration state, generates migration, auto-fixes known issues, and tests it
# Usage: make migration-new MSG="add user preferences"
# Uses yapit_test database for final verification to avoid conflicts with Stack Auth tables
migration-new:
ifndef MSG
	$(error MSG is required. Usage: make migration-new MSG="description")
endif
	@$(DEV_COMPOSE) ps postgres --format '{{.Status}}' | grep -q "Up" || (echo "Starting postgres..." && $(DEV_COMPOSE) up -d postgres --wait)
	@echo "Resetting database to migration state..."
	@$(DEV_COMPOSE) exec -T postgres psql -U yapit -d yapit -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" > /dev/null
	@cd yapit/gateway && DATABASE_URL="postgresql+psycopg://yapit:yapit@localhost:5432/yapit" uv run alembic upgrade head
	@echo "Generating migration..."
	@cd yapit/gateway && DATABASE_URL="postgresql+psycopg://yapit:yapit@localhost:5432/yapit" uv run alembic revision --autogenerate -m "$(MSG)"
	@echo "Auto-fixing sqlmodel types..."
	@find yapit/gateway/migrations/versions -name "*.py" -exec sed -i 's/sqlmodel\.sql\.sqltypes\.AutoString()/sa.String()/g' {} \;
	@echo "Testing migration on fresh DB (yapit_test)..."
	@$(DEV_COMPOSE) exec -T postgres psql -U yapit -d postgres -c "DROP DATABASE IF EXISTS yapit_test;" -c "CREATE DATABASE yapit_test;" > /dev/null
	@cd yapit/gateway && DATABASE_URL="postgresql+psycopg://yapit:yapit@localhost:5432/yapit_test" uv run alembic upgrade head
	@echo "✓ Migration generated and verified"
	@echo "Review: yapit/gateway/migrations/versions/"
	@echo "Restart dev: make dev-cpu"

# Decrypt .env.sops for dev
# Convention: DEV_* → dev only, PROD_* → prod only, _* → never, no prefix → shared
dev-env:
	@if [ -z "$$YAPIT_SOPS_AGE_KEY_FILE" ]; then \
		echo "Error: Set YAPIT_SOPS_AGE_KEY_FILE to the yapit age key path"; exit 1; \
	fi
	@SOPS_AGE_KEY_FILE=$$YAPIT_SOPS_AGE_KEY_FILE sops -d .env.sops \
		| grep -v "^#" \
		| grep -v "^_" \
		| grep -v "^PROD_" \
		| sed 's/^DEV_//' \
		> .env
	@echo "ENV_MARKER=dev" >> .env
	@echo "Created .env for dev"

# Decrypt .env.sops for prod operations (e.g., stripe_setup.py --prod)
# WARNING: Run `make dev-env` after you're done with prod operations!
prod-env:
	@if [ -z "$$YAPIT_SOPS_AGE_KEY_FILE" ]; then \
		echo "Error: Set YAPIT_SOPS_AGE_KEY_FILE to the yapit age key path"; exit 1; \
	fi
	@SOPS_AGE_KEY_FILE=$$YAPIT_SOPS_AGE_KEY_FILE sops -d .env.sops \
		| grep -v "^#" \
		| grep -v "^_" \
		| grep -v "^DEV_" \
		| sed 's/^PROD_//' \
		> .env
	@echo "ENV_MARKER=prod" >> .env
	@echo "⚠️  Created .env with PROD keys - run 'make dev-env' when done!"
	@echo "You can now run: uv run --env-file=.env python scripts/stripe_setup.py --prod"

format:
	uv run ruff check --fix .
	uv run ruff format .

check: check-backend check-frontend

check-backend:
	uvx ty@latest check yapit/gateway/

check-frontend:
	cd frontend && npm run lint && npx tsc --noEmit

# Releases
define do_release
	@LAST=$$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0"); \
	IFS='.' read -r MAJOR MINOR PATCH <<< "$${LAST#v}"; \
	case "$(1)" in \
		patch) PATCH=$$((PATCH + 1));; \
		minor) MINOR=$$((MINOR + 1)); PATCH=0;; \
		major) MAJOR=$$((MAJOR + 1)); MINOR=0; PATCH=0;; \
	esac; \
	NEW="v$$MAJOR.$$MINOR.$$PATCH"; \
	echo "$$LAST → $$NEW"; \
	sed -i "s/^## Unreleased/## $$NEW — $$(date +%Y-%m-%d)/" CHANGELOG.md; \
	git add CHANGELOG.md; \
	git commit -m "Release $$NEW"; \
	git tag "$$NEW"; \
	echo "Tagged $$NEW. Run 'make gh-release' to push and publish."
endef

release-patch:
	$(call do_release,patch)

release-minor:
	$(call do_release,minor)

release-major:
	$(call do_release,major)

gh-release:
	@git push && git push --tags
	@TAG=$$(git describe --tags --abbrev=0); \
	BODY=$$(sed -n "/^## $$TAG/,/^## v/{/^## v/!p;}" CHANGELOG.md | sed '1d'); \
	gh release create "$$TAG" --title "$$TAG" --notes "$$BODY"

# Prod operations
deploy:
	./scripts/deploy.sh

PROD_GATEWAY = $$(docker ps -qf name=yapit_gateway)

warm-cache:
	@echo "Starting warm-cache in tmux session on prod..."
	@ssh $(VPS_HOST) 'tmux kill-session -t warm-cache 2>/dev/null; tmux new-session -d -s warm-cache "docker exec $(PROD_GATEWAY) python -m yapit.gateway.warm_cache 2>&1 | tee /tmp/warm-cache.log; echo DONE; sleep 86400"'
	@echo "Attaching to tmux session..."
	@ssh -t $(VPS_HOST) 'tmux attach -t warm-cache'

# Metrics

# Sync metrics from prod TimescaleDB to local DuckDB
sync-metrics:
	@mkdir -p data
	@echo "Exporting metrics from prod..."
	@ssh $(VPS_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_event ORDER BY timestamp) TO STDOUT WITH CSV HEADER"' \
		> data/metrics_raw.csv
	@echo "Exporting hourly aggregates..."
	@ssh $(VPS_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_hourly ORDER BY bucket DESC) TO STDOUT WITH CSV HEADER"' \
		> data/metrics_hourly.csv
	@echo "Exporting daily aggregates..."
	@ssh $(VPS_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_daily ORDER BY bucket DESC) TO STDOUT WITH CSV HEADER"' \
		> data/metrics_daily.csv
	@echo "Converting to DuckDB..."
	@uv run --with duckdb python scripts/csv_to_duckdb.py
	@rm -f data/metrics_raw.csv data/metrics_hourly.csv data/metrics_daily.csv
	@echo "✓ Metrics synced to data/metrics.duckdb"

# Sync logs from prod (from Docker volume)
sync-logs:
	@echo "Syncing logs from prod..."
	@mkdir -p data/logs
	@rsync -avz --progress $(VPS_HOST):/var/lib/docker/volumes/yapit_gateway-data/_data/logs/*.jsonl* data/logs/
	@echo "Decompressing logs..."
	@gunzip -f data/logs/*.jsonl.gz 2>/dev/null || true
	@echo "✓ Logs synced to data/logs/"

# Sync all data (metrics + logs)
sync-data: sync-metrics sync-logs

# Run health analysis (syncs data, runs Claude, sends to Discord)
report:
	@./scripts/report.sh

report-post-deploy:
	@./scripts/report.sh --after-deploy

# Run local dashboard (syncs first)
dashboard: sync-metrics
	@echo "Starting dashboard..."
	@(sleep 2 && xdg-open http://localhost:8502 2>/dev/null || open http://localhost:8502 2>/dev/null || true) &
	@PYTHONPATH=. uv run --with streamlit,pandas,plotly,duckdb,numpy streamlit run dashboard/__init__.py --server.port 8502 --server.headless true

# Dashboard without sync (use existing local data)
dashboard-local:
	@echo "Starting dashboard with local data..."
	@(sleep 2 && xdg-open http://localhost:8502 2>/dev/null || open http://localhost:8502 2>/dev/null || true) &
	@PYTHONPATH=. uv run --with streamlit,pandas,plotly,duckdb,numpy streamlit run dashboard/__init__.py --server.port 8502 --server.headless true

