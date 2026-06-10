#!/usr/bin/env python3
"""PreToolUse hook: inject compact memory for files Codex is about to read."""

import json
import os
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.bank import derive_bank_id
from lib.config import debug_log, load_config

from hindsight_lite.models import RecallResult
from hindsight_lite.recall import format_recall_result_line, recall
from hindsight_lite.store import LocalMemoryStore

_PATH_KEYS = ("file_path", "path", "filename")
_PATH_LIST_KEYS = ("filePaths", "file_paths", "paths")
_READ_COMMANDS = {"cat", "sed", "rg", "grep", "head", "tail", "less", "more", "nl"}


def main() -> None:
    config = load_config()

    if not config.get("autoFileContext", True):
        debug_log(config, "Auto file context disabled, exiting")
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print("[Hindsight] Failed to read hook input", file=sys.stderr)
        return

    file_paths = _extract_file_paths(hook_input)
    if not file_paths:
        debug_log(config, "No readable file path in PreToolUse input")
        return
    file_paths = [path for path in file_paths if not _is_memory_path(path)]
    if not file_paths:
        debug_log(config, "Skipping file context for memory store paths")
        return

    bank_id = derive_bank_id(hook_input, config)
    store = LocalMemoryStore(bank_id=bank_id)
    max_results = int(config.get("fileContextMaxResults", 3))
    excerpt_max_chars = int(config.get("fileContextMaxExcerptChars", config.get("recallMaxExcerptChars", 140)))
    query = " ".join(file_paths)
    results = recall(store, query=query, max_results=max_results)
    if not results:
        debug_log(config, f"No file context memories for {file_paths}")
        return

    context_message = _format_file_context(
        file_paths=file_paths,
        preamble=config.get("fileContextPromptPreamble", ""),
        results=results,
        excerpt_max_chars=excerpt_max_chars,
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": context_message,
        }
    }
    json.dump(output, sys.stdout)


def _extract_file_paths(hook_input: Mapping[str, object]) -> list[str]:
    tool_name = hook_input.get("tool_name")
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        return []

    paths = _extract_structured_paths(tool_input)
    if paths:
        return paths

    if tool_name == "Bash":
        command = tool_input.get("command") or tool_input.get("cmd")
        if isinstance(command, list):
            command = " ".join(str(part) for part in command)
        if isinstance(command, str):
            return _extract_shell_read_paths(command)

    return []


def _extract_structured_paths(tool_input: Mapping[str, object]) -> list[str]:
    paths: list[str] = []
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str):
            paths.append(value)

    for key in _PATH_LIST_KEYS:
        value = tool_input.get(key)
        if isinstance(value, list):
            paths.extend(item for item in value if isinstance(item, str))

    return _dedupe_paths(paths)


def _extract_shell_read_paths(command: str) -> list[str]:
    try:
        parts = shlex.split(command)
    except ValueError:
        return []
    if not parts or Path(parts[0]).name not in _READ_COMMANDS:
        return []

    candidates = [part for part in parts[1:] if _looks_like_path(part)]
    return _dedupe_paths(candidates)


def _looks_like_path(value: str) -> bool:
    if not value or value.startswith("-"):
        return False
    return "/" in value or "." in Path(value).name


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in paths:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped[:10]


def _is_memory_path(value: str) -> bool:
    path = Path(value).expanduser()
    if not path.is_absolute():
        return False
    normalized = path.resolve(strict=False)
    memory_roots = [
        Path(os.environ.get("HINDSIGHT_LITE_HOME", "~/.hindsight-lite")).expanduser(),
        Path("~/.codex/memories").expanduser(),
        Path("~/.hindsight/codex").expanduser(),
    ]
    return any(_is_path_relative_to(normalized, root.resolve(strict=False)) for root in memory_roots)


def _is_path_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return path == root
    return True


def _format_file_context(
    file_paths: list[str],
    preamble: str,
    results: list[RecallResult],
    excerpt_max_chars: int,
) -> str:
    lines = ["<hindsight_lite_file_context>", preamble, f"FILES: {', '.join(file_paths)}", ""]
    for result in results:
        lines.append(format_recall_result_line(result, excerpt_max_chars))
    lines.append("</hindsight_lite_file_context>")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] Unexpected error in file context: {e}", file=sys.stderr)
        try:
            sys.exit(2 if load_config().get("debug") else 0)
        except Exception:
            sys.exit(0)
