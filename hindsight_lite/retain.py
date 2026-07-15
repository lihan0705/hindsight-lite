from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from hindsight_lite.models import (
    ObservationCandidate,
    RetainedEntity,
    RetainedFact,
    RetainedRelationship,
    RetainGraphEdge,
    RetainGraphNode,
    RetainRecord,
    RetainSecurityEvent,
    SessionMemoryEvent,
)

ExtractionMode = Literal["concise", "verbose", "custom"]

_CAPITALIZED_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3}\b")
_CONCEPT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_+#.-]{2,}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_TIME_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.I),
    re.compile(r"\b(?:last|next)\s+(?:spring|summer|fall|autumn|winter|week|month|year)\b", re.I),
    re.compile(r"\b(?:in|during)\s+\d{4}\b", re.I),
)
_PROMPT_INJECTION_RE = re.compile(
    r"(ignore (?:all )?(?:previous|prior) instructions|system prompt|developer message|jailbreak)",
    re.I,
)
_CAUSAL_RE = re.compile(r"\b(because|due to|therefore|so that|so|caused by|导致|因为|所以)\b", re.I)
_EMOTION_RE = re.compile(r"\b(thrilled|excited|happy|frustrated|worried|concerned|angry|upset|burned out)\b", re.I)
_STOP_ENTITIES = {
    "Do",
    "Remember",
    "Reply",
    "Memory",
    "What",
    "Your",
    "The",
    "This",
    "That",
    "I",
}


@dataclass(frozen=True)
class RetainArtifacts:
    record: RetainRecord
    graph_nodes: list[RetainGraphNode]
    graph_edges: list[RetainGraphEdge]
    observation_candidate: ObservationCandidate | None


@dataclass(frozen=True)
class RetainMessage:
    role: str
    text: str


def create_retain_artifacts(
    event: SessionMemoryEvent,
    extraction_mode: ExtractionMode = "concise",
    retain_mission: str | None = None,
    receipt_uri: str | None = None,
) -> RetainArtifacts:
    messages = _event_messages(event)
    facts = _extract_facts(event, messages, extraction_mode)
    entities = _extract_entities(facts)
    relationships = _extract_relationships(facts, entities)
    security_events = _detect_security_events(messages, receipt_uri)
    record = RetainRecord(
        type="retain_record",
        id=f"retain-{_digest(event.bank_id, event.session_id, event.id)}",
        timestamp=event.timestamp,
        bank_id=event.bank_id,
        session_id=event.session_id,
        source_event_id=event.id,
        mention_time=event.timestamp,
        extraction_mode=extraction_mode,
        retain_mission=retain_mission,
        facts=facts,
        entities=entities,
        relationships=relationships,
        security_events=security_events,
        receipt_uri=receipt_uri,
    )
    graph_nodes = _graph_nodes(record)
    graph_edges = _graph_edges(record)
    return RetainArtifacts(
        record=record,
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        observation_candidate=_observation_candidate(record),
    )


def _event_messages(event: SessionMemoryEvent) -> list[RetainMessage]:
    try:
        parsed = json.loads(event.content)
    except json.JSONDecodeError:
        return [RetainMessage(role="unknown", text=event.content)]
    if not isinstance(parsed, list):
        return [RetainMessage(role="unknown", text=event.content)]
    messages: list[RetainMessage] = []
    for item in parsed:
        if not isinstance(item, Mapping):
            continue
        text = _content_text(item.get("content"))
        if text:
            messages.append(RetainMessage(role=str(item.get("role", "unknown")), text=text))
    return messages or [RetainMessage(role="unknown", text=event.content)]


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif item.get("type") == "tool_use":
                    parts.append(f"{item.get('name', 'tool')}: {json.dumps(item.get('input', {}), ensure_ascii=False)}")
                elif item.get("type") == "tool_result" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return ""


