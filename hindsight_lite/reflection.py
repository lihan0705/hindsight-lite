from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from hindsight_lite.models import ReflectionPacket, default_reflection_result_schema
from hindsight_lite.recall import recall
from hindsight_lite.store import LocalMemoryStore


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
