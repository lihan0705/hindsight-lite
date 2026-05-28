# AGENTS.md

This repository is a subtractive fork of Hindsight focused on `hindsight-lite`:
a local-first memory runtime for Codex CLI using Markdown, JSONL, and static
inspection tools.

## Source Of Truth

Read [CLAUDE.md](./CLAUDE.md) before making code changes. It contains the
current project architecture, local commands, and conventions.

Before Python implementation work, also read
[.claude/skills/code-review/SKILL.md](./.claude/skills/code-review/SKILL.md).
Its standards apply here even when using Codex instead of Claude Code.

## Fork Direction

The intended direction is subtraction:

- Prefer deleting, simplifying, or narrowing behavior over adding new
  compatibility layers.
- Keep changes scoped to the lite runtime and Codex integration.
- When removing code, remove related docs, tests, workflows, scripts, and
  references in the same change when they are no longer valid.
- Preserve user-visible correctness over nominal backwards compatibility.
- Do not leave dead adapters, unused exports, placeholder compatibility shims,
  or "removed" comments behind.

## Working Rules

- Check `git status --short` before editing and do not revert unrelated user
  changes.
- For codebase understanding, start from `.understand-anything/` before broad
  source search. Read `analysis-summary.json`, `meta.json`, and
  `knowledge-graph.json` to orient on layers, tour steps, and relevant nodes,
  then use targeted `rg` searches in the source tree.
- Follow nearby code style and package boundaries instead of introducing broad
  abstractions.
- Keep structured Python data typed with Pydantic models or dataclasses; do not
  use raw dicts for known schemas or multi-item tuple returns.
- After Python changes, run `./scripts/hooks/lint.sh`.
- Add or update focused tests for behavior changes. For deleted behavior, update
  or remove tests that asserted the old surface.
- Before pushing or opening a PR, run the repository code-review workflow
  described in `CLAUDE.md` and resolve must-fix findings.

## Useful Commands

```bash
# Lite runtime and Codex integration tests
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v

# Lint Python code
./scripts/hooks/lint.sh
```
