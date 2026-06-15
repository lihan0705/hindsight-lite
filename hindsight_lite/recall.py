from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from hindsight_lite.index import RecallIndexDocument, bm25_scores, ensure_recall_index, tokenize_terms
from hindsight_lite.models import RecallResult
from hindsight_lite.store import LocalMemoryStore
from hindsight_lite.user_profile import expand_user_profile_query

DEFAULT_RECALL_EXCERPT_MAX_CHARS = 160


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
    candidates = _filter_temporal_bug_candidates(ensure_recall_index(store).documents, temporal_bug_query)
    scores = bm25_scores(candidates, query_terms)
    results = [
        _score_candidate(candidate, scores.get(candidate.path, 0.0), query_terms, query_phrase)
        for candidate in candidates
    ]
    ranked = sorted((result for result in results if result.score > 0), key=lambda result: (-result.score, result.id))
    deduped = _dedupe_ranked_results(ranked)
    profile_result = _authoritative_profile_result(deduped, candidates, query)
    if profile_result is not None:
        return [profile_result]
    return deduped[:max_results]


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


def _score_candidate(
    candidate: RecallIndexDocument,
    base_score: float,
    query_terms: set[str],
    query_phrase: str,
) -> RecallResult:
    score = base_score
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


def _dedupe_ranked_results(results: list[RecallResult]) -> list[RecallResult]:
    seen: set[str] = set()
    deduped: list[RecallResult] = []
    for result in results:
        key = _recall_dedupe_key(result)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _recall_dedupe_key(result: RecallResult) -> str:
    if result.source == "page":
        return f"page:{result.id}"
    document = result.title or result.path.split("#", 1)[0]
    return f"session:{document}"


def _authoritative_profile_result(
    results: list[RecallResult],
    candidates: list[RecallIndexDocument],
    query: str,
) -> RecallResult | None:
    labels = _profile_query_labels(query)
    if not labels:
        return None

    profile = next((result for result in results if result.source == "page" and result.id == "user-profile"), None)
    if profile is None:
        return None

    profile_candidate = next(
        (candidate for candidate in candidates if candidate.source == "page" and candidate.id == "user-profile"),
        None,
    )
    if profile_candidate is None:
        return None

    excerpt = _profile_excerpt(profile_candidate.body, labels)
    if not excerpt:
        return None

    # Promoted profile fields are the compact source of truth for personal facts.
    # Replaying source sessions here previously added duplicate and stale dialogue.
    return replace(profile, excerpt=excerpt)


def _profile_query_labels(query: str) -> set[str]:
    normalized = query.lower()
    labels: set[str] = set()
    if "我是谁" in query or "我的名字" in query or any(marker in normalized for marker in ("who am i", "my name")):
        labels.add("Name")
    if "编程语言" in query or "programming language" in normalized:
        labels.add("Preferred programming language")
    if (
        "喜欢喝" in query
        or "喝什么" in query
        or any(marker in normalized for marker in ("like to drink", "like drinking", "preferred drink"))
    ):
        labels.add("Preferred drink")
    if (
        "喜欢吃" in query
        or "吃什么" in query
        or any(marker in normalized for marker in ("like to eat", "like eating", "preferred food"))
    ):
        labels.add("Preference (food)")
    if not labels and (
        "我喜欢什么" in query
        or "我的偏好" in query
        or any(marker in normalized for marker in ("what do i like", "my preferences"))
    ):
        labels.add("Preference")
    return labels


def _profile_excerpt(content: str, labels: set[str]) -> str:
    profile_lines = [line.strip() for line in content.splitlines() if ":" in line]
    if "Preference" in labels:
        return " | ".join(
            line for line in profile_lines if line.startswith("Preferred ") or line.startswith("Preference (")
        )
    return " | ".join(line for line in profile_lines if any(line.startswith(f"{label}:") for label in labels))


def _trim_excerpt(excerpt: str, max_chars: int) -> str:
    budget = max(40, max_chars)
    compact = " ".join(excerpt.split())
    if len(compact) <= budget:
        return compact
    return compact[: budget - 3].rstrip() + "..."


def _tokenize(text: str) -> set[str]:
    return set(tokenize_terms(text))


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
    candidates: list[RecallIndexDocument],
    temporal_bug_query: TemporalBugQuery | None,
) -> list[RecallIndexDocument]:
    if temporal_bug_query is None:
        return candidates
    return [candidate for candidate in candidates if _matches_temporal_bug_query(candidate, temporal_bug_query)]


def _matches_temporal_bug_query(candidate: RecallIndexDocument, temporal_bug_query: TemporalBugQuery) -> bool:
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


def _contains_query_phrase(candidate: RecallIndexDocument, query_phrase: str) -> bool:
    if " " not in query_phrase:
        return False
    searchable = _normalize_phrase(" ".join([candidate.title, candidate.keywords, candidate.body]))
    return query_phrase in searchable


def _normalize_phrase(text: str) -> str:
    return " ".join(tokenize_terms(text))


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