def _extract_facts(
    event: SessionMemoryEvent,
    messages: list[RetainMessage],
    extraction_mode: ExtractionMode,
) -> list[RetainedFact]:
    facts: list[RetainedFact] = []
    limit = 4 if extraction_mode == "concise" else 16
    for message_index, message in enumerate(messages):
        for sentence_index, sentence in enumerate(_fact_sentences(message.text)):
            if len(facts) >= limit:
                return facts
            if not _significant_fact(sentence, extraction_mode):
                continue
            entity_names = _entity_names(sentence)
            facts.append(
                RetainedFact(
                    type="retained_fact",
                    id=f"fact-{_digest(event.id, str(message_index), str(sentence_index), sentence)}",
                    kind="experience" if message.role == "assistant" else "world",
                    text=sentence,
                    evidence=sentence,
                    source_role=message.role,
                    entity_ids=[_entity_id(name) for name in entity_names],
                    reasoning=_reasoning(sentence),
                    emotion=_emotion(sentence),
                    significance=_significance(sentence),
                    occurred_at=_occurred_at(sentence),
                    mentioned_at=event.timestamp,
                )
            )
    return facts


def _fact_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT_RE.split(text) if sentence.strip()]


def _significant_fact(sentence: str, extraction_mode: ExtractionMode) -> bool:
    if extraction_mode == "verbose":
        return len(sentence) >= 3
    lowered = sentence.lower()
    return (
        len(sentence) >= 12
        and not lowered.startswith(("reply exactly", "do not run tools"))
        and lowered not in {"remembered", "retained", "ok"}
    )


def _entity_names(text: str) -> list[str]:
    names = [match.group(0).strip() for match in _CAPITALIZED_ENTITY_RE.finditer(text)]
    names.extend(_concept_names(text))
    ordered: dict[str, None] = {}
    for name in names:
        normalized = name.strip(" .,:;!?")
        if normalized and normalized not in _STOP_ENTITIES:
            ordered[normalized] = None
    return list(ordered)


def _concept_names(text: str) -> list[str]:
    concepts = []
    for match in _CONCEPT_RE.finditer(text):
        value = match.group(0)
        if any(marker in value for marker in ("_", "+", "#", ".")) or value.lower() in {
            "python",
            "pytest",
            "sqlite",
            "fastapi",
            "postgresql",
            "typescript",
            "rust",
        }:
            concepts.append(value)
    return concepts


def _extract_entities(facts: list[RetainedFact]) -> list[RetainedEntity]:
    mentions: dict[str, list[str]] = {}
    for fact in facts:
        for name in _entity_names(fact.evidence):
            mentions.setdefault(name, []).append(fact.id)
    return [
        RetainedEntity(
            id=_entity_id(name),
            name=name,
            kind=_entity_kind(name),
            aliases=[],
            mentions=sorted(set(fact_ids)),
        )
        for name, fact_ids in sorted(mentions.items(), key=lambda item: _entity_id(item[0]))
    ]


def _entity_kind(name: str) -> Literal["person", "organization", "place", "product", "concept", "label"]:
    lowered = name.lower()
    if lowered in {"google", "openai", "mit", "stanford"}:
        return "organization"
    if lowered in {"python", "pytest", "sqlite", "rust", "typescript", "fastapi", "postgresql"}:
        return "concept"
    if lowered in {"fly.io"}:
        return "product"
    if " " in name and all(part[:1].isupper() for part in name.split()):
        return "person"
    return "concept"


def _extract_relationships(facts: list[RetainedFact], entities: list[RetainedEntity]) -> list[RetainedRelationship]:
    known_entity_ids = {entity.id for entity in entities}
    relationships: list[RetainedRelationship] = []
    for fact in facts:
        entity_ids = [entity_id for entity_id in fact.entity_ids if entity_id in known_entity_ids]
        for entity_id in entity_ids:
            relationships.append(
                RetainedRelationship(
                    id=f"rel-{_digest(fact.id, entity_id, 'mentions')}",
                    source_entity_id=entity_id,
                    target_entity_id=fact.id,
                    kind="mentions",
                    evidence=fact.evidence,
                    fact_ids=[fact.id],
                )
            )
        if len(entity_ids) >= 2:
            kind: Literal["co_occurs", "causes"] = "causes" if _CAUSAL_RE.search(fact.evidence) else "co_occurs"
            relationships.append(
                RetainedRelationship(
                    id=f"rel-{_digest(fact.id, entity_ids[0], entity_ids[1], kind)}",
                    source_entity_id=entity_ids[0],
                    target_entity_id=entity_ids[1],
                    kind=kind,
                    evidence=fact.evidence,
                    fact_ids=[fact.id],
                )
            )
    return relationships


