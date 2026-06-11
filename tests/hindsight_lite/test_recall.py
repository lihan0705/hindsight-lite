from datetime import datetime, timezone
from pathlib import Path

from hindsight_lite.models import RecallResult, SessionMemoryEvent
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


def test_recall_uses_titles_tags_and_session_metadata(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="project-direction",
        title="Project Direction",
        content="Keep runtime behavior local-first and easy to inspect.",
        tags=["architecture"],
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-auth",
            timestamp="2026-05-20T09:15:00Z",
            bank_id="codex",
            session_id="auth-redirect-loop",
            source="codex",
            document_id="codex-auth-redirect-loop",
            content="Middleware ran before cookie refresh.",
            tags=["debugging", "auth"],
            metadata={"area": "redirect"},
        )
    )

    results = recall(store, "auth redirect debugging", max_results=3)

    assert [result.id for result in results] == ["evt-auth"]
    assert results[0].score > 0


def test_recall_excerpt_focuses_near_query_terms(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    prefix = " ".join(["background"] * 80)
    store.write_page(
        page_id="late-match",
        title="Late Match",
        content=f"{prefix} The useful lesson is to refresh cookies before redirect checks.",
    )

    result = recall(store, "refresh cookies redirect", max_results=1)[0]

    assert result.id == "late-match"
    assert "refresh cookies before redirect checks" in result.excerpt
    assert not result.excerpt.startswith("background background")


def test_recall_filters_solved_bugs_by_past_day_window(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-recent-bug",
            timestamp="2026-05-31T12:00:00Z",
            bank_id="codex",
            session_id="recent-auth",
            source="codex",
            document_id="codex-recent-auth",
            content="Resolved auth redirect loop bug by refreshing session state before redirect checks.",
            tags=["debugging"],
        )
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-old-bug",
            timestamp="2026-05-10T12:00:00Z",
            bank_id="codex",
            session_id="old-cache",
            source="codex",
            document_id="codex-old-cache",
            content="Resolved stale cache bug by clearing the generated index.",
            tags=["debugging"],
        )
    )

    results = recall(
        store,
        "过去10天我解决了哪些bug",
        max_results=5,
        current_time=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )

    assert [result.id for result in results] == ["evt-recent-bug"]
    assert "auth redirect loop bug" in results[0].excerpt


def test_recall_dedupes_multiple_events_from_same_session_document(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    for index in range(3):
        store.append_session_event(
            SessionMemoryEvent(
                type="session_memory",
                id=f"evt-drink-{index}",
                timestamp=f"2026-05-31T12:0{index}:00Z",
                bank_id="codex",
                session_id="drink-session",
                source="codex",
                document_id="codex-drink-session",
                content=f"User preference: likes lemon water. duplicate event {index}",
                tags=["preference", "drink"],
            )
        )

    results = recall(store, "lemon water drink preference", max_results=5)

    assert len(results) == 1
    assert results[0].title == "codex-drink-session"


def test_recall_uses_only_compact_profile_field_for_personal_preference_query(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="user-profile",
        title="User Profile",
        content=(
            "# User Profile\n\n"
            "Name: jack\n"
            "Preferred programming language: rust\n"
            "Preferred drink: 柠檬水、奶茶\n"
            "Preference (food): 火锅"
        ),
        tags=["user", "preference", "drink", "food"],
    )
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-drink-history",
            timestamp="2026-06-10T12:00:00Z",
            bank_id="codex",
            session_id="drink-history",
            source="codex",
            document_id="codex-drink-history",
            content='[{"role":"user","content":"我喜欢喝什么"},{"role":"assistant","content":"不知道"}]',
            tags=["user", "preference", "drink"],
        )
    )

    results = recall(store, "我喜欢喝什么", max_results=5)

    assert len(results) == 1
    assert results[0].id == "user-profile"
    assert results[0].excerpt == "Preferred drink: 柠檬水、奶茶"


def test_recall_profile_query_falls_back_to_sessions_without_profile_page(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_event(
        SessionMemoryEvent(
            type="session_memory",
            id="evt-drink-history",
            timestamp="2026-06-10T12:00:00Z",
            bank_id="codex",
            session_id="drink-history",
            source="codex",
            document_id="codex-drink-history",
            content="User preference drink beverage: likes lemon water.",
            tags=["user", "preference", "drink"],
        )
    )

    results = recall(store, "我喜欢喝什么", max_results=5)

    assert [result.id for result in results] == ["evt-drink-history"]


def test_recall_compacts_multiple_requested_profile_fields(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="user-profile",
        title="User Profile",
        content=("# User Profile\n\nName: jack\nPreferred programming language: rust\nPreferred drink: 柠檬水"),
        tags=["user", "identity", "preference", "programming-language", "drink"],
    )

    results = recall(store, "我是谁 我喜欢什么编程语言 我喜欢喝什么", max_results=5)

    assert results[0].excerpt == "Name: jack | Preferred programming language: rust | Preferred drink: 柠檬水"


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


def test_format_recall_for_codex_trims_excerpts_to_injection_budget() -> None:
    result = RecallResult(
        id="long-session",
        source="session",
        path="sessions/session-1.jsonl#long-session",
        score=5.0,
        title="session-1",
        excerpt=" ".join(["token"] * 40),
    )

    context = format_recall_for_codex(
        [result],
        preamble="Relevant hindsight-lite memory:",
        current_time="2026-05-10 12:00",
        excerpt_max_chars=48,
    )

    memory_line = next(line for line in context.splitlines() if line.startswith("- "))
    assert memory_line.endswith("[session] (session-1)")
    assert "..." in memory_line
    assert len(memory_line.split(" [session] ")[0]) <= 50
