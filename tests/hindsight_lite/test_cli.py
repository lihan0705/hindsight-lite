import json
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


def test_cli_writes_reflection_result_file(tmp_path: Path, capsys) -> None:
    result_file = tmp_path / "reflection-result.json"
    result_file.write_text(
        json.dumps(
            {
                "type": "reflection_result",
                "id": "result-1",
                "request_id": "reflect-1",
                "timestamp": "2026-05-30T10:00:00Z",
                "bank_id": "codex",
                "session_id": "session-1",
                "trajectory": {
                    "state": "Need evaluator output stored locally.",
                    "action": "Write a typed reflection result JSON.",
                    "observation": "The CLI validates the result before persisting it.",
                    "outcome": "The memory bank has a reusable eval artifact.",
                    "lesson": "Keep RL data artifacts explicit and inspectable.",
                },
                "durable_facts": ["Reflection results live in the reflections tree."],
                "reusable_procedures": ["Validate result files before writing them to memory."],
                "uncertain_items": [],
                "confidence": 0.88,
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--home",
                str(tmp_path / "home"),
                "reflection-result",
                "write",
                "--bank",
                "codex",
                "--file",
                str(result_file),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    saved_path = tmp_path / "home" / "banks" / "codex" / "reflections" / "result-1.json"
    assert str(saved_path) in output
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["type"] == "reflection_result"
    assert saved["trajectory"]["lesson"] == "Keep RL data artifacts explicit and inspectable."


def test_cli_exports_reflection_dataset(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    request_path = home / "banks" / "codex" / "reflections" / "reflect-1.json"
    result_path = home / "banks" / "codex" / "reflections" / "result-1.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(
        json.dumps(
            {
                "type": "reflection_request",
                "id": "reflect-1",
                "timestamp": "2026-05-30T10:00:00Z",
                "bank_id": "codex",
                "session_id": "session-1",
                "query": "How should this become eval data?",
                "retrieved_context": [],
                "task_context": {"repo": "hindsight-lite"},
                "reflection_prompt": "Return a reflection_result.",
            }
        ),
        encoding="utf-8",
    )
    result_path.write_text(
        json.dumps(
            {
                "type": "reflection_result",
                "id": "result-1",
                "request_id": "reflect-1",
                "timestamp": "2026-05-30T10:01:00Z",
                "bank_id": "codex",
                "session_id": "session-1",
                "trajectory": {
                    "state": "Need eval data.",
                    "action": "Export paired records.",
                    "observation": "JSONL keeps records scriptable.",
                    "outcome": "Later tooling can consume one row per result.",
                    "lesson": "Pair request and result before exporting.",
                },
                "durable_facts": [],
                "reusable_procedures": [],
                "uncertain_items": [],
                "confidence": 0.75,
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "reflection-dataset.jsonl"

    assert (
        main(
            [
                "--home",
                str(home),
                "reflection-dataset",
                "export",
                "--bank",
                "codex",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert f"{output_path}\t1" in output
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["request_id"] == "reflect-1"
    assert rows[0]["trajectory"]["lesson"] == "Pair request and result before exporting."


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


def test_cli_memory_ui_can_open_generated_file(tmp_path: Path, capsys, monkeypatch) -> None:
    opened: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> None:
        assert check is True
        opened.append(command)

    monkeypatch.setattr("hindsight_lite.cli.subprocess.run", fake_run)
    monkeypatch.setattr("hindsight_lite.cli.sys.platform", "darwin")

    assert main(["--home", str(tmp_path), "memory-ui", "--bank", "codex", "--open"]) == 0

    output = capsys.readouterr().out
    output_path = tmp_path / "banks" / "codex" / "memory-tree.html"
    assert str(output_path) in output
    assert opened == [["open", str(output_path.resolve())]]


def test_cli_memory_ui_uses_startfile_on_windows(tmp_path: Path, capsys, monkeypatch) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("hindsight_lite.cli.sys.platform", "win32")
    monkeypatch.setattr("hindsight_lite.cli.os.startfile", opened.append, raising=False)

    assert main(["--home", str(tmp_path), "memory-ui", "--bank", "codex", "--open"]) == 0

    output_path = tmp_path / "banks" / "codex" / "memory-tree.html"
    assert str(output_path) in capsys.readouterr().out
    assert opened == [output_path.resolve()]


def test_cli_installs_codex_memorytree_prompt(tmp_path: Path, capsys) -> None:
    prompt_dir = tmp_path / "prompts"

    assert main(["codex-prompts", "install", "--prompt-dir", str(prompt_dir)]) == 0

    output = capsys.readouterr().out
    prompt_path = prompt_dir / "memorytree.md"
    assert str(prompt_path) in output
    content = prompt_path.read_text(encoding="utf-8")
    assert "description: Generate and open the hindsight-lite memory tree UI" in content
    assert "PYTHONPATH=" in content
    assert "python3 -m hindsight_lite memory-ui --bank codex --open" in content
    assert "Windows `os.startfile`" in content
    assert "Start-Process" in content


def test_cli_refuses_to_overwrite_codex_prompt_without_force(tmp_path: Path, capsys) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "memorytree.md").write_text("custom", encoding="utf-8")

    assert main(["codex-prompts", "install", "--prompt-dir", str(prompt_dir)]) == 1

    assert "prompt already exists" in capsys.readouterr().err
    assert (prompt_dir / "memorytree.md").read_text(encoding="utf-8") == "custom"


def test_cli_seeds_demo_memory_and_generates_ui(tmp_path: Path, capsys) -> None:
    assert (
        main(
            [
                "--home",
                str(tmp_path),
                "demo-memory",
                "seed",
                "--bank",
                "codex",
                "--write-ui",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    output_path = tmp_path / "banks" / "codex" / "memory-tree.html"
    assert "page\tproject-direction" in output
    assert "session\tauth-redirect-loop" in output
    assert "reflection\tui-review-negative" in output
    assert f"ui\t{output_path}" in output
    html = output_path.read_text(encoding="utf-8")
    assert "Project Direction" in html
    assert "auth-redirect-loop.jsonl" in html
    assert "Trajectory Samples" in html
    assert "Error / Negative Candidates" in html
    assert "Task failed because the agent treated a stale draft as final." in html
