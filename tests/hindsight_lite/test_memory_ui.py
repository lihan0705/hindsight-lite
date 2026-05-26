import json
from dataclasses import asdict
from pathlib import Path

from hindsight_lite.memory_ui import MemoryUiSnapshot, render_memory_ui, write_memory_ui
from hindsight_lite.models import ReflectionPacket, SessionMemoryEvent
from hindsight_lite.store import LocalMemoryStore


def test_render_memory_ui_includes_memory_tree_snapshot(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)

    html = render_memory_ui(store)

    assert "<!doctype html>" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert "project-rules" in html
    assert "session-1.jsonl" in html
    assert "reflect-1.json" in html
    assert "recall-cache.json" in html
    assert "Keep this fork local-first." in html


def test_render_memory_ui_escapes_script_closing_tags(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(page_id="script", title="Script", content="literal </script> in memory")

    html = render_memory_ui(store)

    assert "literal <\\/script> in memory" in html
    assert html.count("</script>") == 1


def test_write_memory_ui_uses_default_bank_output_path(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)

    output_path = write_memory_ui(store)

    assert output_path == tmp_path / "banks" / "codex" / "memory-tree.html"
    assert output_path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_memory_ui_snapshot_is_structured_for_json_payload() -> None:
    snapshot = MemoryUiSnapshot(bank_id="codex", bank_path="/tmp/bank", sections=[])

    assert json.loads(json.dumps(asdict(snapshot))) == {
        "bank_id": "codex",
        "bank_path": "/tmp/bank",
        "sections": [],
    }


def _store_with_memory(tmp_path: Path) -> LocalMemoryStore:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="project-rules",
        title="Project Rules",
        content="Keep this fork local-first.",
        tags=["rules"],
        metadata={"source": "test"},
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="event-1",
            timestamp="2026-05-24T12:00:00Z",
            bank_id="codex",
            session_id="session-1",
            source="codex",
            document_id="codex-session-1",
            content="Session memory for UI tree.",
        )
    )
    store.write_reflection_packet(
        ReflectionPacket(
            type="reflection_request",
            id="reflect-1",
            timestamp="2026-05-24T12:01:00Z",
            bank_id="codex",
            session_id="session-1",
            query="what should the UI show?",
            retrieved_context=[],
            task_context={"cwd": "/tmp/project"},
            reflection_prompt="Reflect on memory UI evidence.",
        )
    )
    (store.paths.index_dir / "recall-cache.json").write_text('{"ready":true}', encoding="utf-8")
    return store
