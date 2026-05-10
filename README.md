<h1 align="center">
  hindsight-lite
</h1>

<p align="center">
  <strong>Local-first memory for AI coding agents.</strong>
</p>

<p align="center">
  <a href="https://github.com/lihan0705/hindsight-lite"><img src="https://img.shields.io/badge/status-design-orange?style=flat-square" alt="Status"></a>
  <a href="https://github.com/lihan0705/hindsight-lite"><img src="https://img.shields.io/badge/Codex_CLI-first-ff6b35?style=flat-square" alt="Codex CLI"></a>
  <a href="https://github.com/lihan0705/hindsight-lite"><img src="https://img.shields.io/badge/Claude_Code-later-c97539?style=flat-square" alt="Claude Code"></a>
  <a href="https://github.com/lihan0705/hindsight-lite"><img src="https://img.shields.io/badge/OpenCode-later-22c55e?style=flat-square" alt="OpenCode"></a>
  <img src="https://img.shields.io/badge/memory-Markdown%2FJSONL-black?style=flat-square" alt="Markdown/JSONL">
  <img src="https://img.shields.io/badge/no_server-no_daemon-lightgrey?style=flat-square" alt="No server">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square" alt="License">
</p>

<p align="center">
  <code>#agent-memory</code>
  <code>#codex</code>
  <code>#local-first</code>
  <code>#markdown-jsonl</code>
  <code>#rl-ready</code>
</p>

> This project is a subtractive fork of
> [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight).
> The upstream README is preserved at
> [docs/upstream/HINDSIGHT_README.md](docs/upstream/HINDSIGHT_README.md).

hindsight-lite keeps the agent memory workflow and removes the heavy product
surface: no server, no daemon, no database, no cloud dependency, and no control
plane UI.

The first target is Codex CLI. The V1 design stores memory locally as editable
Markdown and JSONL files, then injects only compact, relevant memory through the
existing Codex hook mechanism.

```text
Store locally. Recall narrowly. Reflect for future training data.
```

---

## Why This Fork?

Upstream Hindsight is a full memory platform with an API server, database,
control plane, SDKs, Docker/Helm deployment, and many framework integrations.

hindsight-lite is the subtractive version for coding agents:

- local files instead of hosted infrastructure,
- Codex hooks instead of a memory server,
- Markdown pages and JSONL sessions instead of PostgreSQL,
- explicit reflection packets instead of hidden model calls,
- a small plugin surface before broader multi-agent support.

The goal is not to reproduce every upstream feature. The goal is to keep the
parts that help an agent remember project work and remove the parts that make a
local plugin hard to install, inspect, or reason about.

---

## Codex-First V1

The V1 scope is intentionally small.

| Capability | Status | Mechanism |
|---|---:|---|
| `agent_knowledge_retain` | design | Codex `Stop` hook writes session JSONL |
| `agent_knowledge_recall` | design | Codex `UserPromptSubmit` injects compact context |
| `agent_knowledge_reflect` | design | local recall packet plus saved reflection request |
| `agent_knowledge_list_pages` | design | lists local Markdown pages |
| `agent_knowledge_get_page` | design | reads one local Markdown page |

The existing Codex integration already has the right hook shape:

```text
SessionStart      -> session_start.py
UserPromptSubmit  -> recall.py
Stop              -> retain.py
```

hindsight-lite keeps that contract and replaces the backend:

```text
old:
  Codex hook -> recall.py / retain.py -> daemon/API client -> Hindsight server

new:
  Codex hook -> recall.py / retain.py -> local Python core -> Markdown/JSONL
```

---

## Memory Files

Default local memory root:

```text
~/.hindsight-lite/
```

Bank layout:

```text
~/.hindsight-lite/
  banks/
    <bank_id>/
      sessions/
        <session_id>.jsonl
      pages/
        <page_id>.md
      reflections/
        <session_id>.jsonl
      index/
        recall-cache.json
      metadata.json
```

V1 memory types:

- `sessions/*.jsonl` stores retained Codex conversation snapshots.
- `pages/*.md` stores user-readable knowledge pages.
- `reflections/*.jsonl` stores reflection requests for later analysis.

This keeps memory readable, diffable, scriptable, and easy to delete.

---

## Recall Injection

Codex recall remains automatic.

Before each user prompt, `recall.py` reads the hook input, derives the bank,
runs local text retrieval over sessions and pages, and emits:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<hindsight_memories>...</hindsight_memories>"
  }
}
```

Codex injects `additionalContext` into the current turn. Retain strips
`<hindsight_memories>` blocks before writing session memory, which prevents
memory feedback loops.

---

## Reflection For Agentic RL Data

`agent_knowledge_reflect` is a data boundary, not an LLM wrapper.

It does not call a model. It performs local recall, builds a structured packet,
and saves a `reflection_request` event:

```json
{
  "type": "reflection_request",
  "query": "What should we remember about this repo?",
  "retrieved_context": [],
  "task_context": {
    "cwd": "/path/to/project",
    "git_commit": "abcdef",
    "recent_prompt": "..."
  },
  "reflection_prompt": "Use the retrieved evidence to produce a concise decision-oriented reflection..."
}
```

That shape is meant to support future agentic RL datasets:

```text
state/context -> retrieved memory -> reflection request -> later agent action
```

V1 records reflection requests only. Reflection results can be added later once
the training/evaluation schema is stable.

---

## Current Design

The active design spec is:

[docs/superpowers/specs/2026-05-10-codex-local-memory-plugin-design.md](docs/superpowers/specs/2026-05-10-codex-local-memory-plugin-design.md)

The implementation strategy and README rewrite rationale are recorded in:

[docs/superpowers/notes/2026-05-10-readme-redesign-implementation.md](docs/superpowers/notes/2026-05-10-readme-redesign-implementation.md)

---

## Original Hindsight

This repository started from upstream Hindsight:

- Upstream repository:
  [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
- Preserved upstream README:
  [docs/upstream/HINDSIGHT_README.md](docs/upstream/HINDSIGHT_README.md)

The upstream project remains the reference for the original full-stack memory
platform. hindsight-lite is the local plugin fork.

---

## License

MIT
