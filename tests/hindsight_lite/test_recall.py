from pathlib import Path

from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.recall import format_recall_for_codex, recall
from hindsight_lite.store import LocalMemoryStore


def test_recall_ranks_pages_and_session_events(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="project-rules",
        title="Project Rules",
        content="Use local Markdown pages as the source of truth for agent memory.",
        tags=["rules"],
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-1",
            timestamp="2026-05-10T12:00:00Z",
            bank_id="codex",
            session_id="session-1",
            source="codex",
            document_id="doc-1",
            content="Agent reflection packets should preserve state action observation outcome lesson.",
        )
    )

    results = recall(store, "agent memory markdown source", max_results=3)

    assert [result.id for result in results] == ["project-rules", "evt-1"]
    assert results[0].source == "page"
    assert results[0].score > results[1].score
    assert "Markdown pages" in results[0].excerpt


def test_recall_respects_max_results_and_ignores_zero_scores(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(page_id="matching", title="Matching", content="Codex stores compact local memory.")
    store.write_page(page_id="other", title="Other", content="This page is unrelated.")

    results = recall(store, "codex memory", max_results=1)

    assert [result.id for result in results] == ["matching"]


def test_format_recall_for_codex_keeps_context_compact(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="project-rules",
        title="Project Rules",
        content="Keep this fork subtractive and Codex-first.",
        metadata={"scope": "repo:hindsight-lite"},
    )

    context = format_recall_for_codex(
        recall(store, "subtractive codex", max_results=2),
        preamble="Relevant hindsight-lite memory:",
        current_time="2026-05-10 12:00",
    )

    assert context.startswith("<hindsight_lite_memories>")
    assert "Relevant hindsight-lite memory:" in context
    assert "Current time - 2026-05-10 12:00" in context
    assert "- Keep this fork subtractive and Codex-first. [page] (project-rules)" in context
    assert context.endswith("</hindsight_lite_memories>")
