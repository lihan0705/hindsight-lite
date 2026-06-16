# CLAUDE.md

This file provides guidance to Claude Code and other coding agents working in
this repository.

## Project Overview

`hindsight-lite` is a local-first memory runtime for AI coding agents. It stores
agent memory as editable files, with no API server, daemon, database, generated
SDKs, or hosted control plane.

The first supported integration is Codex CLI. Codex hooks call the local Python
runtime to retain session memory, recall compact context, and write reflection
requests for later evaluation/RL data work.

## Development Commands

```bash
# Run focused test coverage
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v

# Lint and format Python code
./scripts/hooks/lint.sh

# Exercise the local CLI
python3 -m hindsight_lite --help
python3 -m hindsight_lite memory-ui --bank codex
```

## Architecture

Tracked runtime surface:

- `hindsight_lite/`: local memory runtime and CLI
- `tests/hindsight_lite/`: focused tests for the local runtime
- `hindsight-integrations/codex/`: Codex hook scripts, sample settings, and tests
- `docs/assets/`: README images and UI previews
- `docs/agent-contribution-guide.md`: contribution workflow
- `scripts/hooks/lint.sh`: local lint entry point

The memory store is file-based:

```text
~/.hindsight-lite/
  banks/
    <bank_id>/
      sessions/*.jsonl
      pages/*.md
      reflections/*.json
      index/recall-index.json
      metadata.json
```

Core modules:

- `hindsight_lite/store.py`: typed file-store operations
- `hindsight_lite/index.py`: rebuildable typed BM25 index over sessions and pages
- `hindsight_lite/recall.py`: indexed local recall with compact excerpts
- `hindsight_lite/reflection.py`: reflection request packet creation
- `hindsight_lite/codex_memory.py`: Codex memory import
- `hindsight_lite/memory_ui.py`: static memory tree inspector
- `hindsight_lite/cli.py`: command-line surface

Codex hook flow:

```text
SessionStart      -> codex_hook.py -> session_start.py
UserPromptSubmit  -> codex_hook.py -> recall.py
PreToolUse        -> codex_hook.py -> file_context.py
Stop              -> codex_hook.py -> retain.py
```

## Coding Conventions

- Keep changes scoped to the lite runtime and active Codex integration.
- Prefer deleting stale upstream surface over adding compatibility shims.
- Use dataclasses or Pydantic models for known structured data.
- Do not return multi-item tuples from Python helpers.
- Keep comments for non-obvious reasoning, not line-by-line narration.
- Update tests with behavior changes and remove tests for deleted behavior.

## Verification

Before opening a PR, run:

```bash
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v
./scripts/hooks/lint.sh
git diff --check
```
