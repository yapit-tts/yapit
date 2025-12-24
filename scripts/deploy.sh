#!/usr/bin/env bash
# Deploy script - pulls latest, decrypts secrets, runs docker compose
# Run on VPS: /opt/yapit/scripts/deploy.sh
set -euo pipefail

REPO_DIR="/opt/yapit"
AGE_KEY="/root/.age/yapit.txt"

cd "$REPO_DIR"

echo "==> Pulling latest code..."
git pull --ff-only

echo "==> Decrypting secrets..."
SOPS_AGE_KEY_FILE="$AGE_KEY" sops -d .env.local.sops > .env.local

echo "==> Starting services..."
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans

echo "==> Deploy complete"
