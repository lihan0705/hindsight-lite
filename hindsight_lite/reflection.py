from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from hindsight_lite.models import (
    ReflectionPacket,
    ReflectionResult,
    ReflectionTrajectory,
    default_reflection_result_schema,
)
from hindsight_lite.recall import recall
from hindsight_lite.store import LocalMemoryStore


class ReflectionResultError(ValueError):
    pass


def create_reflection_packet(
    store: LocalMemoryStore,
    session_id: str,
    query: str,
    task_context: dict[str, str] | None = None,
    max_results: int = 5,
) -> ReflectionPacket:
    context = recall(store, query, max_results=max_results)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    packet = ReflectionPacket(
        type="reflection_request",
        id=f"reflect-{uuid4().hex}",
        timestamp=timestamp,
        bank_id=store.paths.bank_id,
        session_id=session_id,
        query=query,
        retrieved_context=context,
        task_context=task_context or {},
        reflection_prompt=_build_reflection_prompt(query),
    )
    store.write_reflection_packet(packet)
    return packet


def write_reflection_result_from_file(store: LocalMemoryStore, path: Path) -> Path:
    result = parse_reflection_result(json.loads(path.read_text(encoding="utf-8")))
    if result.bank_id != store.paths.bank_id:
        raise ReflectionResultError(
            f"reflection result bank_id {result.bank_id!r} does not match {store.paths.bank_id!r}"
        )
    return store.write_reflection_result(result)


def parse_reflection_result(value: object) -> ReflectionResult:
    data = _require_mapping(value, "reflection result")
    trajectory = _require_mapping(data.get("trajectory"), "trajectory")
    confidence = _require_number(data.get("confidence"), "confidence")
    if confidence < 0.0 or confidence > 1.0:
        raise ReflectionResultError("confidence must be between 0.0 and 1.0")

    return ReflectionResult(
        type=_require_literal(data.get("type"), "type", "reflection_result"),
        id=_require_string(data.get("id"), "id"),
        request_id=_require_string(data.get("request_id"), "request_id"),
        timestamp=_require_string(data.get("timestamp"), "timestamp"),
        bank_id=_require_string(data.get("bank_id"), "bank_id"),
        session_id=_require_string(data.get("session_id"), "session_id"),
        trajectory=ReflectionTrajectory(
            state=_require_string(trajectory.get("state"), "trajectory.state"),
            action=_require_string(trajectory.get("action"), "trajectory.action"),
            observation=_require_string(trajectory.get("observation"), "trajectory.observation"),
            outcome=_require_string(trajectory.get("outcome"), "trajectory.outcome"),
            lesson=_require_string(trajectory.get("lesson"), "trajectory.lesson"),
        ),
        durable_facts=_require_string_list(data.get("durable_facts"), "durable_facts"),
        reusable_procedures=_require_string_list(data.get("reusable_procedures"), "reusable_procedures"),
        uncertain_items=_require_string_list(data.get("uncertain_items"), "uncertain_items"),
        confidence=confidence,
    )


def _build_reflection_prompt(query: str) -> str:
    return "\n".join(
        [
            "Reflect on this task using retrieved hindsight-lite memory.",
            "",
            f"Query: {query}",
            "",
            "Return a concise reflection_result object matching schema version "
            f"{default_reflection_result_schema().version}:",
            "- trajectory: state -> action -> observation -> outcome -> lesson",
            "- durable facts worth promoting",
            "- procedures worth reusing",
            "- uncertainty or conflicts that should not be promoted yet",
            "- confidence from 0.0 to 1.0",
        ]
    )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReflectionResultError(f"{field} must be an object")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReflectionResultError(f"{field} must be a non-empty string")
    return value


def _require_literal(value: object, field: str, expected: str) -> str:
    text = _require_string(value, field)
    if text != expected:
        raise ReflectionResultError(f"{field} must be {expected!r}")
    return text


def _require_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReflectionResultError(f"{field} must be a number")
    return float(value)


def _require_string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReflectionResultError(f"{field} must be a list of strings")
    return value
