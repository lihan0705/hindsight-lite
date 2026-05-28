#!/bin/bash
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "  Syncing Python dependencies..."
uv sync --quiet

echo "  Running ruff checks..."
uv run ruff check --fix \
    "$REPO_ROOT/hindsight_lite" \
    "$REPO_ROOT/tests/hindsight_lite" \
    "$REPO_ROOT/hindsight-integrations/codex/scripts" \
    "$REPO_ROOT/hindsight-integrations/codex/tests"

uv run ruff format \
    "$REPO_ROOT/hindsight_lite" \
    "$REPO_ROOT/tests/hindsight_lite" \
    "$REPO_ROOT/hindsight-integrations/codex/scripts" \
    "$REPO_ROOT/hindsight-integrations/codex/tests"

echo "  All lints passed ✓"
