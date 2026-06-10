from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

MEMORYTREE_PROMPT_TEMPLATE = """---
description: Open the editable hindsight-lite memory tree UI
argument-hint: [BANK=codex]
---

Start the editable hindsight-lite memory tree UI for the Codex bank and open it locally.

Use `codex` as the bank unless the arguments include a different `BANK=` value.
Run this as a long-running command and keep it alive while the user edits memory:

```bash
PYTHONPATH={plugin_root}${{PYTHONPATH:+:$PYTHONPATH}} python3 -m hindsight_lite memory-ui --bank codex --serve --open
```

If a different `BANK=` value was provided, replace `codex` with that bank name.
The command prints a `http://127.0.0.1:<port>/` URL and opens it with the
platform-native launcher. Under WSL it asks Windows PowerShell to open the
localhost URL, avoiding `\\\\wsl.localhost` file paths. If opening the GUI
requires approval, request approval and retry. Report the localhost URL and
leave the server running until the user asks to stop it.
"""


@dataclass(frozen=True)
class CodexPromptInstallResult:
    installed_paths: list[Path]


def install_codex_prompts(prompt_dir: Path | None = None, force: bool = False) -> CodexPromptInstallResult:
    target_dir = prompt_dir or Path.home() / ".codex" / "prompts"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "memorytree.md"
    if target_path.exists() and not force:
        raise FileExistsError(target_path)

    target_path.write_text(_memorytree_prompt(), encoding="utf-8")
    return CodexPromptInstallResult(installed_paths=[target_path])


def _memorytree_prompt() -> str:
    plugin_root = shlex.quote(str(Path(__file__).resolve().parents[1]))
    return MEMORYTREE_PROMPT_TEMPLATE.format(plugin_root=plugin_root)
