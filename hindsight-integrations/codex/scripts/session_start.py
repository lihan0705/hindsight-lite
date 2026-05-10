#!/usr/bin/env python3
"""SessionStart hook: initialize local hindsight-lite memory.

Fires once when a Codex session begins. Ensures the local bank directory exists
so the first recall or retain hook can use Markdown/JSONL storage immediately.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.bank import derive_bank_id
from lib.config import debug_log, load_config

from hindsight_lite.store import LocalMemoryStore


def main():
    config = load_config()

    if not config.get("autoRecall") and not config.get("autoRetain"):
        debug_log(config, "Both autoRecall and autoRetain disabled, skipping session start")
        return

    # Consume stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    debug_log(config, f"SessionStart hook, session: {hook_input.get('session_id', 'unknown')}")

    bank_id = derive_bank_id(hook_input, config)
    LocalMemoryStore(bank_id=bank_id)
    debug_log(config, f"Initialized local hindsight-lite bank: {bank_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] SessionStart error: {e}", file=sys.stderr)
        sys.exit(0)
