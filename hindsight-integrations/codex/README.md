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

## Install The Plugin

The repository includes a Codex marketplace entry, plugin manifest, hooks, and
the `memorytree` skill. Install the marketplace and plugin from any shell:

```bash
codex plugin marketplace add lihan0705/hindsight-lite --ref main
codex plugin add hindsight-lite@hindsight-lite
```

Restart Codex and start a new thread after installation. Run `/plugins` to
confirm that `hindsight-lite` is installed and enabled. End one short session,
start another, and ask about a fact from the first session to verify retain and
recall. Use `$memorytree` or `/skills` -> **Memory Tree** to inspect the local
memory files.

Do not keep an older manual hindsight-lite registration in
`~/.codex/hooks.json` at the same time. The plugin already registers
SessionStart, UserPromptSubmit, PreToolUse, and Stop; registering both copies
makes each lifecycle event run twice and can duplicate hook output or errors.

To update the plugin, refresh the marketplace, remove the installed copy, add
it again, then restart Codex:

```bash
codex plugin marketplace upgrade hindsight-lite
codex plugin remove hindsight-lite@hindsight-lite
codex plugin add hindsight-lite@hindsight-lite
```

Each plugin release uses a new manifest version so Codex creates a fresh cache.
If `$memorytree` names a launcher path that does not exist, reinstall as above
instead of searching an older versioned cache directory.

## Quickstart

These developer smoke tests are optional; normal users should install the
plugin above. Run the commands from a repository checkout. They keep memory in
a temporary directory so you can verify the local runtime without touching
existing `~/.hindsight-lite` data:

```bash
export HINDSIGHT_LITE_HOME="$(mktemp -d)"
python3 -m hindsight_lite knowledge write --bank codex --id project-rules --file AGENTS.md
python3 -m hindsight_lite agent_knowledge_retain --bank codex --session-id smoke --content "Codex should remember this repo is local-first."
python3 -m hindsight_lite agent_knowledge_recall --bank codex "local-first project rules"
```

The recall command should print a `<hindsight_lite_memories>` block containing
the retained note or the `project-rules` page.

To smoke-test the Codex hook adapter directly, keep `PYTHONPATH` pointed at the
repository root and send a minimal `UserPromptSubmit` payload. The temporary
`HOME` keeps the hook state files under the same disposable directory:

```bash
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
printf '{"prompt":"local-first project rules","session_id":"smoke","cwd":"%s"}' "$PWD" \
  | HOME="$HINDSIGHT_LITE_HOME" python3 hindsight-integrations/codex/scripts/codex_hook.py UserPromptSubmit
```

When memories match, the hook prints Codex `hookSpecificOutput` JSON with
`additionalContext`. No output means recall found no matching local memory.

## Manual Hook Installation

This repository includes Codex plugin metadata in `.codex-plugin/plugin.json`
and a relocatable hook payload at `hooks/plugin-hooks.json`. The plugin hook
commands resolve `HINDSIGHT_LITE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_ROOT`,
`PLUGIN_ROOT`, or the current checkout, then set `PYTHONPATH` before calling
`codex_hook.py`. That keeps the same checkout usable after installation or on a
different machine without editing absolute script paths.

Use this section only when the marketplace installation is unavailable, and
remove these manual entries before later enabling the plugin. If your Codex
runtime accepts an external hook payload, use:

```text
hindsight-integrations/codex/hooks/plugin-hooks.json
```

The legacy manual hook file is still available for direct Codex hook config.
It uses the same hook events but requires replacing the `__SCRIPTS_DIR__`
placeholder with this checkout's absolute scripts path. Generate the concrete
hooks JSON from the repository root:

```bash
scripts_dir="$PWD/hindsight-integrations/codex/scripts"
sed "s#__SCRIPTS_DIR__#$scripts_dir#g" \
  hindsight-integrations/codex/hooks/hooks.json
```

Merge the generated `hooks` object into the Codex CLI hook configuration used by
your Codex installation. Start Codex from a shell that can import this checkout:

```bash
export PYTHONPATH="/path/to/hindsight-lite${PYTHONPATH:+:$PYTHONPATH}"
export HINDSIGHT_LITE_HOME="$HOME/.hindsight-lite"
codex
```

After a Codex session ends, check that retain wrote local session memory:

```bash
find "$HINDSIGHT_LITE_HOME/banks/codex/sessions" -name '*.jsonl'
```

