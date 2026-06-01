from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from hindsight_lite.models import RecallResult, ReflectionResult, ReflectionTrajectory
from hindsight_lite.reflection import ReflectionResultError, parse_reflection_result
from hindsight_lite.store import LocalMemoryStore


@dataclass(frozen=True)
class ReflectionRequestRecord:
    id: str
    timestamp: str
    bank_id: str
    session_id: str
    query: str
    retrieved_context: list[RecallResult]
    task_context: dict[str, str]
    reflection_prompt: str


@dataclass(frozen=True)
class ReflectionDatasetExample:
    request_id: str
    result_id: str
    bank_id: str
    session_id: str
    request_timestamp: str
    result_timestamp: str
    query: str
    retrieved_context: list[RecallResult]
    task_context: dict[str, str]
    reflection_prompt: str
    trajectory: ReflectionTrajectory
    durable_facts: list[str]
    reusable_procedures: list[str]
    uncertain_items: list[str]
    confidence: float


@dataclass(frozen=True)
class ReflectionDatasetExportResult:
    output_path: Path
    example_count: int


@dataclass(frozen=True)
class ReflectionRecords:
    requests: dict[str, ReflectionRequestRecord]
    results: list[ReflectionResult]


def export_reflection_dataset(store: LocalMemoryStore, output_path: Path) -> ReflectionDatasetExportResult:
    examples = build_reflection_dataset_examples(store)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for example in examples:
            file.write(json.dumps(asdict(example), ensure_ascii=False, sort_keys=True))
            file.write("\n")
    return ReflectionDatasetExportResult(output_path=output_path, example_count=len(examples))


def build_reflection_dataset_examples(store: LocalMemoryStore) -> list[ReflectionDatasetExample]:
    records = _load_reflection_records(store)
    examples: list[ReflectionDatasetExample] = []
    for result in sorted(records.results, key=lambda item: item.id):
        request = records.requests.get(result.request_id)
        if request is None or request.bank_id != store.paths.bank_id or result.bank_id != store.paths.bank_id:
            continue
        examples.append(_dataset_example(request, result))
    return examples


def _load_reflection_records(store: LocalMemoryStore) -> ReflectionRecords:
    requests: dict[str, ReflectionRequestRecord] = {}
    results: list[ReflectionResult] = []
    for path in sorted(store.paths.reflections_dir.glob("*.json")):
        record = _read_reflection_record(path)
        if isinstance(record, ReflectionRequestRecord):
            requests[record.id] = record
        elif isinstance(record, ReflectionResult):
            results.append(record)
    return ReflectionRecords(requests=requests, results=results)


def _read_reflection_record(path: Path) -> ReflectionRequestRecord | ReflectionResult | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, Mapping):
        return None
    if raw.get("type") == "reflection_request":
        return _parse_reflection_request(raw)
    if raw.get("type") == "reflection_result":
        try:
            return parse_reflection_result(raw)
        except ReflectionResultError:
            return None
    return None


def _parse_reflection_request(data: Mapping[str, object]) -> ReflectionRequestRecord | None:
    retrieved_context = _parse_recall_results(data.get("retrieved_context"))
    task_context = _string_map(data.get("task_context"))
    required = [
        data.get("id"),
        data.get("timestamp"),
        data.get("bank_id"),
        data.get("session_id"),
        data.get("query"),
        data.get("reflection_prompt"),
    ]
    if any(not isinstance(item, str) or not item for item in required):
        return None

    return ReflectionRequestRecord(
        id=str(data["id"]),
        timestamp=str(data["timestamp"]),
        bank_id=str(data["bank_id"]),
        session_id=str(data["session_id"]),
        query=str(data["query"]),
        retrieved_context=retrieved_context,
        task_context=task_context,
        reflection_prompt=str(data["reflection_prompt"]),
    )


def _parse_recall_results(value: object) -> list[RecallResult]:
    if not isinstance(value, list):
        return []

    results: list[RecallResult] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result = _parse_recall_result(item)
        if result is not None:
            results.append(result)
    return results


def _parse_recall_result(data: Mapping[str, object]) -> RecallResult | None:
    required = [data.get("id"), data.get("source"), data.get("path"), data.get("title"), data.get("excerpt")]
    if any(not isinstance(item, str) or not item for item in required):
        return None
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        return None
    source_text = str(data["source"])
    if source_text not in {"session", "page"}:
        return None
    source = "session" if source_text == "session" else "page"

    timestamp = data.get("timestamp")
    return RecallResult(
        id=str(data["id"]),
        source=source,
        path=str(data["path"]),
        score=float(score),
        title=str(data["title"]),
        excerpt=str(data["excerpt"]),
        timestamp=timestamp if isinstance(timestamp, str) else None,
        metadata=_string_map(data.get("metadata")),
    )


def _dataset_example(request: ReflectionRequestRecord, result: ReflectionResult) -> ReflectionDatasetExample:
    return ReflectionDatasetExample(
        request_id=request.id,
        result_id=result.id,
        bank_id=result.bank_id,
        session_id=result.session_id,
        request_timestamp=request.timestamp,
        result_timestamp=result.timestamp,
        query=request.query,
        retrieved_context=request.retrieved_context,
        task_context=request.task_context,
        reflection_prompt=request.reflection_prompt,
        trajectory=result.trajectory,
        durable_facts=result.durable_facts,
        reusable_procedures=result.reusable_procedures,
        uncertain_items=result.uncertain_items,
        confidence=result.confidence,
    )


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}
