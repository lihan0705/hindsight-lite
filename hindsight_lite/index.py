from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal

from hindsight_lite.models import KnowledgePage, SessionMemoryEvent

if TYPE_CHECKING:
    from hindsight_lite.store import LocalMemoryStore

_INDEX_VERSION = "1"
_INDEX_FILE_NAME = "recall-index.json"
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class SourceFileState:
    path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class RecallIndexDocument:
    id: str
    source: Literal["page", "session"]
    path: str
    title: str
    body: str
    keywords: str
    timestamp: str | None
    metadata: dict[str, str] = field(default_factory=dict)
    term_frequencies: dict[str, float] = field(default_factory=dict)
    token_count: float = 0.0


@dataclass(frozen=True)
class RecallIndex:
    version: str
    bank_path: str
    generated_at: str
    source_files: list[SourceFileState]
    documents: list[RecallIndexDocument]


@dataclass(frozen=True)
class RecallIndexStatus:
    state: Literal["ready", "missing", "stale", "invalid"]
    path: str
    document_count: int
    source_file_count: int
    generated_at: str | None = None


def recall_index_path(store: LocalMemoryStore) -> Path:
    return store.paths.index_dir / _INDEX_FILE_NAME


def invalidate_recall_index(store: LocalMemoryStore) -> None:
    recall_index_path(store).unlink(missing_ok=True)


def update_page_in_recall_index(store: LocalMemoryStore, page: KnowledgePage) -> None:
    path = recall_index_path(store)
    index = _read_recall_index(path)
    if index is None:
        return
    source_path = str(Path(page.path).relative_to(store.paths.bank_dir))
    if not _can_incrementally_update(store, index, {source_path}):
        invalidate_recall_index(store)
        return
    documents = [
        document for document in index.documents if not (document.source == "page" and document.path == page.path)
    ]
    documents.append(_page_document(page))
    _write_updated_index(store, documents)


def append_session_event_to_recall_index(store: LocalMemoryStore, event: SessionMemoryEvent) -> None:
    path = recall_index_path(store)
    index = _read_recall_index(path)
    if index is None:
        return
    source_path = f"sessions/{event.session_id}.jsonl"
    if not _can_incrementally_update(store, index, {source_path}):
        invalidate_recall_index(store)
        return
    documents = [*index.documents, _session_document(event)]
    _write_updated_index(store, documents)


def replace_session_event_in_recall_index(store: LocalMemoryStore, event: SessionMemoryEvent) -> None:
    path = recall_index_path(store)
    index = _read_recall_index(path)
    if index is None:
        return
    source_path = f"sessions/{event.session_id}.jsonl"
    if not _can_incrementally_update(store, index, {source_path}):
        invalidate_recall_index(store)
        return
    path_prefix = f"{source_path}#"
    documents = [
        document
        for document in index.documents
        if not (document.source == "session" and document.path.startswith(path_prefix))
    ]
    documents.append(_session_document(event))
    _write_updated_index(store, documents)


def ensure_recall_index(store: LocalMemoryStore) -> RecallIndex:
    index = _read_recall_index(recall_index_path(store))
    if (
        index is not None
        and index.bank_path == str(store.paths.bank_dir)
        and index.source_files == _source_file_states(store)
    ):
        return index
    return rebuild_recall_index(store)


def rebuild_recall_index(store: LocalMemoryStore) -> RecallIndex:
    documents = [_page_document(page) for page in store.list_pages()]
    documents.extend(_session_document(event) for event in store.list_session_events())
    index = RecallIndex(
        version=_INDEX_VERSION,
        bank_path=str(store.paths.bank_dir),
        generated_at=_utc_now(),
        source_files=_source_file_states(store),
        documents=documents,
    )
    _write_recall_index(recall_index_path(store), index)
    return index


def recall_index_status(store: LocalMemoryStore) -> RecallIndexStatus:
    path = recall_index_path(store)
    source_files = _source_file_states(store)
    if not path.exists():
        return RecallIndexStatus(
            state="missing",
            path=str(path),
            document_count=0,
            source_file_count=len(source_files),
        )

    index = _read_recall_index(path)
    if index is None:
        return RecallIndexStatus(
            state="invalid",
            path=str(path),
            document_count=0,
            source_file_count=len(source_files),
        )

    state: Literal["ready", "stale"] = (
        "ready" if index.bank_path == str(store.paths.bank_dir) and index.source_files == source_files else "stale"
    )
    return RecallIndexStatus(
        state=state,
        path=str(path),
        document_count=len(index.documents),
        source_file_count=len(source_files),
        generated_at=index.generated_at,
    )


