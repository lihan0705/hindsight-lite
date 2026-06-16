from pathlib import Path

from hindsight_lite.demo_memory import DemoMemoryExistsError, seed_demo_memory
from hindsight_lite.store import LocalMemoryStore


def test_seed_demo_memory_writes_representative_tree_data(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    result = seed_demo_memory(store)

    assert result.pages == ["project-direction", "coding-preferences"]
    assert result.sessions == ["auth-redirect-loop", "memory-ui-feedback"]
    assert result.reflections == ["ui-review-reflection", "ui-review-success", "ui-review-negative"]
    assert result.index_files == ["recall-index.json"]
    assert "local-first memory runtime" in store.get_page("project-direction").content
    assert "auth redirect loop" in (store.paths.sessions_dir / "auth-redirect-loop.jsonl").read_text(encoding="utf-8")
    assert "reflection_request" in (store.paths.reflections_dir / "ui-review-reflection.json").read_text(
        encoding="utf-8"
    )
    success = (store.paths.reflections_dir / "ui-review-success.json").read_text(encoding="utf-8")
    negative = (store.paths.reflections_dir / "ui-review-negative.json").read_text(encoding="utf-8")
    assert "reflection_result" in success
    assert "Keep the graph deterministic and tied to source files." in success
    assert "reflection_result" in negative
    assert "Task failed because the agent treated a stale draft as final." in negative
    assert '"confidence": 0.28' in negative


def test_seed_demo_memory_refuses_to_overwrite_without_flag(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    seed_demo_memory(store)

    try:
        seed_demo_memory(store)
    except DemoMemoryExistsError as exc:
        assert "project-direction.md" in str(exc)
    else:
        raise AssertionError("expected DemoMemoryExistsError")


def test_seed_demo_memory_can_overwrite_known_demo_files(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    seed_demo_memory(store)
    (store.paths.pages_dir / "project-direction.md").write_text("stale", encoding="utf-8")

    seed_demo_memory(store, overwrite=True)

    assert "local-first memory runtime" in store.get_page("project-direction").content
