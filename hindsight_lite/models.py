from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class SessionMemoryEvent:
    type: Literal["session_memory"]
    id: str
    timestamp: str
    bank_id: str
    session_id: str
    source: str
    document_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgePage:
    id: str
    title: str
    content: str
    path: str
    updated_at: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RecallResult:
    id: str
    source: Literal["session", "page"]
    path: str
    score: float
    title: str
    excerpt: str
    timestamp: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReflectionResultField:
    name: str
    value_type: Literal["string", "string_list", "number", "object"]
    description: str
    required: bool = True


@dataclass(frozen=True)
class ReflectionResultSchema:
    version: str
    result_type: Literal["reflection_result"]
    fields: list[ReflectionResultField]


def default_reflection_result_schema() -> ReflectionResultSchema:
    return ReflectionResultSchema(
        version="1.0",
        result_type="reflection_result",
        fields=[
            ReflectionResultField(
                name="trajectory",
                value_type="object",
                description="State, action, observation, outcome, and lesson for one agent work trajectory.",
            ),
            ReflectionResultField(
                name="durable_facts",
                value_type="string_list",
                description="Facts stable enough to promote into long-term pages.",
            ),
            ReflectionResultField(
                name="reusable_procedures",
                value_type="string_list",
                description="Procedures or strategies that should guide similar future work.",
            ),
            ReflectionResultField(
                name="uncertain_items",
                value_type="string_list",
                description="Conflicts, weak evidence, or open questions that should not be promoted yet.",
            ),
            ReflectionResultField(
                name="confidence",
                value_type="number",
                description="Confidence score from 0.0 to 1.0 for using this result as eval/RL data.",
            ),
        ],
    )


@dataclass(frozen=True)
class ReflectionTrajectory:
    state: str
    action: str
    observation: str
    outcome: str
    lesson: str


@dataclass(frozen=True)
class ReflectionResult:
    type: Literal["reflection_result"]
    id: str
    request_id: str
    timestamp: str
    bank_id: str
    session_id: str
    trajectory: ReflectionTrajectory
    durable_facts: list[str] = field(default_factory=list)
    reusable_procedures: list[str] = field(default_factory=list)
    uncertain_items: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class ReflectionPacket:
    type: Literal["reflection_request"]
    id: str
    timestamp: str
    bank_id: str
    session_id: str
    query: str
    retrieved_context: list[RecallResult]
    task_context: dict[str, str]
    reflection_prompt: str
    result_schema: ReflectionResultSchema = field(default_factory=default_reflection_result_schema)
