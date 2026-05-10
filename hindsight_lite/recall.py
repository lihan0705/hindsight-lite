from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from hindsight_lite.models import KnowledgePage, RecallResult, SessionMemoryEvent
from hindsight_lite.store import LocalMemoryStore

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class SearchCandidate:
    id: str
    source: str
    path: str
    title: str
    text: str
    timestamp: str | None
    metadata: dict[str, str]


def recall(store: LocalMemoryStore, query: str, max_results: int = 5) -> list[RecallResult]:
    query_terms = _tokenize(query)
    if not query_terms or max_results <= 0:
        return []

    results = [_score_candidate(candidate, query_terms) for candidate in _iter_candidates(store)]
    ranked = sorted((result for result in results if result.score > 0), key=lambda result: (-result.score, result.id))
    return ranked[:max_results]


def format_recall_for_codex(
    results: list[RecallResult],
    preamble: str,
    current_time: str | None = None,
) -> str:
    timestamp = current_time or format_current_time()
    lines = ["<hindsight_lite_memories>", preamble, f"Current time - {timestamp}", ""]
    lines.extend(_format_result(result) for result in results)
    lines.append("</hindsight_lite_memories>")
    return "\n".join(lines)


def format_current_time() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M")


def _iter_candidates(store: LocalMemoryStore) -> list[SearchCandidate]:
    candidates = [_page_candidate(page) for page in store.list_pages()]
    candidates.extend(_event_candidate(event) for event in store.list_session_events())
    return candidates


def _page_candidate(page: KnowledgePage) -> SearchCandidate:
    return SearchCandidate(
        id=page.id,
        source="page",
        path=page.path,
        title=page.title,
        text=f"{page.content}\n{' '.join(page.tags)}",
        timestamp=page.updated_at,
        metadata=page.metadata,
    )


def _event_candidate(event: SessionMemoryEvent) -> SearchCandidate:
    return SearchCandidate(
        id=event.id,
        source="session",
        path=f"sessions/{event.session_id}.jsonl#{event.id}",
        title=event.document_id,
        text=event.content,
        timestamp=event.timestamp,
        metadata=event.metadata,
    )


def _score_candidate(candidate: SearchCandidate, query_terms: set[str]) -> RecallResult:
    candidate_terms = _tokenize(candidate.text)
    overlap = query_terms & candidate_terms
    score = float(len(overlap))
    return RecallResult(
        id=candidate.id,
        source="page" if candidate.source == "page" else "session",
        path=candidate.path,
        score=score,
        title=candidate.title,
        excerpt=_excerpt(candidate.text),
        timestamp=candidate.timestamp,
        metadata=candidate.metadata,
    )


def _format_result(result: RecallResult) -> str:
    label = result.id if result.source == "page" else result.title
    return f"- {result.excerpt} [{result.source}] ({label})"


def _tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def _excerpt(text: str, max_chars: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."
