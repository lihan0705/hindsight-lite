import json
from dataclasses import asdict
from pathlib import Path

from hindsight_lite.memory_ui import MemoryUiSnapshot, render_memory_ui, write_memory_ui
from hindsight_lite.models import ReflectionPacket, ReflectionResult, ReflectionTrajectory, SessionMemoryEvent
from hindsight_lite.store import LocalMemoryStore


def test_render_memory_ui_includes_memory_tree_snapshot(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)

    html = render_memory_ui(store)

    assert "<!doctype html>" in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert "project-rules" in html
    assert "session-1.jsonl" in html
    assert "reflect-1.json" in html
    assert "result-1.json" in html
    assert '"kind": "reflection-request"' in html
    assert '"kind": "reflection-result"' in html
    assert '"result_ids": "result-1"' in html
    assert '"request_id": "reflect-1"' in html
    assert '"confidence": "0.82"' in html
    assert '"lesson": "Keep request and result data linked for eval review."' in html
    assert "recall-cache.json" in html
    assert "Keep this fork local-first." in html
    assert "Download Markdown" in html
    assert "Reset changes" in html
    assert "Unsaved draft" in html


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
    snapshot = MemoryUiSnapshot(bank_id="codex", bank_path="/tmp/bank", sections=[], graph=None)

    assert json.loads(json.dumps(asdict(snapshot))) == {
        "bank_id": "codex",
        "bank_path": "/tmp/bank",
        "sections": [],
        "graph": None,
    }


def test_memory_ui_pages_include_downloadable_markdown_frontmatter(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)

    html = render_memory_ui(store)

    assert '"editable": true' in html
    assert '"download_name": "project-rules.md"' in html
    assert '"download_prefix": "---\\nid: \\"project-rules\\"' in html


def test_memory_ui_renders_session_jsonl_as_readable_events(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)

    html = render_memory_ui(store)

    assert '"kind": "session"' in html
    assert "Event 1: event-1" in html
    assert "timestamp: 2026-05-24T12:00:00Z" in html
    assert "session_id: session-1" in html
    assert "Session memory for UI tree." in html


def test_render_memory_ui_includes_trajectory_tree_graph(tmp_path: Path) -> None:
    store = _store_with_memory(tmp_path)
    store.write_reflection_result(
        ReflectionResult(
            type="reflection_result",
            id="result-error",
            request_id="reflect-1",
            timestamp="2026-05-24T12:03:00Z",
            bank_id="codex",
            session_id="session-1",
            trajectory=ReflectionTrajectory(
                state="Agent tried to finish a task with missing evidence.",
                action="Changed the implementation before checking the failing case.",
                observation="The task still failed and the output was wrong.",
                outcome="Task failed because the trajectory skipped validation.",
                lesson="Treat this as a negative RL trajectory sample.",
            ),
            durable_facts=[],
            reusable_procedures=[],
            uncertain_items=["Need reviewer confirmation before promotion."],
            confidence=0.31,
        )
    )

    html = render_memory_ui(store)

    assert '"label": "Trajectory Samples"' in html
    assert '"label": "Success"' in html
    assert '"label": "Error / Negative Candidates"' in html
    assert '"label": "Uncertain"' in html
    assert '"sample_status": "negative"' in html
    assert '"sample_status": "success"' in html
    assert '"parent_id": "trajectory-negative"' in html
    assert '"parent_id": "trajectory-success"' in html
    assert '"label": "outcome"' in html
    assert "Task failed because the trajectory skipped validation." in html
    assert "Trajectory Branch Map" in html
    assert "side branches /" in html
    assert "failed branch" in html
    assert "correct path" in html
    assert ".branch-row.branch-side" in html
    assert ".branch-row.branch-main" in html
    assert "Graph" in html


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
    store.write_reflection_result(
        ReflectionResult(
            type="reflection_result",
            id="result-1",
            request_id="reflect-1",
            timestamp="2026-05-24T12:02:00Z",
            bank_id="codex",
            session_id="session-1",
            trajectory=ReflectionTrajectory(
                state="Need to inspect reflection records.",
                action="Render semantic reflection metadata in the UI.",
                observation="Requests and results are both local JSON files.",
                outcome="Reviewers can connect result lessons to source requests.",
                lesson="Keep request and result data linked for eval review.",
            ),
            durable_facts=["Reflection results can be reviewed in the memory tree."],
            reusable_procedures=["Check confidence before promoting lessons."],
            uncertain_items=[],
            confidence=0.82,
        )
    )
    (store.paths.index_dir / "recall-cache.json").write_text('{"ready":true}', encoding="utf-8")
    return store