def tokenize_terms(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def bm25_scores(documents: list[RecallIndexDocument], query_terms: set[str]) -> dict[str, float]:
    if not documents or not query_terms:
        return {}

    average_length = sum(document.token_count for document in documents) / len(documents)
    document_frequency = {
        term: sum(1 for document in documents if document.term_frequencies.get(term, 0.0) > 0) for term in query_terms
    }
    scores: dict[str, float] = {}
    for document in documents:
        score = 0.0
        for term in query_terms:
            frequency = document.term_frequencies.get(term, 0.0)
            if frequency <= 0:
                continue
            inverse_frequency = math.log(
                1 + (len(documents) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            normalization = frequency + 1.2 * (1 - 0.75 + 0.75 * (document.token_count / max(average_length, 1.0)))
            score += inverse_frequency * (frequency * 2.2) / normalization
        scores[document.path] = score
    return scores


def _page_document(page: KnowledgePage) -> RecallIndexDocument:
    keywords = _join_search_terms(page.title, page.tags, page.metadata)
    return _index_document(
        id=page.id,
        source="page",
        path=page.path,
        title=page.title,
        body=page.content,
        keywords=keywords,
        timestamp=page.updated_at,
        metadata=page.metadata,
    )


def _session_document(event: SessionMemoryEvent) -> RecallIndexDocument:
    keywords = _join_search_terms(event.document_id, event.tags, event.metadata, event.session_id)
    return _index_document(
        id=event.id,
        source="session",
        path=f"sessions/{event.session_id}.jsonl#{event.id}",
        title=event.document_id,
        body=event.content,
        keywords=keywords,
        timestamp=event.timestamp,
        metadata=event.metadata,
    )


def _index_document(
    *,
    id: str,
    source: Literal["page", "session"],
    path: str,
    title: str,
    body: str,
    keywords: str,
    timestamp: str | None,
    metadata: dict[str, str],
) -> RecallIndexDocument:
    body_terms = tokenize_terms(body)
    title_terms = tokenize_terms(title)
    keyword_terms = tokenize_terms(keywords)
    frequencies: Counter[str] = Counter(body_terms)
    for term, count in Counter(title_terms).items():
        frequencies[term] += count * 2.0
    for term, count in Counter(keyword_terms).items():
        frequencies[term] += count * 1.5
    return RecallIndexDocument(
        id=id,
        source=source,
        path=path,
        title=title,
        body=body,
        keywords=keywords,
        timestamp=timestamp,
        metadata=metadata,
        term_frequencies=dict(frequencies),
        token_count=len(body_terms) + (len(title_terms) * 2.0) + (len(keyword_terms) * 1.5),
    )


def _source_file_states(store: LocalMemoryStore) -> list[SourceFileState]:
    paths = [
        *sorted(store.paths.pages_dir.glob("*.md")),
        *sorted(store.paths.sessions_dir.glob("*.jsonl")),
    ]
    return [_source_file_state(store.paths.bank_dir, path) for path in paths]


def _source_file_state(bank_dir: Path, path: Path) -> SourceFileState:
    stat = path.stat()
    return SourceFileState(
        path=str(path.relative_to(bank_dir)),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _can_incrementally_update(
    store: LocalMemoryStore,
    index: RecallIndex,
    changed_paths: set[str],
) -> bool:
    if index.bank_path != str(store.paths.bank_dir):
        return False
    indexed_states = [state for state in index.source_files if state.path not in changed_paths]
    current_states = [state for state in _source_file_states(store) if state.path not in changed_paths]
    return indexed_states == current_states


def _write_updated_index(store: LocalMemoryStore, documents: list[RecallIndexDocument]) -> None:
    index = RecallIndex(
        version=_INDEX_VERSION,
        bank_path=str(store.paths.bank_dir),
        generated_at=_utc_now(),
        source_files=_source_file_states(store),
        documents=sorted(documents, key=lambda document: (document.source, document.path, document.id)),
    )
    _write_recall_index(recall_index_path(store), index)


def _join_search_terms(title: str, tags: list[str], metadata: dict[str, str], extra: str = "") -> str:
    metadata_terms = [item for pair in metadata.items() for item in pair]
    return " ".join([title, *tags, *metadata_terms, extra])


def _write_recall_index(path: Path, index: RecallIndex) -> None:
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        json.dump(asdict(index), temporary_file, ensure_ascii=False, indent=2, sort_keys=True)
        temporary_file.write("\n")
        temporary_path = Path(temporary_file.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_recall_index(path: Path) -> RecallIndex | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or raw.get("version") != _INDEX_VERSION:
            return None
        return RecallIndex(
            version=_require_string(raw.get("version")),
            bank_path=_require_string(raw.get("bank_path")),
            generated_at=_require_string(raw.get("generated_at")),
            source_files=_parse_source_files(raw.get("source_files")),
            documents=_parse_documents(raw.get("documents")),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _parse_source_files(value: object) -> list[SourceFileState]:
    if not isinstance(value, list):
        raise ValueError("source_files must be a list")
    states: list[SourceFileState] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("source file must be an object")
        states.append(
            SourceFileState(
                path=_require_string(item.get("path")),
                size=_require_int(item.get("size")),
                mtime_ns=_require_int(item.get("mtime_ns")),
            )
        )
    return states


def _parse_documents(value: object) -> list[RecallIndexDocument]:
    if not isinstance(value, list):
        raise ValueError("documents must be a list")
    documents: list[RecallIndexDocument] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("document must be an object")
        documents.append(
            RecallIndexDocument(
                id=_require_string(item.get("id")),
                source=_require_source(item.get("source")),
                path=_require_string(item.get("path")),
                title=_require_string(item.get("title")),
                body=_require_string(item.get("body"), allow_empty=True),
                keywords=_require_string(item.get("keywords"), allow_empty=True),
                timestamp=_optional_string(item.get("timestamp")),
                metadata=_parse_string_map(item.get("metadata")),
                term_frequencies=_parse_float_map(item.get("term_frequencies")),
                token_count=_require_number(item.get("token_count")),
            )
        )
    return documents


def _parse_string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("metadata must be an object")
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("metadata values must be strings")
    return dict(value)


def _parse_float_map(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("term_frequencies must be an object")
    parsed: dict[str, float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError("term frequencies must be numeric")
        parsed[key] = float(item)
    return parsed


def _require_string(value: object, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError("value must be a string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_string(value)


def _require_source(value: object) -> Literal["page", "session"]:
    if value == "page" or value == "session":
        return value
    raise ValueError("document source must be page or session")


def _require_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("value must be a non-negative integer")
    return value


def _require_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError("value must be a non-negative number")
    return float(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
