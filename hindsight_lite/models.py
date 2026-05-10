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
