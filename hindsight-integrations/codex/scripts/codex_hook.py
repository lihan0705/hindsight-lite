#!/usr/bin/env python3
"""Small dispatcher for Codex hook events."""

import io
import json
import os
import sys
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import file_context
import recall
import retain
import session_start

_HANDLERS: dict[str, Callable[[], None]] = {
    "SessionStart": session_start.main,
    "UserPromptSubmit": recall.main,
    "PreToolUse": file_context.main,
    "Stop": retain.main,
}


def main() -> None:
    event_name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in _HANDLERS else ""
    raw_input = sys.stdin.read()
    if not event_name:
        event_name = _event_name_from_input(raw_input)

    handler = _HANDLERS.get(event_name)
    if handler is None:
        return

    sys.stdin = io.StringIO(raw_input)
    handler()


def _event_name_from_input(raw_input: str) -> str:
    try:
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError:
        return ""
    value = hook_input.get("hook_event_name")
    return value if isinstance(value, str) else ""


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] Unexpected error in Codex hook dispatcher: {e}", file=sys.stderr)
        sys.exit(0)
