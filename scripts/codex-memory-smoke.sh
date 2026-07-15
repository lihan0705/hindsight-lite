#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKETPLACE_NAME="hindsight-local-smoke"
MARKETPLACE_ROOT="${TMPDIR:-/tmp}/hindsight-lite-codex-marketplace"
MEMORY_HOME="${HINDSIGHT_LITE_SMOKE_HOME:-${TMPDIR:-/tmp}/hindsight-lite-codex-smoke}"
BANK_ID="${HINDSIGHT_LITE_SMOKE_BANK:-codex-smoke}"
SERVE=0

usage() {
  cat <<'USAGE'
Usage: scripts/codex-memory-smoke.sh [--home DIR] [--bank BANK] [--serve]

Installs the current checkout as a local Codex plugin, runs several independent
Codex sessions, verifies local recall, and writes a MemoryTree HTML snapshot.

Environment:
  HINDSIGHT_LITE_SMOKE_HOME   Memory home directory (default: /tmp/hindsight-lite-codex-smoke)
  HINDSIGHT_LITE_SMOKE_BANK   Memory bank id (default: codex-smoke)

The script writes only to the selected memory home and a temporary local Codex
marketplace under /tmp, but Codex may update its user plugin configuration.
USAGE
}

while (($#)); do
  case "$1" in
    --home)
      MEMORY_HOME="${2:?missing value for --home}"
      shift 2
      ;;
    --bank)
      BANK_ID="${2:?missing value for --bank}"
      shift 2
      ;;
    --serve)
      SERVE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 127
  }
}

