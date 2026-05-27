#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env to pick up HINDSIGHT_API_PORT if set
ROOT_DIR="$(git rev-parse --show-toplevel)"
if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi
API_PORT="${HINDSIGHT_API_PORT:-8888}"

echo "Starting API server..."
"$SCRIPT_DIR/start-api.sh" --port "$API_PORT"