The hooks also keep small operational state files under
`~/.hindsight/codex/state`. Memory data stays under `HINDSIGHT_LITE_HOME`.

## Commands

Direct CLI checks:

```bash
python3 -m hindsight_lite agent_knowledge_list_pages --bank codex
python3 -m hindsight_lite knowledge write --bank codex --id project-rules --file AGENTS.md
python3 -m hindsight_lite agent_knowledge_get_page --bank codex project-rules
python3 -m hindsight_lite agent_knowledge_recall --bank codex "project rules"
python3 -m hindsight_lite agent_knowledge_retain --bank codex --session-id test --content "Important session note"
python3 -m hindsight_lite agent_knowledge_reflect --bank codex --session-id test "what should we remember?"
python3 -m hindsight_lite agent_knowledge_import_codex_memory --bank codex --dry-run
python3 -m hindsight_lite memory-ui --bank codex --serve --open
```

Short commands such as `recall`, `retain`, `reflect`, and `knowledge list/get`
remain available for local debugging.

To bridge Codex-owned memory files into hindsight-lite, import them as editable
Markdown pages:

```bash
python3 -m hindsight_lite codex-memory import --bank codex
```

The importer reads `~/.codex/memories` by default, preserves source provenance
in page metadata, and never writes back to Codex-owned files. Pass
`--source-dir /path/to/memories` when testing with exported or fixture data.

`memory-ui --serve` starts a local editor. It uses `127.0.0.1` normally and the
WSL distro's private IPv4 when the Windows browser cannot rely on localhost
forwarding. This avoids WSL UNC paths and allows existing Markdown pages to be
saved back to `pages/*.md`. Sessions, reflections, and index files remain
read-only. Without `--serve`, the command writes a static `memory-tree.html`
file into the selected bank directory; browser edits can then be downloaded
but not written directly back to disk. When the Codex hooks are installed, the
Stop hook refreshes this static file after each successful retain.

The installed plugin includes a `memorytree` skill. Start a new Codex thread
and invoke `$memorytree`, or type `/skills` and select **Memory Tree**. The
skill starts the editor and keeps it running while you inspect or edit memory.
Under WSL, Windows PowerShell opens the distro IPv4 URL in the Windows browser.

Codex does not expose third-party top-level slash command registration, so
`/memorytree` cannot be added by this plugin. Use the bundled skill instead of
the deprecated custom prompt system.

## Configuration

Defaults live in `settings.json`. User overrides can be written to
`~/.hindsight/codex.json`.

| Key | Default | Description |
|---|---:|---|
| `bankId` | `codex` | Memory bank identifier |
| `autoRecall` | `true` | Inject memory before each prompt |
| `autoFileContext` | `true` | Inject compact memory before file-reading tools |
| `autoRetain` | `true` | Store conversations after each turn |
| `autoMemoryUi` | `true` | Refresh `memory-tree.html` after each successful retain |
| `autoReflect` | `true` | Write review-only trajectory candidates after corrected failures |
| `retainMode` | `full-session` | Replace the latest session snapshot, or append retained `chunked` windows |
| `retainEveryNTurns` | `1` | Retain every N turns |
| `recallMaxResults` | `5` | Maximum local recall results |
| `recallMaxExcerptChars` | `160` | Maximum prompt-recall excerpt characters per result |
| `fileContextMaxResults` | `3` | Maximum file-context recall results |
| `fileContextMaxExcerptChars` | `140` | Maximum file-context excerpt characters per result |
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
export HINDSIGHT_RECALL_MAX_EXCERPT_CHARS=160
export HINDSIGHT_FILE_CONTEXT_MAX_RESULTS=3
export HINDSIGHT_FILE_CONTEXT_MAX_EXCERPT_CHARS=140
export HINDSIGHT_AUTO_MEMORY_UI=true
export HINDSIGHT_AUTO_REFLECT=true
export HINDSIGHT_DEBUG=true
```

## Recall And Retain

Recall reads local pages and session events, ranks them with lightweight lexical
matching, and emits Codex `additionalContext` wrapped in
`<hindsight_lite_memories>`. The hook output uses compact excerpts with stable
source labels, so Codex gets a small memory index first instead of full session
transcripts.

Retain strips injected memory blocks before writing session JSONL, preventing
memory feedback loops.

`codex_hook.py` is the installed hook dispatcher. It keeps the hook surface
small while routing `SessionStart`, `UserPromptSubmit`, `PreToolUse`, and
`Stop` to the local Python handlers.
