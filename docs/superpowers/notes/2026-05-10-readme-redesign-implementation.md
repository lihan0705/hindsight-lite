# README Redesign Implementation Notes

## Intent

The README rewrite reframes this repository as `hindsight-lite`, a subtractive
fork of upstream Hindsight. The goal is to make the first screen match the new
product direction before implementation begins:

- Codex-first local memory plugin
- Markdown/JSONL storage
- no server, daemon, database, cloud dependency, or control plane
- small V1 surface with retain, recall, reflect, list pages, and get page
- reflection requests as future agentic RL data artifacts

The upstream README is preserved instead of deleted, because the original
project is still useful reference material while this fork is being reduced.

## Method

1. Preserve the original root `README.md` at
   `docs/upstream/HINDSIGHT_README.md`.
2. Replace the root README with a short, honest landing page for the fork.
3. Avoid broken assets by not referencing a logo file that does not exist yet.
4. Use status badges that say "design" and "Codex CLI first" instead of
   implying completed support.
5. Link to the active Codex local memory plugin design spec as the source of
   implementation truth.
6. Keep the page focused on the current V1. Do not import the full OrcaMemo
   five-layer model into this repository README.

## Philosophy

The fork should communicate subtraction, not replacement theater.

Upstream Hindsight is a full platform. `hindsight-lite` should be legible as a
local plugin system: fewer moving parts, inspectable files, and a narrow agent
workflow. The README therefore avoids benchmark claims, cloud onboarding,
Docker commands, and broad integration marketing. Those belong to upstream.

The central product promise is operational memory for coding agents:

```text
Store locally. Recall narrowly. Reflect for future training data.
```

That sentence encodes three implementation constraints:

- storage must stay local and user-inspectable,
- recall must be conservative enough not to pollute the context window,
- reflection should produce structured artifacts that can later become
  evaluation or training data.

## What Was Deliberately Not Added

- No install command yet, because the Codex local runtime is still at design
  stage.
- No logo reference, because `docs/logo.png` does not exist.
- No claim that Claude Code or OpenCode adapters are implemented.
- No page create/update/delete commands in the V1 feature table.
- No server/API/daemon setup instructions.

## Follow-Up

After Codex V1 is implemented, update README status from `design` to `alpha`
and add verified install and smoke-test commands. Those commands should come
from real local verification, not aspirational package names.
