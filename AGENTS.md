# AGENTS.md

This repository is a subtractive fork of Hindsight for heavier secondary
development. Treat the upstream implementation as reference material, but do
not default to adding features or preserving every upstream surface area.

## Source Of Truth

Read [CLAUDE.md](./CLAUDE.md) before making code changes. It contains the
project architecture, local commands, and hard coding conventions.

Before Python or TypeScript implementation work, also read
[.claude/skills/code-review/SKILL.md](./.claude/skills/code-review/SKILL.md).
Its standards apply here even when using Codex instead of Claude Code.

## Fork Direction

The intended direction is subtraction:

- Prefer deleting, simplifying, or narrowing behavior over adding new
  compatibility layers.
- Keep changes scoped to the new product direction; avoid upstream-style
  feature accumulation unless explicitly requested.
- When removing code, remove the related docs, tests, release hooks, generated
  clients, workflows, and integration references in the same change when they
  are no longer valid.
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
- After Python or TypeScript/Node changes, run `./scripts/hooks/lint.sh`.
- Add or update focused tests for behavior changes. For deleted behavior, update
  or remove tests that asserted the old surface.
- Before pushing or opening a PR, run the repository code-review workflow
  described in `CLAUDE.md` and resolve must-fix findings.

## Useful Commands

```bash
# Start API
./scripts/dev/start.sh

# API tests
cd hindsight-api-slim && uv run pytest tests/

# Lint Python and TypeScript/Node changes
./scripts/hooks/lint.sh
```
