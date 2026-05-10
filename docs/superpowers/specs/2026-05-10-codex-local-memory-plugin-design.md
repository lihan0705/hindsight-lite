# Codex Local Memory Plugin Design

## Goal

Turn this Hindsight fork into a lightweight, Codex-first local memory plugin.
The first implementation phase keeps the Codex hook flow and removes the
server, daemon, remote API, vector database, UI, generated clients, and broad
integration surface.

The V1 product surface is intentionally small:

- `agent_knowledge_retain`
- `agent_knowledge_recall`
- `agent_knowledge_reflect`
- `agent_knowledge_list_pages`
- `agent_knowledge_get_page`

The command names preserve the existing `agent_knowledge_*` style from the
Claude Code MCP tools, but V1 targets Codex first.

## Non-Goals

V1 does not include:

- FastAPI server or local daemon
- PostgreSQL, pgvector, embeddings, or rerankers
- Hindsight Cloud or remote API mode
- Next.js control plane UI
- OpenAPI/client generation
- OpenCode or Claude Code adapter rewrites
- page create/update/delete commands
- file ingest commands
- LLM provider calls inside the memory runtime

Reflect is important for future agentic RL data collection, but V1 only records
reflection requests. It does not require the runtime to synthesize reflection
results.

## Current Codex Baseline

The existing Codex integration already has the right hook shape:

- `SessionStart` runs `session_start.py`.
- `UserPromptSubmit` runs `recall.py`.
- `Stop` runs `retain.py`.

`recall.py` currently performs auto recall before each user prompt and emits
Codex hook JSON with `hookSpecificOutput.additionalContext`. Codex injects that
additional context into the current turn.

`retain.py` currently stores the transcript after a turn by calling the
Hindsight HTTP API.

The lightweight implementation keeps the hook contract and replaces the
transport and storage:

```text
old:
  Codex hook -> recall.py / retain.py -> daemon/API client -> Hindsight server

new:
  Codex hook -> recall.py / retain.py -> local Python core -> Markdown/JSONL
```

## Architecture

Add a small Python package that owns all local memory behavior:

```text
hindsight_lite/
  __init__.py
  __main__.py
  cli.py
  models.py
  paths.py
  store.py
  scoring.py
  formatting.py
  reflection.py
```

The package exposes both Python APIs and CLI commands. Codex hooks may import
the Python API directly for speed and testability. The CLI exists so the user
or agent can call the same functionality from shell commands.

The existing Codex scripts stay as thin adapters:

```text
hindsight-integrations/codex/scripts/recall.py
hindsight-integrations/codex/scripts/retain.py
hindsight-integrations/codex/scripts/session_start.py
```

`session_start.py` becomes a no-op or creates the local bank directories. It no
longer checks health or starts a daemon.

Remove or stop using these Codex implementation dependencies in V1:

- `scripts/lib/client.py`
- `scripts/lib/daemon.py`
- `scripts/lib/llm.py`
- server mission setup calls from `scripts/lib/bank.py`

Keep these pieces because they already solve Codex-specific problems:

- transcript parsing and memory-tag stripping in `scripts/lib/content.py`
- bank derivation in `scripts/lib/bank.py`
- config loading in `scripts/lib/config.py`, simplified for local-only options

## Local Storage

Default root:

```text
~/.hindsight-lite/
```

Config may override the root with `HINDSIGHT_LITE_HOME`.

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

`sessions/<session_id>.jsonl` stores retained memory events. Each event is a
single JSON object:

```json
{
  "type": "session_memory",
  "id": "mem_...",
  "timestamp": "2026-05-10T00:00:00Z",
  "bank_id": "codex",
  "session_id": "session-id",
  "source": "codex",
  "document_id": "session-id",
  "content": "formatted transcript text",
  "tags": ["session-id"],
  "metadata": {
    "cwd": "/path/to/project",
    "message_count": "12"
  }
}
```

`pages/<page_id>.md` stores user-readable knowledge pages. The runtime reads
frontmatter when present:

```markdown
---
id: project-rules
title: Project Rules
tags: [project, rules]
updated_at: 2026-05-10T00:00:00Z
---

Page content.
```

V1 lists and reads pages only. Page creation and mutation are deliberately left
out of the Codex-first scope.

`reflections/<session_id>.jsonl` stores reflection request events for future
agentic RL datasets.

## Commands

The CLI keeps the original knowledge-tool naming style:

```bash
python -m hindsight_lite agent_knowledge_retain
python -m hindsight_lite agent_knowledge_recall "query"
python -m hindsight_lite agent_knowledge_reflect "query"
python -m hindsight_lite agent_knowledge_list_pages
python -m hindsight_lite agent_knowledge_get_page page_id
```

All commands accept:

```bash
--bank <bank_id>
--home <path>
--json
```

Codex hooks can call internal Python functions instead of shelling out, but the
CLI and hooks must share the same core implementation.

## Retain Flow

`Stop` hook flow:

```text
read hook input from stdin
load local config
read Codex transcript JSONL
strip <hindsight_memories> blocks
filter configured roles/tool-call content
derive bank_id
append a session_memory event to sessions/<session_id>.jsonl
exit 0 on expected failures
```

V1 keeps the current graceful-degradation behavior: retain failures should not
break the Codex session unless debug mode explicitly asks for hard failures.

The first implementation should preserve full-session retain mode. Chunked
retain can remain only if it is cheap to keep after removing server-specific
logic.

## Recall Flow

`UserPromptSubmit` hook flow:

