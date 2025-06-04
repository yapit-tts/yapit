#!/bin/bash
# scripts/get_token.sh
# Helper script to get access token without make output pollution

set -a
source .env.dev
set +a

# Run the Python script and capture only stdout
exec uv run python scripts/create_dev_user.py --print-token 2>/dev/null