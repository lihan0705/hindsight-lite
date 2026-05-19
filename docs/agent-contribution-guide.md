# Agent Contribution Guide

This guide is written for humans and coding agents contributing to
`hindsight-lite`.

`hindsight-lite` is a subtractive fork. Keep the product small, local-first, and
plugin-first. Do not bring back upstream Hindsight surfaces unless the task
explicitly needs them.

## Before Editing

Start from a clean understanding of the repository:

```bash
git status --short
```

If there are existing changes, do not revert them unless the user explicitly
asks. Treat unrelated changes as user work.

For codebase understanding, start with:

```text
.understand-anything/analysis-summary.json
.understand-anything/meta.json
.understand-anything/knowledge-graph.json
```

Then use targeted source search:

```bash
rg "term"
rg --files
```

Before Python or TypeScript implementation work, read:

```text
AGENTS.md
CLAUDE.md
.claude/skills/code-review/SKILL.md
```

## Branch Workflow

Use `main` as the integration branch.

Update local `main` before starting a new change:

```bash
git checkout main
git pull --rebase origin main
```

Create a focused branch:

```bash
git checkout -b feat/short-description
```

Use prefixes that describe the work:

```text
feat/<topic>
fix/<topic>
docs/<topic>
chore/<topic>
```

Keep one branch focused on one change. Do not mix unrelated cleanup, formatting,
dependency churn, or generated files into a feature branch.

## Implementation Rules

Prefer subtraction:

- delete or simplify invalid surfaces,
- keep local Python core behavior small,
- avoid compatibility shims that are not actively used,
- avoid daemon, server, database, cloud, or UI dependencies in the lite path.

Follow nearby patterns before adding abstractions.

For structured Python data, use dataclasses or Pydantic models. Do not use raw
dicts for known schemas, and do not return multi-item tuples.

When changing behavior, add or update focused tests first. For deleted behavior,
remove or update tests that asserted the old surface.

## Verification

Run the narrow tests that cover the change.

For the current lite Codex path:

```bash
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v
```

After Python or TypeScript/Node changes, run:

```bash
./scripts/hooks/lint.sh
```

Before committing, run:

```bash
git diff --check
git status --short
```

If `./scripts/hooks/lint.sh` modifies files, inspect the diff before staging.
Do not keep generated dependency or formatting noise unless it is required for
the task.

## Commit Workflow

Review the diff:

```bash
git diff --stat
git diff
```

Stage only the intended files:

```bash
git add path/to/file path/to/test
```

Check what will be committed:

```bash
git diff --cached --name-only
git diff --cached --stat
```

Commit with a clear message:

```bash
git commit -m "feat: add codex file context hook"
```

Use concise commit prefixes:

```text
feat: user-visible feature
fix: bug fix
docs: documentation-only change
test: test-only change
chore: repository maintenance
refactor: behavior-preserving code change
```

Do not amend commits unless the user explicitly asks.

## Merge Request Or Pull Request

Before opening an MR/PR, make sure the branch is current:

```bash
git fetch origin
git rebase origin/main
```

Resolve conflicts deliberately. Do not use destructive commands such as
`git reset --hard` or `git checkout --` unless the user explicitly approved that
operation.

Push the branch:

```bash
git push -u origin feat/short-description
```

Open the MR/PR against `main`.

The MR/PR description should include:

```markdown
## Summary
- What changed
- Why it changed

## Verification
- `uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v`
- `./scripts/hooks/lint.sh`
- `git diff --check`

## Notes
- Any skipped verification and why
- Any follow-up work intentionally left out
```

If merging locally after review:

```bash
git checkout main
git pull --rebase origin main
git merge --no-ff feat/short-description
git push origin main
```

After merge, confirm:

```bash
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

`HEAD` and `origin/main` should match after a direct push to `main`.

## Agent-Specific Checklist

Agents should follow this checklist before final response:

- Read `.understand-anything` first for repo orientation.
- Check `git status --short` before editing.
- Keep unrelated user changes intact.
- Add focused tests for behavior changes.
- Run relevant tests.
- Run `./scripts/hooks/lint.sh` after Python or TypeScript/Node changes.
- Run `git diff --check`.
- Stage only intended files.
- Report exact verification commands and results.

If a command fails because dependencies are missing or network access is blocked,
state the actual failure and fix the environment only as far as needed for the
requested change.
