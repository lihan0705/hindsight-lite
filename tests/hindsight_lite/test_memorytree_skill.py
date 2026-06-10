import json
import runpy
from pathlib import Path


def test_plugin_packages_memorytree_skill() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    manifest = json.loads((root_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill_path = root_dir / "skills" / "memorytree" / "SKILL.md"
    metadata_path = root_dir / "skills" / "memorytree" / "agents" / "openai.yaml"
    launcher_path = root_dir / "skills" / "memorytree" / "scripts" / "open_memorytree.py"

    skill = skill_path.read_text(encoding="utf-8")
    metadata = metadata_path.read_text(encoding="utf-8")
    launcher = runpy.run_path(str(launcher_path), run_name="memorytree_launcher")

    assert manifest["skills"] == "./skills/"
    assert "name: memorytree" in skill
    assert "scripts/open_memorytree.py --bank codex" in skill
    assert "memory-tree.html" in skill
    assert "Use $memorytree" in metadata
    assert launcher["plugin_root"]() == root_dir
    assert launcher["memory_ui_args"]("codex", 0, True) == [
        "memory-ui",
        "--bank",
        "codex",
        "--serve",
        "--port",
        "0",
        "--open",
    ]
