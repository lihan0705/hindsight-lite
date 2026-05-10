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