def _graph_nodes(record: RetainRecord) -> list[RetainGraphNode]:
    nodes: list[RetainGraphNode] = []
    for entity in record.entities:
        nodes.append(
            RetainGraphNode(
                type="retain_graph_node",
                id=entity.id,
                kind="entity",
                label=entity.name,
                retain_id=record.id,
                entity_kind=entity.kind,
                source_id=entity.id,
            )
        )
    for fact in record.facts:
        nodes.append(
            RetainGraphNode(
                type="retain_graph_node",
                id=fact.id,
                kind="fact",
                label=fact.text,
                retain_id=record.id,
                fact_kind=fact.kind,
                source_id=fact.id,
            )
        )
    return nodes


def _graph_edges(record: RetainRecord) -> list[RetainGraphEdge]:
    return [
        RetainGraphEdge(
            type="retain_graph_edge",
            id=relationship.id,
            source_id=relationship.source_entity_id,
            target_id=relationship.target_entity_id,
            kind=relationship.kind,
            evidence=relationship.evidence,
            retain_id=record.id,
            fact_ids=relationship.fact_ids,
        )
        for relationship in record.relationships
    ]


def _observation_candidate(record: RetainRecord) -> ObservationCandidate | None:
    durable_facts = [fact for fact in record.facts if fact.kind == "world"]
    if not durable_facts:
        return None
    observation = f"Retain extracted {len(durable_facts)} world fact candidate(s)."
    if record.relationships:
        observation = f"{observation} It linked {len(record.relationships)} relationship(s)."
    return ObservationCandidate(
        type="observation_candidate",
        id=f"observe-{_digest(record.bank_id, record.session_id, record.id)}",
        timestamp=record.timestamp,
        bank_id=record.bank_id,
        session_id=record.session_id,
        source_retain_id=record.id,
        observation=observation,
        evidence_fact_ids=[fact.id for fact in durable_facts],
        proof_count=len(durable_facts),
        confidence=0.6,
    )


def _detect_security_events(messages: list[RetainMessage], receipt_uri: str | None) -> list[RetainSecurityEvent]:
    events: list[RetainSecurityEvent] = []
    for message in messages:
        match = _PROMPT_INJECTION_RE.search(message.text)
        if match is None:
            continue
        events.append(
            RetainSecurityEvent(
                detector="prompt_injection",
                severity="high",
                message="Potential prompt injection text was retained as evidence only.",
                evidence=match.group(0),
                receipt_uri=receipt_uri,
            )
        )
    return events


def _reasoning(sentence: str) -> str | None:
    match = _CAUSAL_RE.search(sentence)
    if match is None:
        return None
    return sentence[match.start() :].strip()


def _emotion(sentence: str) -> str | None:
    match = _EMOTION_RE.search(sentence)
    return match.group(0).lower() if match else None


def _significance(sentence: str) -> str | None:
    lowered = sentence.lower()
    if "opportunity" in lowered or "important" in lowered or "decision" in lowered:
        return sentence
    return None


def _occurred_at(sentence: str) -> str | None:
    for pattern in _TIME_PATTERNS:
        match = pattern.search(sentence)
        if match:
            return match.group(0)
    return None


def _entity_id(name: str) -> str:
    normalized = " ".join(name.lower().split())
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "entity"
    return f"entity-{slug}-{_digest(normalized)[:8]}"


def _digest(*parts: str) -> str:
    joined = "\0".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
