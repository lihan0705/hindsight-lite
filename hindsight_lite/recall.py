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
    body: str
    keywords: str
    timestamp: str | None
    metadata: dict[str, str]


def recall(store: LocalMemoryStore, query: str, max_results: int = 5) -> list[RecallResult]:
    query_terms = _tokenize(query)
    if not query_terms or max_results <= 0:
        return []

    query_phrase = _normalize_phrase(query)
    results = [_score_candidate(candidate, query_terms, query_phrase) for candidate in _iter_candidates(store)]
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
        body=page.content,
        keywords=_join_search_terms(page.title, page.tags, page.metadata),
        timestamp=page.updated_at,
        metadata=page.metadata,
    )


def _event_candidate(event: SessionMemoryEvent) -> SearchCandidate:
    return SearchCandidate(
        id=event.id,
        source="session",
        path=f"sessions/{event.session_id}.jsonl#{event.id}",
        title=event.document_id,
        body=event.content,
        keywords=_join_search_terms(event.document_id, event.tags, event.metadata, event.session_id),
        timestamp=event.timestamp,
        metadata=event.metadata,
    )


def _score_candidate(candidate: SearchCandidate, query_terms: set[str], query_phrase: str) -> RecallResult:
    body_terms = _tokenize(candidate.body)
    title_terms = _tokenize(candidate.title)
    keyword_terms = _tokenize(candidate.keywords)
    body_overlap = query_terms & body_terms
    title_overlap = query_terms & title_terms
    keyword_overlap = query_terms & keyword_terms
    score = float(len(body_overlap) + (len(title_overlap) * 2.0) + (len(keyword_overlap) * 1.5))
    if _contains_query_phrase(candidate, query_phrase):
        score += 2.0
    return RecallResult(
        id=candidate.id,
        source="page" if candidate.source == "page" else "session",
        path=candidate.path,
        score=score,
        title=candidate.title,
        excerpt=_excerpt(candidate.body, query_terms),
        timestamp=candidate.timestamp,
        metadata=candidate.metadata,
    )


def _format_result(result: RecallResult) -> str:
    label = result.id if result.source == "page" else result.title
    return f"- {result.excerpt} [{result.source}] ({label})"


def _tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def _join_search_terms(title: str, tags: list[str], metadata: dict[str, str], extra: str = "") -> str:
    metadata_terms = [item for pair in metadata.items() for item in pair]
    return " ".join([title, *tags, *metadata_terms, extra])


def _contains_query_phrase(candidate: SearchCandidate, query_phrase: str) -> bool:
    if " " not in query_phrase:
        return False
    searchable = _normalize_phrase(" ".join([candidate.title, candidate.keywords, candidate.body]))
    return query_phrase in searchable


def _normalize_phrase(text: str) -> str:
    return " ".join(match.group(0).lower() for match in _TOKEN_RE.finditer(text))


def _excerpt(text: str, query_terms: set[str], max_chars: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact

    lower_compact = compact.lower()
    positions = [lower_compact.find(term) for term in query_terms if lower_compact.find(term) >= 0]
    if not positions:
        return compact[: max_chars - 1].rstrip() + "..."

    start = max(0, min(positions) - 60)
    end = min(len(compact), start + max_chars)
    excerpt = compact[start:end].strip()
    if start > 0:
        excerpt = f"...{excerpt}"
    if end < len(compact):
        excerpt = f"{excerpt.rstrip()}..."
    return excerpt
