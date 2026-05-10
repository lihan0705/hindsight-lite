from pathlib import Path

import pytest

from hindsight_lite.paths import MemoryPaths, unsafe_page_id


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
