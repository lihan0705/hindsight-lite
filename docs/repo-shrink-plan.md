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
| 1 | Local residue and stale planning docs | Lowest risk cleanup | `.sesskey` removed; old `docs/superpowers/` implementation notes removed |
| 2 | Non-Codex integrations | V1 is Codex-first | Python, Node, and plugin integrations removed; only Codex remains |
| 3 | Control plane and docs site | Lite has no server UI or Docusaurus docs site | Control plane, docs site, docs-derived skills, and related workflows removed |
| 4 | API, database, clients, CLI, packaging wrappers | Lite runtime does not use FastAPI, PostgreSQL, generated clients, Rust CLI, or meta packages | API packages, generated clients, Rust CLI, meta packages, old dev tools, and dependent package/release workflows removed |
| 5 | Deployment, release, benchmarks, monitoring | No hosted service remains | Docker, Helm, benchmark scripts, monitoring assets, and hosted-release workflows removed |

## Rewrite Alongside Deletions

- `CLAUDE.md` and `AGENTS.md` should describe the lite runtime, not the
  remaining upstream monorepo surface.
- `pyproject.toml` now describes the lite runtime and test/lint tooling.
- `package.json`, `package-lock.json`, and `deno.lock` were removed with the
  final tracked Node workspaces.
- `.github/workflows/test.yml` now runs only lite Python tests and Codex
  integration tests.
- `scripts/hooks/lint.sh` now covers only the local Python runtime plus active
  Codex integration.

## Verification Target

The reduced repository should still pass:

```bash
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v
./scripts/hooks/lint.sh
git diff --check
```

Each deletion PR should state which surfaces were removed, which references were
updated, and which verification commands passed.