```text
read hook input from stdin
extract prompt / user_prompt
derive bank_id
optionally include recent transcript context in the query
run local recall over sessions/*.jsonl and pages/*.md
format top results as <hindsight_memories>
emit hookSpecificOutput.additionalContext JSON
```

The Codex hook output stays compatible with the existing integration:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<hindsight_memories>...</hindsight_memories>"
  }
}
```

Recall should inject a small context by default:

- top 3-5 results
- bounded excerpt length
- include source path and timestamp
- include pages and session memories in one ranked list

The formatter must keep the existing anti-feedback-loop contract by wrapping
in `<hindsight_memories>...</hindsight_memories>`, because retain strips those
blocks before writing session memory.

## Local Scoring

V1 uses lightweight text retrieval, not embeddings.

Required behavior:

- tokenize query and candidate text
- score exact phrase and token overlap
- prefer title/page-id matches for pages
- prefer recent session memory as a tie-breaker
- keep bank isolation strict
- return deterministic results for tests

The implementation may start with a BM25-like score or a simpler weighted token
score. It should not introduce a vector database or network dependency.

`index/recall-cache.json` is optional in V1. If implemented, it must be
rebuildable from `sessions/` and `pages/`.

## Reflect Flow

`agent_knowledge_reflect` does not call an LLM. It creates a structured packet
for the current agent to synthesize.

Flow:

```text
read query and task context
run local recall
build reflection_prompt
write reflection_request to reflections/<session_id>.jsonl
return the packet to stdout
```

Reflection request event:

```json
{
  "type": "reflection_request",
  "id": "refl_...",
  "timestamp": "2026-05-10T00:00:00Z",
  "bank_id": "codex",
  "session_id": "session-id",
  "query": "What should we remember about this repo?",
  "retrieved_context": [
    {
      "id": "mem_...",
      "source": "session",
      "path": "sessions/session-id.jsonl",
      "score": 0.82,
      "excerpt": "..."
    }
  ],
  "task_context": {
    "cwd": "/path/to/project",
    "git_commit": "abcdef",
    "recent_prompt": "..."
  },
  "reflection_prompt": "Use the retrieved evidence to produce a concise decision-oriented reflection..."
}
```

This gives future RL work a clean boundary:

```text
state/context -> retrieved memory -> reflection request -> later agent action
```

V1 does not implement `reflection_result`. Add it later only after the desired
training data schema is stable.

## Page Commands

`agent_knowledge_list_pages` returns page metadata:

```json
[
  {
    "id": "project-rules",
    "title": "Project Rules",
    "path": ".../pages/project-rules.md",
    "updated_at": "2026-05-10T00:00:00Z",
    "tags": ["project", "rules"]
  }
]
```

`agent_knowledge_get_page <page_id>` returns:

```json
{
  "id": "project-rules",
  "title": "Project Rules",
  "content": "Page content.",
  "path": ".../pages/project-rules.md",
  "metadata": {}
}
```

The page ID must resolve within the selected bank's `pages/` directory. Path
traversal is invalid.

## Configuration

Keep a small local-only configuration surface:

- `bankId`
- `bankIdPrefix`
- `dynamicBankId`
- `dynamicBankGranularity`
- `autoRecall`
- `autoRetain`
- `recallMaxTokens`
- `recallContextTurns`
- `recallMaxQueryChars`
- `retainRoles`
- `retainToolCalls`
- `retainEveryNTurns`
- `retainTags`
- `retainMetadata`
- `debug`
- `home`

Remove these settings from the Codex local-only path:

- `hindsightApiUrl`
- `hindsightApiToken`
- `apiPort`
- `daemonIdleTimeout`
- `embedVersion`
- `embedPackagePath`
- `llmProvider`
- `llmModel`
- `llmApiKeyEnv`
- `bankMission`
- `retainMission`

The user config path may remain `~/.hindsight/codex.json` for compatibility, but
new local memory data should live under `~/.hindsight-lite/`.

## Error Handling

Hooks should continue to degrade gracefully:

- missing memory home creates directories
- missing pages directory returns an empty list
- unreadable session files are skipped with debug logging
- malformed JSONL lines are skipped
- recall with no results emits no `additionalContext`
- page ID path traversal returns a structured error
- reflect always writes the request when possible, but still returns a packet if
  writing fails

No V1 path should require network access.

## Tests

Core tests:

- retain appends a valid `session_memory` JSONL event
- recall finds matches from session JSONL
- recall finds matches from page Markdown
- page list parses frontmatter and fallback titles
- page get rejects path traversal
- reflect returns a packet and writes `reflection_request`
- bank isolation prevents cross-bank recall

Codex adapter tests:

- `recall.py` emits `hookSpecificOutput.additionalContext`
- `recall.py` exits cleanly when no results exist
- `retain.py` strips injected memory blocks before writing
- `retain.py` parses Codex rollout JSONL via existing content helpers
- no Codex test requires API URL, daemon startup, or LLM key

## Migration And Deletion Sequence

Implement in this order:

1. Add the local Python core and tests.
2. Add CLI commands with `agent_knowledge_*` names.
3. Switch Codex `recall.py` to local recall.
4. Switch Codex `retain.py` to local retain.
5. Make `session_start.py` local-only.
6. Remove Codex runtime dependency on `client.py`, `daemon.py`, and `llm.py`.
7. After Codex V1 passes, plan the larger repo deletion pass for server, UI,
   generated clients, Docker/Helm, and non-target integrations.

Do not delete the full monorepo surface in the same change as the Codex V1
runtime switch. The deletion pass should be a separate implementation plan.
