from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

MEMORYTREE_PROMPT_TEMPLATE = """---
description: Generate and open the hindsight-lite memory tree UI
argument-hint: [BANK=codex]
---

Generate the latest hindsight-lite memory tree UI for the Codex bank and open it locally.

Use `codex` as the bank unless the arguments include a different `BANK=` value.
Run:

```bash
PYTHONPATH={plugin_root}${{PYTHONPATH:+:$PYTHONPATH}} python3 -m hindsight_lite memory-ui --bank codex --open
```

If a different `BANK=` value was provided, replace `codex` with that bank name.
After running the command, report the generated `memory-tree.html` path.
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