install_local_plugin() {
  rm -rf "$MARKETPLACE_ROOT"
  mkdir -p "$MARKETPLACE_ROOT/.agents/plugins" "$MARKETPLACE_ROOT/plugins"
  ln -s "$ROOT_DIR" "$MARKETPLACE_ROOT/plugins/hindsight-lite"
  cat >"$MARKETPLACE_ROOT/.agents/plugins/marketplace.json" <<JSON
{
  "name": "$MARKETPLACE_NAME",
  "interface": {
    "displayName": "hindsight-lite local smoke"
  },
  "plugins": [
    {
      "name": "hindsight-lite",
      "source": {
        "source": "local",
        "path": "./plugins/hindsight-lite"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
JSON

  codex plugin remove "hindsight-lite@$MARKETPLACE_NAME" --json >/dev/null 2>&1 || true
  codex plugin marketplace remove "$MARKETPLACE_NAME" --json >/dev/null 2>&1 || true
  codex plugin marketplace add "$MARKETPLACE_ROOT" --json >/dev/null
  codex plugin add "hindsight-lite@$MARKETPLACE_NAME" --json >/dev/null
}

run_codex_session() {
  local name="$1"
  local prompt="$2"
  local output="$3"
  echo "Running Codex session: $name"
  HINDSIGHT_LITE_HOME="$MEMORY_HOME" \
  HINDSIGHT_BANK_ID="$BANK_ID" \
  HINDSIGHT_RECALL_MAX_RESULTS=12 \
  codex exec \
    --json \
    --dangerously-bypass-hook-trust \
    -C "$ROOT_DIR" \
    -s read-only \
    "$prompt" </dev/null >"$output"
}

extract_agent_text() {
  python3 -c '
import json
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "agent_message":
        text = item.get("text")
        if isinstance(text, str):
            print(text)
' "$1"
}

assert_file_contains() {
  local file="$1"
  local expected="$2"
  if ! grep -Fq "$expected" "$file"; then
    echo "expected '$expected' in $file" >&2
    exit 1
  fi
}

assert_recall_contains() {
  local query="$1"
  local expected="$2"
  local output="$3"
  HINDSIGHT_LITE_HOME="$MEMORY_HOME" \
    python3 -m hindsight_lite --home "$MEMORY_HOME" agent_knowledge_recall --bank "$BANK_ID" "$query" >"$output"
  assert_file_contains "$output" "$expected"
}

assert_min_file_count() {
  local directory="$1"
  local pattern="$2"
  local minimum="$3"
  local actual
  actual="$(find "$directory" -name "$pattern" | wc -l)"
  if [[ "$actual" -lt "$minimum" ]]; then
    echo "expected at least $minimum $pattern file(s) in $directory, found $actual" >&2
    exit 1
  fi
}

assert_structured_retain_outputs() {
  local bank_dir="$MEMORY_HOME/banks/$BANK_ID"
  assert_min_file_count "$bank_dir/sessions" '*.jsonl' 10
  assert_min_file_count "$bank_dir/retains" '*.json' 10
  assert_min_file_count "$bank_dir/facts" '*.jsonl' 10
  assert_min_file_count "$bank_dir/observations/candidates" 'observe-*.json' 10
  assert_file_contains "$bank_dir/graph/nodes.jsonl" "retain_graph_node"
  assert_file_contains "$bank_dir/graph/edges.jsonl" "retain_graph_edge"
}

run_reflection_hook_smoke() {
  local transcript="$RUN_DIR/reflection-transcript.jsonl"
  local hook_input="$RUN_DIR/reflection-hook-input.json"
  cat >"$transcript" <<'JSONL'
{"role":"user","content":"Fix the failing authentication smoke test."}
{"role":"assistant","content":[{"type":"tool_use","name":"pytest","input":{"target":"test_auth_smoke.py"}},{"type":"tool_result","content":"1 failed\nexit_code: 1"},{"type":"tool_use","name":"apply_patch","input":{"file":"auth.py"}},{"type":"tool_result","content":"status: completed"},{"type":"text","text":"Fixed the authentication smoke test."}]}
JSONL
  python3 -c '
import json
import sys

payload = {
    "session_id": "reflection-smoke",
    "transcript_path": sys.argv[1],
    "cwd": sys.argv[2],
}
open(sys.argv[3], "w", encoding="utf-8").write(json.dumps(payload))
' "$transcript" "$ROOT_DIR" "$hook_input"
  HINDSIGHT_LITE_HOME="$MEMORY_HOME" \
  HINDSIGHT_BANK_ID="$BANK_ID" \
  PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    python3 "$ROOT_DIR/hindsight-integrations/codex/scripts/codex_hook.py" Stop <"$hook_input" \
    >"$RUN_DIR/reflection-hook-output.txt"

  local reflection_count
  reflection_count="$(find "$MEMORY_HOME/banks/$BANK_ID/reflections" -name 'reflect-auto-*.json' | wc -l)"
  if [[ "$reflection_count" -lt 1 ]]; then
    echo "expected at least one reflection candidate in $MEMORY_HOME/banks/$BANK_ID/reflections" >&2
    exit 1
  fi
  grep -R -Fq '"trigger_reason": "tool_failure"' "$MEMORY_HOME/banks/$BANK_ID/reflections" || {
    echo "expected reflection candidate trigger_reason=tool_failure" >&2
    exit 1
  }
}

require_cmd codex
require_cmd python3
require_cmd grep

mkdir -p "$MEMORY_HOME"
RUN_DIR="$MEMORY_HOME/.smoke-run"
mkdir -p "$RUN_DIR"

echo "Installing local plugin from: $ROOT_DIR"
install_local_plugin

echo "Memory home: $MEMORY_HOME"
echo "Bank: $BANK_ID"

run_codex_session \
  "aurora-storage" \
  "Do not run tools. Remember for hindsight-lite smoke: project Aurora uses SQLite for its local recall index. Reply exactly: aurora remembered." \
  "$RUN_DIR/session-aurora.jsonl"

run_codex_session \
  "editor-preference" \
  "Do not run tools. Remember for hindsight-lite smoke: the user prefers Neovim when editing Python memory code. Reply exactly: editor remembered." \
  "$RUN_DIR/session-editor.jsonl"

run_codex_session \
  "deploy-target" \
  "Do not run tools. Remember for hindsight-lite smoke: the demo service deploy target is Fly.io. Reply exactly: deploy remembered." \
  "$RUN_DIR/session-deploy.jsonl"

run_codex_session \
  "cache-policy" \
  "Do not run tools. Remember for hindsight-lite smoke: the cache policy is stale-while-revalidate for ten minutes. Reply exactly: cache remembered." \
  "$RUN_DIR/session-cache.jsonl"

run_codex_session \
  "api-owner" \
  "Do not run tools. Remember for hindsight-lite smoke: Maya owns the Memory API contract review. Reply exactly: owner remembered." \
  "$RUN_DIR/session-owner.jsonl"

run_codex_session \
  "incident-channel" \
  "Do not run tools. Remember for hindsight-lite smoke: production incidents go to channel #ops-memory. Reply exactly: channel remembered." \
  "$RUN_DIR/session-channel.jsonl"

run_codex_session \
  "release-day" \
  "Do not run tools. Remember for hindsight-lite smoke: weekly releases happen every Thursday. Reply exactly: release remembered." \
  "$RUN_DIR/session-release.jsonl"

run_codex_session \
  "test-runner" \
  "Do not run tools. Remember for hindsight-lite smoke: pytest is the required test runner. Reply exactly: tests remembered." \
  "$RUN_DIR/session-tests.jsonl"

run_codex_session \
  "ui-theme" \
  "Do not run tools. Remember for hindsight-lite smoke: the MemoryTree UI theme should stay high-contrast. Reply exactly: theme remembered." \
  "$RUN_DIR/session-theme.jsonl"

run_codex_session \
  "backup-region" \
  "Do not run tools. Remember for hindsight-lite smoke: the backup region is us-west-2. Reply exactly: backup remembered." \
  "$RUN_DIR/session-backup.jsonl"

echo "Verifying CLI recall across sessions..."
assert_structured_retain_outputs
assert_recall_contains "Aurora local recall index storage" "SQLite" "$RUN_DIR/recall-aurora.txt"
assert_recall_contains "preferred editor for Python memory code" "Neovim" "$RUN_DIR/recall-editor.txt"
assert_recall_contains "demo service deploy target" "Fly.io" "$RUN_DIR/recall-deploy.txt"
assert_recall_contains "cache policy duration" "stale-while-revalidate" "$RUN_DIR/recall-cache.txt"
assert_recall_contains "Memory API contract review owner" "Maya" "$RUN_DIR/recall-owner.txt"
assert_recall_contains "production incidents channel" "#ops-memory" "$RUN_DIR/recall-channel.txt"
assert_recall_contains "weekly release day" "Thursday" "$RUN_DIR/recall-release.txt"
assert_recall_contains "required test runner" "pytest" "$RUN_DIR/recall-tests.txt"
assert_recall_contains "MemoryTree UI theme" "high-contrast" "$RUN_DIR/recall-theme.txt"
assert_recall_contains "backup region" "us-west-2" "$RUN_DIR/recall-backup.txt"

run_codex_session \
  "cross-session-recall" \
  "Do not run tools. Based only on hindsight-lite memory, answer in ten short bullets: Aurora storage, editor preference, deploy target, cache policy, API owner, incident channel, release day, test runner, UI theme, and backup region." \
  "$RUN_DIR/session-cross-recall.jsonl"

echo "Verifying reflection candidate extraction..."
run_reflection_hook_smoke

HTML_PATH="$MEMORY_HOME/banks/$BANK_ID/memory-tree.html"
HINDSIGHT_LITE_HOME="$MEMORY_HOME" \
  python3 -m hindsight_lite --home "$MEMORY_HOME" memory-ui --bank "$BANK_ID" --output "$HTML_PATH"

echo
echo "Codex cross-session answer:"
extract_agent_text "$RUN_DIR/session-cross-recall.jsonl"

echo
echo "Memory files:"
find "$MEMORY_HOME/banks/$BANK_ID" -maxdepth 3 -type f | sort

echo
echo "Recall checks:"
cat "$RUN_DIR/recall-aurora.txt"
cat "$RUN_DIR/recall-editor.txt"
cat "$RUN_DIR/recall-deploy.txt"
cat "$RUN_DIR/recall-cache.txt"
cat "$RUN_DIR/recall-owner.txt"
cat "$RUN_DIR/recall-channel.txt"
cat "$RUN_DIR/recall-release.txt"
cat "$RUN_DIR/recall-tests.txt"
cat "$RUN_DIR/recall-theme.txt"
cat "$RUN_DIR/recall-backup.txt"

echo
echo "MemoryTree HTML:"
echo "$HTML_PATH"

if [[ "$SERVE" == "1" ]]; then
  echo
  echo "Serving editable MemoryTree UI. Press Ctrl-C to stop."
  HINDSIGHT_LITE_HOME="$MEMORY_HOME" \
    python3 -m hindsight_lite --home "$MEMORY_HOME" memory-ui --bank "$BANK_ID" --serve --open
fi
