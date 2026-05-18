# hindsight-lite for OpenAI Codex CLI

Local memory for Codex CLI using hooks plus editable files under
`~/.hindsight-lite`. No Hindsight server, daemon, database, or cloud API is
required.

## How It Works

| Hook | Action |
|---|---|
| `SessionStart` | Initializes the local bank directory |
| `UserPromptSubmit` | Recalls relevant local memory and injects compact context |
| `PreToolUse` | Injects compact file-specific memory before file reads |
| `Stop` | Retains the conversation to session JSONL |

Memory layout:

```text
~/.hindsight-lite/
  banks/
    codex/
      sessions/<session-id>.jsonl
      pages/<page-id>.md
      reflections/<reflection-id>.json
      index/
```

## Requirements

- OpenAI Codex CLI with hook support
- Python 3.11+
- This repository available on the local machine

## Commands

Direct CLI checks:

```bash
python -m hindsight_lite knowledge list --bank codex
python -m hindsight_lite knowledge write --bank codex --id project-rules --file AGENTS.md
python -m hindsight_lite knowledge get --bank codex project-rules
python -m hindsight_lite recall --bank codex "project rules"
python -m hindsight_lite retain --bank codex --session-id test --content "Important session note"
python -m hindsight_lite reflect --bank codex --session-id test "what should we remember?"
```

## Configuration

Defaults live in `settings.json`. User overrides can be written to
`~/.hindsight/codex.json`.

| Key | Default | Description |
|---|---:|---|
| `bankId` | `codex` | Memory bank identifier |
| `autoRecall` | `true` | Inject memory before each prompt |
| `autoFileContext` | `true` | Inject compact memory before file-reading tools |
| `autoRetain` | `true` | Store conversations after each turn |
| `retainMode` | `full-session` | `full-session` or `chunked` |
| `retainEveryNTurns` | `10` | Retain every N turns |
| `recallMaxResults` | `5` | Maximum local recall results |
| `fileContextMaxResults` | `3` | Maximum file-context recall results |
| `recallContextTurns` | `1` | Prior transcript turns used for recall query |
| `recallMaxQueryChars` | `800` | Maximum recall query length |
| `dynamicBankId` | `false` | Separate banks by project/session/user fields |
| `dynamicBankGranularity` | `["agent", "project"]` | Fields for dynamic bank ID |
| `debug` | `false` | Log debug info to stderr |

Environment overrides:

```bash
export HINDSIGHT_LITE_HOME=~/.hindsight-lite
export HINDSIGHT_BANK_ID=codex
export HINDSIGHT_RECALL_MAX_RESULTS=5
export HINDSIGHT_FILE_CONTEXT_MAX_RESULTS=3
export HINDSIGHT_DEBUG=true
```

## Recall And Retain

Recall reads local pages and session events, ranks them with lightweight lexical
matching, and emits Codex `additionalContext` wrapped in
`<hindsight_lite_memories>`.

Retain strips injected memory blocks before writing session JSONL, preventing
memory feedback loops.

`codex_hook.py` is the installed hook dispatcher. It keeps the hook surface
small while routing `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and
`Stop` to the local Python handlers.
