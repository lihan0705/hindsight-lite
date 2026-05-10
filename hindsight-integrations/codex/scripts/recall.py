#!/usr/bin/env python3
"""Auto-recall hook for UserPromptSubmit.

Fires before each user prompt. Retrieves relevant memories from Hindsight
and injects them into the Codex context via hookSpecificOutput.additionalContext.

Flow:
  1. Read hook input from stdin (session_id, transcript_path, prompt/user_prompt)
  2. Derive bank ID
  3. Open local hindsight-lite store
  4. Compose multi-turn query if recallContextTurns > 1
  5. Truncate to recallMaxQueryChars
  6. Recall from local Markdown/JSONL memory
  7. Format memories and output hookSpecificOutput.additionalContext

Exit codes:
  0 — always (graceful degradation on any error)
"""

import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.bank import derive_bank_id
from lib.config import debug_log, load_config
from lib.content import (
    compose_recall_query,
    read_transcript,
    truncate_recall_query,
)
from lib.state import write_state

from hindsight_lite.recall import format_recall_for_codex, recall
from hindsight_lite.store import LocalMemoryStore

LAST_RECALL_STATE = "last_recall.json"


def main():
    if sys.platform == "win32":
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

    config = load_config()

    if not config.get("autoRecall"):
        debug_log(config, "Auto-recall disabled, exiting")
        return

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("[Hindsight] Failed to read hook input", file=sys.stderr)
        return

    debug_log(config, f"Hook input keys: {list(hook_input.keys())}")

    # Extract user query — accept both "prompt" and "user_prompt" defensively
    prompt = (hook_input.get("prompt") or hook_input.get("user_prompt") or "").strip()
    if not prompt or len(prompt) < 5:
        debug_log(config, "Prompt too short for recall, skipping")
        return

    def _dbg(*a):
        debug_log(config, *a)

    bank_id = derive_bank_id(hook_input, config)
    store = LocalMemoryStore(bank_id=bank_id)

    # Multi-turn query composition
    recall_context_turns = config.get("recallContextTurns", 1)
    recall_max_query_chars = config.get("recallMaxQueryChars", 800)
    recall_roles = config.get("recallRoles", ["user", "assistant"])

    if recall_context_turns > 1:
        transcript_path = hook_input.get("transcript_path", "")
        messages = read_transcript(transcript_path)
        debug_log(config, f"Multi-turn context: {recall_context_turns} turns, {len(messages)} messages")
        query = compose_recall_query(prompt, messages, recall_context_turns, recall_roles)
    else:
        query = prompt

    query = truncate_recall_query(query, prompt, recall_max_query_chars)
    if len(query) > recall_max_query_chars:
        query = query[:recall_max_query_chars]

    query = query.encode('utf-8', errors='ignore').decode('utf-8')

    preamble = config.get("recallPromptPreamble", "")
    max_results = config.get("recallMaxResults", 5)

    debug_log(config, f"Recalling from local bank '{bank_id}', query length: {len(query)}")
    try:
        results = recall(store, query=query, max_results=max_results)
    except Exception as e:
        print(f"[Hindsight] Recall failed: {e}", file=sys.stderr)
        return

    if not results:
        debug_log(config, "No memories found")
        return

    debug_log(config, f"Injecting {len(results)} memories")

    context_message = format_recall_for_codex(results, preamble=preamble)

    write_state(
        LAST_RECALL_STATE,
        {
            "context": context_message,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bank_id": bank_id,
            "result_count": len(results),
        },
    )

    # Output JSON for Codex hook system
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context_message,
        }
    }
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] Unexpected error in recall: {e}", file=sys.stderr)
        try:
            from lib.config import load_config

            sys.exit(2 if load_config().get("debug") else 0)
        except Exception:
            sys.exit(0)
