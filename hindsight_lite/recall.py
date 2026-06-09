from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hindsight_lite.models import KnowledgePage, RecallResult, SessionMemoryEvent
from hindsight_lite.store import LocalMemoryStore
from hindsight_lite.user_profile import expand_user_profile_query

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
DEFAULT_RECALL_EXCERPT_MAX_CHARS = 160


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


@dataclass(frozen=True)
class TemporalBugQuery:
    days: int
    current_time: datetime

    @property
    def cutoff(self) -> datetime:
        return self.current_time - timedelta(days=self.days)


def recall(
    store: LocalMemoryStore,
    query: str,
    max_results: int = 5,
    current_time: datetime | None = None,
) -> list[RecallResult]:
    temporal_bug_query = _parse_temporal_bug_query(query, current_time)
    expanded_query = _expand_recall_query(query, temporal_bug_query)
    query_terms = _tokenize(expanded_query)
    if not query_terms or max_results <= 0:
        return []

    query_phrase = _normalize_phrase(expanded_query)
    candidates = _filter_temporal_bug_candidates(_iter_candidates(store), temporal_bug_query)
    results = [_score_candidate(candidate, query_terms, query_phrase) for candidate in candidates]
    ranked = sorted((result for result in results if result.score > 0), key=lambda result: (-result.score, result.id))
    return ranked[:max_results]


def format_recall_for_codex(
    results: list[RecallResult],
    preamble: str,
    current_time: str | None = None,
    excerpt_max_chars: int = DEFAULT_RECALL_EXCERPT_MAX_CHARS,
) -> str:
    timestamp = current_time or format_current_time()
    lines = ["<hindsight_lite_memories>", preamble, f"Current time - {timestamp}", ""]
    lines.extend(format_recall_result_line(result, excerpt_max_chars) for result in results)
    lines.append("</hindsight_lite_memories>")
    return "\n".join(lines)


def format_recall_result_line(
    result: RecallResult,
    excerpt_max_chars: int = DEFAULT_RECALL_EXCERPT_MAX_CHARS,
) -> str:
    label = result.id if result.source == "page" else result.title
    excerpt = _trim_excerpt(result.excerpt, excerpt_max_chars)
    return f"- {excerpt} [{result.source}] ({label})"


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


def _trim_excerpt(excerpt: str, max_chars: int) -> str:
    budget = max(40, max_chars)
    compact = " ".join(excerpt.split())
    if len(compact) <= budget:
        return compact
    return compact[: budget - 3].rstrip() + "..."


def _tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in _TOKEN_RE.finditer(text)}


def _join_search_terms(title: str, tags: list[str], metadata: dict[str, str], extra: str = "") -> str:
    metadata_terms = [item for pair in metadata.items() for item in pair]
    return " ".join([title, *tags, *metadata_terms, extra])


def _expand_recall_query(query: str, temporal_bug_query: TemporalBugQuery | None) -> str:
    expanded_query = expand_user_profile_query(query)
    if temporal_bug_query is None:
        return expanded_query
    return " ".join([expanded_query, "bug", "resolved", "fixed", "debugging"])


def _parse_temporal_bug_query(query: str, current_time: datetime | None) -> TemporalBugQuery | None:
    days = _parse_past_day_window(query)
    if days is None or not _asks_for_solved_bugs(query):
        return None
    return TemporalBugQuery(days=days, current_time=_coerce_current_time(current_time))


def _parse_past_day_window(query: str) -> int | None:
    patterns = [
        r"过去\s*(\d+)\s*天",
        r"last\s+(\d+)\s+days?",
        r"past\s+(\d+)\s+days?",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            days = int(match.group(1))
            return days if days > 0 else None
    return None


def _asks_for_solved_bugs(query: str) -> bool:
    normalized = query.lower()
    has_bug = "bug" in normalized or "bugs" in normalized
    has_resolution = any(term in normalized for term in ("resolved", "solved", "fixed", "fix")) or "解决" in query
    return has_bug and has_resolution


def _coerce_current_time(current_time: datetime | None) -> datetime:
    if current_time is None:
        return datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        return current_time.replace(tzinfo=timezone.utc)
    return current_time.astimezone(timezone.utc)


def _filter_temporal_bug_candidates(
    candidates: list[SearchCandidate],
    temporal_bug_query: TemporalBugQuery | None,
) -> list[SearchCandidate]:
    if temporal_bug_query is None:
        return candidates
    return [candidate for candidate in candidates if _matches_temporal_bug_query(candidate, temporal_bug_query)]


def _matches_temporal_bug_query(candidate: SearchCandidate, temporal_bug_query: TemporalBugQuery) -> bool:
    if candidate.source != "session":
        return False
    timestamp = _parse_timestamp(candidate.timestamp)
    if timestamp is None or timestamp < temporal_bug_query.cutoff or timestamp > temporal_bug_query.current_time:
        return False
    searchable = " ".join([candidate.title, candidate.keywords, candidate.body]).lower()
    return "bug" in searchable and any(term in searchable for term in ("resolved", "solved", "fixed", "fix"))


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    if timestamp is None:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _coerce_current_time(parsed)


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
