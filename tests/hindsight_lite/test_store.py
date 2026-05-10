from pathlib import Path

import pytest

from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.paths import MemoryPaths, unsafe_page_id
from hindsight_lite.store import LocalMemoryStore, PageNotFoundError, UnsafePageIdError


def test_memory_paths_create_bank_dirs(tmp_path: Path) -> None:
    paths = MemoryPaths(home=tmp_path, bank_id="codex::project")

    paths.ensure_bank_dirs()

    assert paths.bank_dir == tmp_path / "banks" / "codex__project"
    assert paths.sessions_dir.is_dir()
    assert paths.pages_dir.is_dir()
    assert paths.reflections_dir.is_dir()
    assert paths.index_dir.is_dir()


@pytest.mark.parametrize("page_id", ["../secret", "a/b", "", ".", "x\\y"])
def test_unsafe_page_id_rejects_traversal(page_id: str) -> None:
    assert unsafe_page_id(page_id)


def test_unsafe_page_id_allows_slug() -> None:
    assert not unsafe_page_id("project-rules_2026")


def test_store_appends_and_reads_session_events(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    event = SessionMemoryEvent(
        type="session_memory",
        id="evt-1",
        timestamp="2026-05-10T12:00:00Z",
        bank_id="codex",
        session_id="session-1",
        source="codex",
        document_id="doc-1",
        content="Use local Markdown pages as the source of truth.",
        tags=["architecture"],
        metadata={"repo": "hindsight-lite"},
    )

    store.append_session_event(event)

    events = store.read_session_events(session_id="session-1")
    assert events == [event]
    assert store.read_session_events(session_id="missing") == []


def test_store_writes_lists_and_gets_markdown_pages(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    page = store.write_page(
        page_id="project-rules",
        title="Project Rules",
        content="Keep this fork subtractive and Codex-first.",
        tags=["rules", "codex"],
        metadata={"scope": "repo:hindsight-lite"},
    )

    assert page.path.endswith("project-rules.md")
    assert page.title == "Project Rules"
    assert page.content == "Keep this fork subtractive and Codex-first."

    pages = store.list_pages()
    assert [listed.id for listed in pages] == ["project-rules"]
    assert pages[0].tags == ["rules", "codex"]
    assert pages[0].metadata == {"scope": "repo:hindsight-lite"}

    fetched = store.get_page("project-rules")
    assert fetched == page


def test_store_rejects_unsafe_page_ids(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    with pytest.raises(UnsafePageIdError):
        store.write_page(page_id="../secret", title="Secret", content="nope")

    with pytest.raises(UnsafePageIdError):
        store.get_page("../secret")


def test_store_raises_for_missing_page(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    with pytest.raises(PageNotFoundError):
        store.get_page("missing")
