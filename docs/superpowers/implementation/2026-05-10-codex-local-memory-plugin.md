# Codex Local Memory Plugin Implementation Notes

## Method

- Work in a feature worktree so the subtractive fork can move without touching unrelated user files.
- Commit each completed slice separately: path primitives, local storage, recall, reflection, CLI, and Codex hooks.
- Start each slice with focused tests, then implement only the minimum local core needed to make the test pass.
- Keep upstream Hindsight as reference material, not as a compatibility target.
- Prefer local Markdown and JSONL files under `~/.hindsight-lite` over daemon, API, database, or generated-client paths.
- Keep Codex-specific behavior at the adapter edge; keep reusable memory behavior in `hindsight_lite/`.

## Philosophy

hindsight-lite is a subtraction-first fork. The core should make memory easy to
inspect, edit, diff, and carry across agents without requiring a running server.

The first Codex adapter keeps five operations intentionally small:

- retain: append session memory locally,
- recall: retrieve compact action-changing context,
- reflect: prepare an agent-facing reflection packet for subagent review,
- list pages: inspect durable Markdown memory nodes,
- get page: read one durable memory node.

Reflection is treated as a data collection boundary, not an automatic belief
promotion step. The packet preserves enough structure for future agentic RL
exports while avoiding hidden model calls or permanent-memory side effects.

## 2026-05-16 Codex Hook Refinement

After reviewing `tmp/claude-mem`, I copied the parts that improve the Codex
adapter contract and rejected the parts that would make hindsight-lite heavy
again.

Useful ideas absorbed:

- A single hook dispatcher is easier to reason about than adding more standalone
  hook entrypoints forever.
- Hook failures must be non-blocking by default. Memory should improve Codex,
  not break the user's coding session.
- File-aware context is valuable when it stays compact. `PreToolUse` can inject
  a few relevant memories before Codex reads a file, without starting a worker
  or running semantic search.
- Context should remain progressive: inject compact excerpts first, then let the
  agent ask for full pages or future event details by ID.

Implementation details:

- Added `hindsight-integrations/codex/scripts/codex_hook.py` as the Codex hook
  dispatcher. It routes `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and
  `Stop` to the existing small Python handlers.
- Added `hindsight-integrations/codex/scripts/file_context.py` for `PreToolUse`
  file-context injection. It extracts file paths from structured tool input and
  simple shell read commands, recalls local Markdown/JSONL memory, and emits a
  compact `<hindsight_lite_file_context>` block with `permissionDecision:
  allow`.
- Updated `hindsight-integrations/codex/hooks/hooks.json` so installed Codex
  hooks call the dispatcher instead of calling each script directly.
- Added config keys `autoFileContext`, `fileContextMaxResults`, and
  `fileContextPromptPreamble`. The feature defaults on, but remains easy to
  disable from `~/.hindsight/codex.json` or environment.
- Kept storage unchanged: no Bun, no worker service, no SQLite, no Chroma, no
  MCP dependency.

The main design line stays the same: reuse hook lifecycle ideas from heavier
memory systems, but keep the actual memory core local, inspectable, and
Python-first.
