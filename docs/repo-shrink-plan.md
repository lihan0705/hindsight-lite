# Repo Shrink Plan

This repository is now oriented around `hindsight-lite`: a local-first memory
runtime for Codex CLI using Markdown, JSONL, and static inspection tools. The
remaining upstream monorepo surface should be removed in small PRs so each
change has a clear blast radius and verification path.

## Keep

| Area | Why |
|---|---|
| `hindsight_lite/` | Local memory runtime, CLI, Codex memory importer, memory tree UI |
| `tests/hindsight_lite/` | Focused unit coverage for the local runtime |
| `hindsight-integrations/codex/` | V1 Codex hook integration |
| `docs/assets/` | README architecture and UI preview images |
| `docs/agent-contribution-guide.md` | Current contribution workflow |
| `README.md`, `AGENTS.md`, `CLAUDE.md` | Primary project and agent instructions |
| `scripts/hooks/` | Current pre-commit verification entry points, until simplified |

## Remove In Stages

| Stage | Candidate surface | Rationale | Notes |
|---|---|---|---|
| 1 | Local residue and stale planning docs | Lowest risk cleanup | Remove tracked local-only files such as `.sesskey`; review old `docs/superpowers/` implementation notes |
| 2 | Non-Codex integrations | V1 is Codex-first | Keep only `hindsight-integrations/codex/`; remove release/test references in the same PR |
| 3 | Control plane and docs site | Lite has no server UI or Docusaurus docs site | Remove `hindsight-control-plane/`, `hindsight-docs/`, related npm workspaces and docs workflows |
| 4 | API, database, clients, CLI, packaging wrappers | Lite runtime does not use FastAPI, PostgreSQL, generated clients, Rust CLI, or meta packages | Remove `hindsight-api-slim/`, `hindsight-api/`, `hindsight-clients/`, `hindsight-cli/`, `hindsight-all*`, `hindsight-embed/`, `hindsight-dev/` after scripts and CI are narrowed |
| 5 | Deployment, release, benchmarks, monitoring | No hosted service remains | Remove Docker, Helm, release workflows, benchmark scripts, monitoring configs |

## Rewrite Alongside Deletions

- `CLAUDE.md` and `AGENTS.md` should describe the lite runtime, not the upstream
  API/control-plane monorepo.
- `pyproject.toml` should stop listing deleted uv workspace members.
- `package.json`, `package-lock.json`, and `deno.lock` should be removed once no
  tracked Node workspace remains.
- `.github/workflows/test.yml` should shrink to the lite Python tests and Codex
  integration tests.
- `scripts/hooks/lint.sh` should stop linting deleted packages and only cover
  the local Python runtime plus active Codex integration.

## Verification Target

The reduced repository should still pass:

```bash
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v
./scripts/hooks/lint.sh
git diff --check
```

Each deletion PR should state which surfaces were removed, which references were
updated, and which verification commands passed.
