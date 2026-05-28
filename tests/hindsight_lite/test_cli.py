from pathlib import Path

from hindsight_lite.cli import main


def test_cli_writes_lists_and_gets_knowledge_pages(tmp_path: Path, capsys) -> None:
    source = tmp_path / "AGENTS.md"
    source.write_text("Keep changes subtractive.", encoding="utf-8")

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "knowledge",
                "write",
                "--bank",
                "codex",
                "--id",
                "project-rules",
                "--file",
                str(source),
            ]
        )
        == 0
    )
    assert main(["--home", str(tmp_path), "knowledge", "list", "--bank", "codex"]) == 0
    list_output = capsys.readouterr().out
    assert "project-rules" in list_output

    assert main(["--home", str(tmp_path), "knowledge", "get", "--bank", "codex", "project-rules"]) == 0
    get_output = capsys.readouterr().out
    assert "Keep changes subtractive." in get_output


def test_cli_retain_and_recall_session_memory(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "retain",
                "--bank",
                "codex",
                "--session-id",
                "session-1",
                "--content",
                "Codex should recall local memory without a server.",
            ]
        )
        == 0
    )

    assert main(["--home", str(tmp_path), "recall", "--bank", "codex", "local memory server"]) == 0
    output = capsys.readouterr().out
    assert "<hindsight_lite_memories>" in output
    assert "Codex should recall local memory without a server." in output


def test_cli_reflect_outputs_packet_json(tmp_path: Path, capsys) -> None:
    source = tmp_path / "memory.md"
    source.write_text("Reflection preserves state action observation outcome lesson.", encoding="utf-8")
    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "knowledge",
                "write",
                "--bank",
                "codex",
                "--id",
                "reflection",
                "--file",
                str(source),
            ]
        )
        == 0
    )

    assert (
        main(["--home", str(tmp_path), "reflect", "--bank", "codex", "--session-id", "session-1", "reflection lesson"])
        == 0
    )
    output = capsys.readouterr().out
    assert '"type": "reflection_request"' in output
    assert '"id": "reflection"' in output


def test_cli_agent_knowledge_aliases_match_v1_surface(tmp_path: Path, capsys) -> None:
    source = tmp_path / "AGENTS.md"
    source.write_text("Keep the Codex local memory path small.", encoding="utf-8")
    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "knowledge",
                "write",
                "--bank",
                "codex",
                "--id",
                "project-rules",
                "--file",
                str(source),
            ]
        )
        == 0
    )

    assert main(["--home", str(tmp_path), "agent_knowledge_list_pages", "--bank", "codex"]) == 0
    list_output = capsys.readouterr().out
    assert "project-rules" in list_output

    assert main(["--home", str(tmp_path), "agent_knowledge_get_page", "--bank", "codex", "project-rules"]) == 0
    page_output = capsys.readouterr().out
    assert "Keep the Codex local memory path small." in page_output

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "agent_knowledge_retain",
                "--bank",
                "codex",
                "--session-id",
                "session-1",
                "--content",
                "Agent knowledge aliases should preserve the existing CLI behavior.",
            ]
        )
        == 0
    )

    assert main(["--home", str(tmp_path), "agent_knowledge_recall", "--bank", "codex", "aliases behavior"]) == 0
    recall_output = capsys.readouterr().out
    assert "<hindsight_lite_memories>" in recall_output
    assert "Agent knowledge aliases should preserve the existing CLI behavior." in recall_output

    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "agent_knowledge_reflect",
                "--bank",
                "codex",
                "--session-id",
                "session-1",
                "aliases behavior",
            ]
        )
        == 0
    )
    reflect_output = capsys.readouterr().out
    assert '"type": "reflection_request"' in reflect_output


def test_cli_imports_codex_memory_files(tmp_path: Path, capsys) -> None:
    source_dir = tmp_path / "codex" / "memories"
    source_dir.mkdir(parents=True)
    (source_dir / "preference.md").write_text("# Preference\nKeep imported memory inspectable.", encoding="utf-8")

    assert (
        main(
            [
                "--home",
                str(tmp_path / "hindsight"),
                "codex-memory",
                "import",
                "--bank",
                "codex",
                "--source-dir",
                str(source_dir),
            ]
        )
        == 0
    )
    import_output = capsys.readouterr().out
    assert "codex-memory-preference" in import_output

    assert main(["--home", str(tmp_path / "hindsight"), "agent_knowledge_list_pages", "--bank", "codex"]) == 0
    list_output = capsys.readouterr().out
    assert "Preference" in list_output


def test_cli_generates_memory_ui(tmp_path: Path, capsys) -> None:
    source = tmp_path / "memory.md"
    source.write_text("Memory tree UI should make pages inspectable.", encoding="utf-8")
    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "knowledge",
                "write",
                "--bank",
                "codex",
                "--id",
                "ui",
                "--file",
                str(source),
            ]
        )
        == 0
    )

    assert main(["--home", str(tmp_path), "memory-ui", "--bank", "codex"]) == 0
    output = capsys.readouterr().out
    output_path = tmp_path / "banks" / "codex" / "memory-tree.html"
    assert str(output_path) in output
    assert "Memory tree UI should make pages inspectable." in output_path.read_text(encoding="utf-8")
