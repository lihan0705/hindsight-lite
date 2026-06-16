from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from hindsight_lite.index import rebuild_recall_index
from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.recall import recall
from hindsight_lite.store import LocalMemoryStore


class RecallEvalExistsError(FileExistsError):
    pass


@dataclass(frozen=True)
class RecallEvalCase:
    id: str
    query: str
    expected_source: Literal["page", "session"]
    expected_id: str
    current_time: datetime | None = None


@dataclass(frozen=True)
class RecallEvalCaseResult:
    case_id: str
    query: str
    expected_source: str
    expected_id: str
    top_source: str
    top_id: str
    top_title: str
    passed: bool
    returned_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RecallEvalRunResult:
    passed: int
    total: int
    cases: list[RecallEvalCaseResult]

    @property
    def ok(self) -> bool:
        return self.passed == self.total


def run_recall_eval(
    store: LocalMemoryStore,
    overwrite: bool = False,
    max_results: int = 3,
) -> RecallEvalRunResult:
    seed_recall_eval_memory(store, overwrite=overwrite)
    results = [_run_case(store, case, max_results=max_results) for case in recall_eval_cases()]
    return RecallEvalRunResult(
        passed=sum(1 for result in results if result.passed),
        total=len(results),
        cases=results,
    )


def seed_recall_eval_memory(store: LocalMemoryStore, overwrite: bool = False) -> None:
    existing = [path for path in _recall_eval_targets(store) if path.exists()]
    if existing and not overwrite:
        raise RecallEvalExistsError(", ".join(str(path) for path in existing))

    _write_eval_pages(store)
    _write_eval_sessions(store)
    rebuild_recall_index(store)


def recall_eval_cases() -> list[RecallEvalCase]:
    return [
        RecallEvalCase(
            id="drink-preference",
            query="我喜欢喝什么",
            expected_source="page",
            expected_id="user-profile",
        ),
        RecallEvalCase(
            id="project-architecture",
            query="How should this repo stay small and local-first?",
            expected_source="page",
            expected_id="eval-project-architecture",
        ),
        RecallEvalCase(
            id="auth-redirect-fix",
            query="How did we fix the auth redirect loop with stale cookies?",
            expected_source="session",
            expected_id="eval-auth-redirect-loop-2",
        ),
        RecallEvalCase(
            id="memory-tree-ui",
            query="What should the memory tree UI show for review?",
            expected_source="session",
            expected_id="eval-memory-tree-ui-1",
        ),
        RecallEvalCase(
            id="recent-bug-window",
            query="过去10天我解决了哪些bug",
            expected_source="session",
            expected_id="eval-recent-cache-bug",
            current_time=datetime(2026, 6, 16, tzinfo=timezone.utc),
        ),
    ]


def _run_case(store: LocalMemoryStore, case: RecallEvalCase, max_results: int) -> RecallEvalCaseResult:
    results = recall(store, case.query, max_results=max_results, current_time=case.current_time)
    top = results[0] if results else None
    top_source = top.source if top is not None else ""
    top_id = top.id if top is not None else ""
    return RecallEvalCaseResult(
        case_id=case.id,
        query=case.query,
        expected_source=case.expected_source,
        expected_id=case.expected_id,
        top_source=top_source,
        top_id=top_id,
        top_title=top.title if top is not None else "",
        passed=top_source == case.expected_source and top_id == case.expected_id,
        returned_ids=[result.id for result in results],
    )


def _recall_eval_targets(store: LocalMemoryStore) -> list[Path]:
    return [
        store.paths.pages_dir / "user-profile.md",
        store.paths.pages_dir / "eval-project-architecture.md",
        store.paths.sessions_dir / "eval-auth-redirect-loop.jsonl",
        store.paths.sessions_dir / "eval-memory-tree-ui.jsonl",
        store.paths.sessions_dir / "eval-bug-history.jsonl",
    ]


