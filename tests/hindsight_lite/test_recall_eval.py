from pathlib import Path

from hindsight_lite.recall_eval import RecallEvalExistsError, run_recall_eval, seed_recall_eval_memory
from hindsight_lite.store import LocalMemoryStore


def test_run_recall_eval_passes_representative_queries(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="recall-eval")

    result = run_recall_eval(store)

    assert result.ok
    assert result.passed == 5
    assert result.total == 5
    assert [case.case_id for case in result.cases] == [
        "drink-preference",
        "project-architecture",
        "auth-redirect-fix",
        "memory-tree-ui",
        "recent-bug-window",
    ]
    assert [case.top_id for case in result.cases] == [
        "user-profile",
        "eval-project-architecture",
        "eval-auth-redirect-loop-2",
        "eval-memory-tree-ui-1",
        "eval-recent-cache-bug",
    ]
    assert (store.paths.index_dir / "recall-index.json").exists()


def test_seed_recall_eval_memory_refuses_to_overwrite_existing_fixture(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="recall-eval")
    seed_recall_eval_memory(store)

    try:
        seed_recall_eval_memory(store)
    except RecallEvalExistsError as exc:
        assert "eval-project-architecture.md" in str(exc)
    else:
        raise AssertionError("expected existing recall eval fixture to be rejected")


def test_run_recall_eval_can_overwrite_fixture(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="recall-eval")
    seed_recall_eval_memory(store)
    store.write_page(page_id="eval-project-architecture", title="Broken", content="broken")

    result = run_recall_eval(store, overwrite=True)

    assert result.ok
    assert store.get_page("eval-project-architecture").title == "Project Architecture"
