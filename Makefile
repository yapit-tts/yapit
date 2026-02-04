
define create-dev-user
	@echo "Creating dev user..."
	uv run --env-file=.env.dev python scripts/create_user.py
endef

check-dev-env:
	@if grep -q "^ENV_MARKER=prod" .env 2>/dev/null; then \
		echo "Error: .env has prod secrets! Run 'make dev-env' first."; exit 1; \
	fi

dev-cpu: check-dev-env down
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml \
		--profile stripe up -d --build
	$(call create-dev-user)

dev-ci: down
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml \
		up -d --build --wait --wait-timeout 300

down:
	docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml --profile stripe down -v --remove-orphans

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
	uv run --env-file=.env.dev pytest tests --ignore=tests/integration -v -m "not runpod and not inworld and not gemini"

test-integration:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v

test-integration-local:
	uv run --env-file=.env.dev pytest tests/integration -v -m "not runpod and not inworld and not gemini"

test-runpod:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v -m "runpod"

test-inworld:
	uv run --env-file=.env.dev --env-file=.env pytest tests/integration -v -m "inworld"

test-gemini:
	uv run --env-file=.env.dev --env-file=.env pytest tests -v -m "gemini"

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
	@cd yapit/gateway && DATABASE_URL="postgresql+psycopg://yapit:yapit@localhost:5432/yapit" uv run alembic upgrade head
	@echo "Generating migration..."
	@cd yapit/gateway && DATABASE_URL="postgresql+psycopg://yapit:yapit@localhost:5432/yapit" uv run alembic revision --autogenerate -m "$(MSG)"
	@echo "Auto-fixing sqlmodel types..."
	@find yapit/gateway/migrations/versions -name "*.py" -exec sed -i 's/sqlmodel\.sql\.sqltypes\.AutoString()/sa.String()/g' {} \;
	@echo "Testing migration on fresh DB (yapit_test)..."
	@docker compose --env-file .env --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U yapit -d postgres -c "DROP DATABASE IF EXISTS yapit_test;" -c "CREATE DATABASE yapit_test;" > /dev/null
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

check: check-backend check-frontend

check-backend:
	uvx ty@latest check yapit/gateway/

check-frontend:
	cd frontend && npm run lint && npx tsc --noEmit

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

# Metrics
PROD_HOST := root@46.224.195.97

# Sync metrics from prod TimescaleDB to local DuckDB
sync-metrics:
	@mkdir -p gateway-data
	@echo "Exporting metrics from prod..."
	@ssh $(PROD_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_event ORDER BY timestamp DESC LIMIT 100000) TO STDOUT WITH CSV HEADER"' \
		> gateway-data/metrics_raw.csv
	@echo "Exporting hourly aggregates..."
	@ssh $(PROD_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_hourly ORDER BY bucket DESC) TO STDOUT WITH CSV HEADER"' \
		> gateway-data/metrics_hourly.csv
	@echo "Exporting daily aggregates..."
	@ssh $(PROD_HOST) 'docker exec $$(docker ps -qf name=metrics-db) \
		psql -U metrics -d metrics -c "COPY (SELECT * FROM metrics_daily ORDER BY bucket DESC) TO STDOUT WITH CSV HEADER"' \
		> gateway-data/metrics_daily.csv
	@echo "Converting to DuckDB..."
	@uv run --with duckdb python -c "\
import duckdb; \
conn = duckdb.connect('gateway-data/metrics.duckdb'); \
conn.execute('DROP TABLE IF EXISTS metrics_event'); \
conn.execute('DROP TABLE IF EXISTS metrics_hourly'); \
conn.execute('DROP TABLE IF EXISTS metrics_daily'); \
conn.execute(\"CREATE TABLE metrics_event AS SELECT * FROM read_csv('gateway-data/metrics_raw.csv', auto_detect=true)\"); \
conn.execute(\"CREATE TABLE metrics_hourly AS SELECT * FROM read_csv('gateway-data/metrics_hourly.csv', auto_detect=true)\"); \
conn.execute(\"CREATE TABLE metrics_daily AS SELECT * FROM read_csv('gateway-data/metrics_daily.csv', auto_detect=true)\"); \
print(f'Synced: {conn.execute(\"SELECT COUNT(*) FROM metrics_event\").fetchone()[0]} raw events'); \
conn.close()"
	@rm -f gateway-data/metrics_raw.csv gateway-data/metrics_hourly.csv gateway-data/metrics_daily.csv
	@echo "✓ Metrics synced to gateway-data/metrics.duckdb"

# Sync logs from prod (from Docker volume)
sync-logs:
	@echo "Syncing logs from prod..."
	@mkdir -p gateway-data/logs
	@rsync -avz --progress $(PROD_HOST):/var/lib/docker/volumes/yapit_gateway-data/_data/logs/*.jsonl* gateway-data/logs/
	@echo "Decompressing logs..."
	@gunzip -f gateway-data/logs/*.jsonl.gz 2>/dev/null || true
	@echo "✓ Logs synced to gateway-data/logs/"

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
	@uv run --with streamlit,pandas,plotly,duckdb,numpy streamlit run dashboard/__init__.py --server.port 8502 --server.headless true

# Dashboard without sync (use existing local data)
dashboard-local:
	@echo "Starting dashboard with local data..."
	@(sleep 2 && xdg-open http://localhost:8502 2>/dev/null || open http://localhost:8502 2>/dev/null || true) &
	@uv run --with streamlit,pandas,plotly,duckdb,numpy streamlit run dashboard/__init__.py --server.port 8502 --server.headless true

