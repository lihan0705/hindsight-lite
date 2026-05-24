from pathlib import Path

from hindsight_lite.codex_memory import import_codex_memories
from hindsight_lite.store import LocalMemoryStore


def test_import_codex_memories_writes_pages_with_source_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "codex" / "memories"
    source_dir.mkdir(parents=True)
    (source_dir / "project.md").write_text("# Project Memory\nPrefer small local memory files.", encoding="utf-8")
    (source_dir / "facts.json").write_text('{"preference":"keep memory transparent"}', encoding="utf-8")
    (source_dir / "ignored.bin").write_text("not imported", encoding="utf-8")

    store = LocalMemoryStore(home=tmp_path / "hindsight", bank_id="codex")
    result = import_codex_memories(store=store, source_dir=source_dir)

    assert len(result.imported_pages) == 2
    pages = store.list_pages()
    assert [page.title for page in pages] == ["Facts", "Project Memory"]
    assert pages[0].tags == ["codex-memory"]
    assert pages[0].metadata["source"] == "codex-memory"
    assert "keep memory transparent" in pages[0].content
    assert "Prefer small local memory files." in pages[1].content


def test_import_codex_memories_dry_run_does_not_write_pages(tmp_path: Path) -> None:
    source_dir = tmp_path / "memories"
    source_dir.mkdir()
    (source_dir / "memory.txt").write_text("Dry run should report this file.", encoding="utf-8")

    store = LocalMemoryStore(home=tmp_path / "hindsight", bank_id="codex")
    result = import_codex_memories(store=store, source_dir=source_dir, dry_run=True)

    assert len(result.imported_pages) == 1
    assert store.list_pages() == []


def test_import_codex_memories_reports_missing_source_dir(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path / "hindsight", bank_id="codex")
    result = import_codex_memories(store=store, source_dir=tmp_path / "missing")

    assert result.imported_pages == []
    assert result.skipped_files == [str(tmp_path / "missing")]