def _write_eval_pages(store: LocalMemoryStore) -> None:
    store.write_page(
        page_id="user-profile",
        title="User Profile",
        content="\n".join(
            [
                "# User Profile",
                "",
                "Preferred drink: 柠檬水、珍珠奶茶",
                "Preferred programming language: Python",
            ]
        ),
        tags=["user", "preference", "drink", "programming-language"],
        metadata={"source": "recall-eval"},
    )
    store.write_page(
        page_id="eval-project-architecture",
        title="Project Architecture",
        content="\n".join(
            [
                "hindsight-lite should remain local-first and dependency-light.",
                "Do not add a server, daemon, database, hosted control plane, or generated clients.",
                "Prefer file-based Markdown, JSONL, JSON, and a rebuildable local recall index.",
            ]
        ),
        tags=["architecture", "local-first", "subtractive"],
        metadata={"source": "recall-eval"},
    )


def _write_eval_sessions(store: LocalMemoryStore) -> None:
    _write_session_file(
        store,
        "eval-auth-redirect-loop",
        [
            SessionMemoryEvent(
                type="session_memory",
                id="eval-auth-redirect-loop-1",
                timestamp="2026-06-01T09:10:00Z",
                bank_id=store.paths.bank_id,
                session_id="eval-auth-redirect-loop",
                source="codex",
                document_id="codex-eval-auth-redirect-loop",
                content="Debugged an auth redirect loop where middleware ran before cookie refresh.",
                tags=["auth", "debugging", "redirect"],
                metadata={"source": "recall-eval"},
            ),
            SessionMemoryEvent(
                type="session_memory",
                id="eval-auth-redirect-loop-2",
                timestamp="2026-06-01T09:34:00Z",
                bank_id=store.paths.bank_id,
                session_id="eval-auth-redirect-loop",
                source="codex",
                document_id="codex-eval-auth-redirect-loop-fix",
                content=(
                    "Fix: refresh session cookies before redirect checks, then add a regression test for stale "
                    "cookie auth loops."
                ),
                tags=["auth", "fix", "stale-cookie"],
                metadata={"source": "recall-eval"},
            ),
        ],
    )
    _write_session_file(
        store,
        "eval-memory-tree-ui",
        [
            SessionMemoryEvent(
                type="session_memory",
                id="eval-memory-tree-ui-1",
                timestamp="2026-06-04T14:05:00Z",
                bank_id=store.paths.bank_id,
                session_id="eval-memory-tree-ui",
                source="codex",
                document_id="codex-eval-memory-tree-ui",
                content=(
                    "User wanted a tree-like memory UI that shows pages, sessions, reflections, and index status "
                    "together for review."
                ),
                tags=["memory-tree", "ui", "review"],
                metadata={"source": "recall-eval"},
            )
        ],
    )
    _write_session_file(
        store,
        "eval-bug-history",
        [
            SessionMemoryEvent(
                type="session_memory",
                id="eval-recent-cache-bug",
                timestamp="2026-06-12T11:00:00Z",
                bank_id=store.paths.bank_id,
                session_id="eval-bug-history",
                source="codex",
                document_id="codex-eval-recent-cache-bug",
                content="Resolved recent index cache bug by rebuilding recall-index.json after direct memory edits.",
                tags=["bug", "resolved", "index"],
                metadata={"source": "recall-eval"},
            ),
            SessionMemoryEvent(
                type="session_memory",
                id="eval-old-render-bug",
                timestamp="2026-05-01T11:00:00Z",
                bank_id=store.paths.bank_id,
                session_id="eval-bug-history",
                source="codex",
                document_id="codex-eval-old-render-bug",
                content="Resolved old graph rendering bug by trimming oversized session JSONL previews.",
                tags=["bug", "resolved", "ui"],
                metadata={"source": "recall-eval"},
            ),
        ],
    )


def _write_session_file(store: LocalMemoryStore, session_id: str, events: list[SessionMemoryEvent]) -> None:
    session_path = store.paths.sessions_dir / f"{session_id}.jsonl"
    lines = [json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) for event in events]
    session_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
