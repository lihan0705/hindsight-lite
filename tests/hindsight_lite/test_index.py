import json
from pathlib import Path

from hindsight_lite.index import (
    ensure_recall_index,
    rebuild_recall_index,
    recall_index_path,
    recall_index_status,
)
from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.recall import recall
from hindsight_lite.store import LocalMemoryStore


def test_rebuild_recall_index_writes_typed_page_and_session_documents(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)

    index = rebuild_recall_index(store)

    assert [document.id for document in index.documents] == ["project-rules", "event-1"]
    assert index.documents[0].source == "page"
    assert index.documents[0].term_frequencies["codex"] > 0
    assert recall_index_path(store).exists()
    status = recall_index_status(store)
    assert status.state == "ready"
    assert status.document_count == 2
    assert status.source_file_count == 2


def test_recall_uses_ready_index_without_rescanning_memory_files(tmp_path: Path, monkeypatch) -> None:
    store = _store_with_page_and_session(tmp_path)
    rebuild_recall_index(store)

    monkeypatch.setattr(store, "list_pages", lambda: (_ for _ in ()).throw(AssertionError("rescanned pages")))
    monkeypatch.setattr(
        store,
        "list_session_events",
        lambda: (_ for _ in ()).throw(AssertionError("rescanned sessions")),
    )

    results = recall(store, "codex local memory")

    assert results[0].id == "project-rules"


def test_bm25_scores_page_and_session_with_same_id_independently(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(page_id="shared", title="Shared", content="Page contains architecture rules.")
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="shared",
            timestamp="2026-06-15T08:00:00Z",
            bank_id="codex",
            session_id="session-1",
            source="codex",
            document_id="codex-session-1",
            content="Session contains debugging evidence.",
        )
    )

    assert recall(store, "architecture")[0].source == "page"
    assert recall(store, "debugging")[0].source == "session"


def test_index_status_detects_direct_source_file_edits_and_rebuilds(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)
    rebuild_recall_index(store)
    page_path = store.paths.pages_dir / "project-rules.md"
    page_path.write_text(page_path.read_text(encoding="utf-8") + "\nNew index evidence.\n", encoding="utf-8")

    assert recall_index_status(store).state == "stale"

    index = ensure_recall_index(store)

    assert recall_index_status(store).state == "ready"
    assert "New index evidence." in index.documents[0].body


def test_store_writes_incrementally_update_existing_index(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)
    rebuild_recall_index(store)

    store.write_page(page_id="new-page", title="New Page", content="Fresh content.")

    assert recall_index_status(store).state == "ready"
    index = ensure_recall_index(store)
    assert [document.id for document in index.documents] == ["new-page", "project-rules", "event-1"]


def test_store_write_invalidates_index_when_another_source_was_edited_directly(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)
    rebuild_recall_index(store)
    session_path = store.paths.sessions_dir / "session-1.jsonl"
    session_path.write_text(session_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    store.write_page(page_id="new-page", title="New Page", content="Fresh content.")

    assert recall_index_status(store).state == "missing"


def test_replace_session_event_updates_index_without_duplicate_snapshots(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)
    rebuild_recall_index(store)
    latest = SessionMemoryEvent(
        type="session_memory",
        id="event-2",
        timestamp="2026-06-15T08:05:00Z",
        bank_id="codex",
        session_id="session-1",
        source="codex",
        document_id="codex-session-1",
        content="Latest full session snapshot.",
    )

    store.replace_session_event(latest)

    session_documents = [document for document in ensure_recall_index(store).documents if document.source == "session"]
    assert [document.id for document in session_documents] == ["event-2"]


def test_ensure_recall_index_replaces_invalid_json(tmp_path: Path) -> None:
    store = _store_with_page_and_session(tmp_path)
    recall_index_path(store).write_text("{invalid", encoding="utf-8")

    index = ensure_recall_index(store)

    assert len(index.documents) == 2
    parsed = json.loads(recall_index_path(store).read_text(encoding="utf-8"))
    assert parsed["version"] == "1"
    assert parsed["bank_path"] == str(store.paths.bank_dir)


def _store_with_page_and_session(tmp_path: Path) -> LocalMemoryStore:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="project-rules",
        title="Project Rules",
        content="Codex should use compact local memory.",
        tags=["architecture"],
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="event-1",
            timestamp="2026-06-15T08:00:00Z",
            bank_id="codex",
            session_id="session-1",
            source="codex",
            document_id="codex-session-1",
            content="The session discussed a separate reflection graph.",
        )
    )
    return store
