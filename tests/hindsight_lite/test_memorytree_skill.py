import json
from pathlib import Path


def test_plugin_packages_memorytree_skill() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    manifest = json.loads((root_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    skill_path = root_dir / "skills" / "memorytree" / "SKILL.md"
    metadata_path = root_dir / "skills" / "memorytree" / "agents" / "openai.yaml"

    skill = skill_path.read_text(encoding="utf-8")
    metadata = metadata_path.read_text(encoding="utf-8")

    assert manifest["skills"] == "./skills/"
    assert "name: memorytree" in skill
    assert "memory-ui --bank codex --serve --open" in skill
    assert "Use $memorytree" in metadata
