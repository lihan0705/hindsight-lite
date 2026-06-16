from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hindsight_lite.store import LocalMemoryStore

_ENVIRONMENT_NOISE_PATTERNS = (
    re.compile(r"\.codex/plugins/cache", re.IGNORECASE),
    re.compile(r"personal-local/hindsight-lite", re.IGNORECASE),
    re.compile(r"operation not permitted", re.IGNORECASE),
    re.compile(r"sandbox permission", re.IGNORECASE),
    re.compile(r"requires? escalat(?:ed|ion)", re.IGNORECASE),
)
_OVERSIZED_STEP_COUNT = 20
_OVERSIZED_FAILED_COUNT = 8


@dataclass(frozen=True)
class ReflectionCleanupRecord:
    id: str
    path: Path
    record_type: Literal["reflection_request", "reflection_result"]
    entry_state: str
    searchable_text: str
    step_count: int
    failed_count: int


@dataclass(frozen=True)
class ReflectionCleanupCandidate:
    id: str
    path: Path
    record_type: str
    entry_state: str
    issue_codes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReflectionCleanupReport:
    scanned: int
    candidates: list[ReflectionCleanupCandidate]


def scan_reflection_cleanup(store: LocalMemoryStore) -> ReflectionCleanupReport:
    records = _read_reflection_records(store)
    repeated_entries = {
        entry_state
        for entry_state, count in Counter(record.entry_state for record in records if record.entry_state).items()
        if count > 1
    }
    candidates = [
        candidate for record in records if (candidate := _cleanup_candidate(record, repeated_entries)) is not None
    ]
    return ReflectionCleanupReport(scanned=len(records), candidates=candidates)


def _read_reflection_records(store: LocalMemoryStore) -> list[ReflectionCleanupRecord]:
    records: list[ReflectionCleanupRecord] = []
    for path in sorted(store.paths.reflections_dir.glob("*.json")):
        record = _read_reflection_record(path)
        if record is not None:
            records.append(record)
    return records


def _read_reflection_record(path: Path) -> ReflectionCleanupRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, Mapping):
        return None
    record_type = raw.get("type")
    if record_type != "reflection_request" and record_type != "reflection_result":
        return None
    record_id = _string_value(raw.get("id"))
    if not record_id:
        return None
    trajectory = _trajectory_mapping(raw)
    steps = _trajectory_steps(trajectory)
    return ReflectionCleanupRecord(
        id=record_id,
        path=path,
        record_type=record_type,
        entry_state=_entry_state(raw, trajectory, steps),
        searchable_text=_searchable_text(raw, trajectory, steps),
        step_count=len(steps),
        failed_count=sum(1 for step in steps if _string_value(step.get("status")) == "failed"),
    )


def _cleanup_candidate(
    record: ReflectionCleanupRecord,
    repeated_entries: set[str],
) -> ReflectionCleanupCandidate | None:
    issue_codes: list[str] = []
    reasons: list[str] = []
    if record.entry_state in repeated_entries:
        issue_codes.append("repeated-entry")
        reasons.append(f"shares entry state {record.entry_state!r} with another reflection")
    if _has_environment_noise(record.searchable_text):
        issue_codes.append("environment-noise")
        reasons.append("contains plugin-cache, sandbox, or local permission noise")
    if record.step_count >= _OVERSIZED_STEP_COUNT or record.failed_count >= _OVERSIZED_FAILED_COUNT:
        issue_codes.append("oversized-trajectory")
        reasons.append(f"contains {record.step_count} steps and {record.failed_count} failed steps")
    if not issue_codes:
        return None
    return ReflectionCleanupCandidate(
        id=record.id,
        path=record.path,
        record_type=record.record_type,
        entry_state=record.entry_state,
        issue_codes=issue_codes,
        reasons=reasons,
    )


def _trajectory_mapping(data: Mapping[str, object]) -> Mapping[str, object]:
    trajectory = data.get("trajectory")
    if isinstance(trajectory, Mapping):
        return trajectory
    candidate_trajectory = data.get("candidate_trajectory")
    if isinstance(candidate_trajectory, Mapping):
        return candidate_trajectory
    return {}


def _trajectory_steps(trajectory: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_steps = trajectory.get("steps")
    if not isinstance(raw_steps, list):
        return []
    return [step for step in raw_steps if isinstance(step, Mapping)]


def _entry_state(
    data: Mapping[str, object],
    trajectory: Mapping[str, object],
    steps: list[Mapping[str, object]],
) -> str:
    for step in steps:
        if _string_value(step.get("kind")) == "state":
            return _compact_text(_string_value(step.get("content")))
    return _compact_text(_string_value(trajectory.get("state")) or _string_value(data.get("query")))


def _searchable_text(
    data: Mapping[str, object],
    trajectory: Mapping[str, object],
    steps: list[Mapping[str, object]],
) -> str:
    values = [
        _string_value(data.get("query")),
        _string_value(data.get("trigger_reason")),
        _string_value(trajectory.get("state")),
        _string_value(trajectory.get("action")),
        _string_value(trajectory.get("observation")),
        _string_value(trajectory.get("outcome")),
        _string_value(trajectory.get("lesson")),
    ]
    values.extend(_string_value(step.get("content")) for step in steps)
    return "\n".join(value for value in values if value)


def _has_environment_noise(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ENVIRONMENT_NOISE_PATTERNS)


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""
