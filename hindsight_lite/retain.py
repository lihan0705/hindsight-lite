from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from hindsight_lite.models import (
    RetainedEntity,
    RetainedFact,
    RetainedRelationship,
    RetainRecord,
    RetainSecurityEvent,
    SessionMemoryEvent,
)

ExtractionMode = Literal["concise", "verbose", "custom"]

_LEGACY_MESSAGE_RE = re.compile(r"\[role: (?P<role>[^\]]+)\]\n(?P<content>.*?)\n\[(?P=role):end\]", re.S)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_ENTITY_RE = re.compile(r"`([^`]{2,80})`|\b([A-Z][A-Za-z0-9_.-]{1,79})\b")
_FILE_RE = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|md|json|toml|yaml|yml|sh)\b")
_CONCISE_MARKERS = (
    "remember",
    "prefer",
    "decided",
    "decision",
    "fixed",
    "resolved",
    "implemented",
    "should",
    "must",
    "use ",
    "不要",
    "需要",
    "必须",
    "记住",
    "喜欢",
    "我是",
    "决定",
    "修复",
)
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "reveal your system prompt",
    "disregard prior instructions",
    "forget your instructions",
)
_ORGANIZATION_SUFFIXES = ("Inc", "LLC", "Corp", "Labs", "OpenAI", "Google", "Microsoft", "MIT")
_PLACE_NAMES = {"Paris", "California", "London", "Beijing", "Shanghai", "深圳", "北京", "上海"}


@dataclass(frozen=True)
class RetainMessage:
    role: str
    text: str


def create_retain_record(
    event: SessionMemoryEvent,
    extraction_mode: ExtractionMode = "concise",
    retain_mission: str | None = None,
    receipt_uri: str | None = None,
) -> RetainRecord:
    mode = extraction_mode if extraction_mode in ("concise", "verbose", "custom") else "concise"
    messages = _parse_messages(event.content)
    facts = _extract_facts(messages, mode, retain_mission)
    entities = _extract_entities(facts)
    relationships = _extract_relationships(facts)
    security_events = _detect_security_events(messages, receipt_uri)
    return RetainRecord(
        type="retain_record",
        id=f"retain-{_digest(event.bank_id, event.session_id, event.id)}",
        timestamp=event.timestamp,
        bank_id=event.bank_id,
        session_id=event.session_id,
        source_event_id=event.id,
        extraction_mode=mode,
        retain_mission=retain_mission,
        facts=facts,
        entities=entities,
        relationships=relationships,
        security_events=security_events,
    )


def _parse_messages(content: str) -> list[RetainMessage]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return _parse_json_messages(parsed)

    legacy = [
        RetainMessage(role=match.group("role"), text=match.group("content").strip())
        for match in _LEGACY_MESSAGE_RE.finditer(content)
        if match.group("content").strip()
    ]
    if legacy:
        return legacy
    return [RetainMessage(role="unknown", text=content.strip())] if content.strip() else []


def _parse_json_messages(messages: list[object]) -> list[RetainMessage]:
    parsed: list[RetainMessage] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if not isinstance(role, str):
            continue
        text = _text_from_content(item.get("content"))
        if text:
            parsed.append(RetainMessage(role=role, text=text))
    return parsed


def _text_from_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
            parts.append(f"Used tool {block['name']}.")
        elif block.get("type") == "tool_result" and isinstance(block.get("content"), str):
            parts.append(block["content"])
    return "\n".join(part.strip() for part in parts if part.strip())


def _extract_facts(
    messages: list[RetainMessage],
    mode: ExtractionMode,
    retain_mission: str | None,
) -> list[RetainedFact]:
    mission_terms = set(_terms(retain_mission or ""))
    facts: list[RetainedFact] = []
    for message in messages:
        for sentence in _sentences(message.text):
            if not _keeps_sentence(sentence, mode, mission_terms):
                continue
            fact_entities = [_entity_id(name) for name in _entity_names(sentence)]
            facts.append(
                RetainedFact(
                    id=f"fact-{_digest(message.role, sentence)}",
                    perspective="experience" if message.role == "assistant" else "world",
                    text=sentence,
                    source_role=message.role,
                    evidence=sentence,
                    entities=fact_entities,
                )
            )
    return _dedupe_facts(facts)


def _keeps_sentence(sentence: str, mode: ExtractionMode, mission_terms: set[str]) -> bool:
    normalized = sentence.lower()
    if len(sentence) < 8:
        return False
    if mission_terms and not mission_terms.intersection(_terms(sentence)):
        return False
    if mode in ("verbose", "custom"):
        return True
    return any(marker in normalized or marker in sentence for marker in _CONCISE_MARKERS)


def _sentences(text: str) -> list[str]:
    return [sentence.strip(" \t-") for sentence in _SENTENCE_SPLIT_RE.split(text) if sentence.strip(" \t-")]


def _extract_entities(facts: list[RetainedFact]) -> list[RetainedEntity]:
    counts = Counter(name for fact in facts for name in _entity_names(fact.text))
    return [
        RetainedEntity(id=_entity_id(name), name=name, kind=_entity_kind(name), mentions=count)
        for name, count in sorted(counts.items())
    ]


def _extract_relationships(facts: list[RetainedFact]) -> list[RetainedRelationship]:
    relationships: list[RetainedRelationship] = []
    for fact in facts:
        names = _entity_names(fact.text)
        if len(names) < 2:
            continue
        kind: Literal["co_occurs", "causes"] = "causes" if _has_causal_marker(fact.text) else "co_occurs"
        relationships.append(
            RetainedRelationship(
                id=f"rel-{_digest(names[0], names[1], kind, fact.id)}",
                source_entity=_entity_id(names[0]),
                target_entity=_entity_id(names[1]),
                kind=kind,
                evidence=fact.text,
            )
        )
    return relationships


def _detect_security_events(messages: list[RetainMessage], receipt_uri: str | None) -> list[RetainSecurityEvent]:
    events: list[RetainSecurityEvent] = []
    for message in messages:
        normalized = message.text.lower()
        for marker in _INJECTION_MARKERS:
            if marker in normalized:
                events.append(
                    RetainSecurityEvent(
                        detector="prompt_injection",
                        severity="high",
                        message="Prompt-injection language was retained as evidence.",
                        evidence=message.text[:500],
                        receipt_uri=receipt_uri,
                    )
                )
                break
    return events


def _entity_names(text: str) -> list[str]:
    names = []
    for match in _ENTITY_RE.finditer(text):
        names.append((match.group(1) or match.group(2)).strip())
    names.extend(match.group(0).strip() for match in _FILE_RE.finditer(text))
    return sorted(set(name for name in names if len(name) > 1 and not name.isdigit()))


def _entity_kind(name: str) -> Literal["person", "organization", "place", "product", "concept"]:
    if name in _PLACE_NAMES:
        return "place"
    if name.endswith(_ORGANIZATION_SUFFIXES):
        return "organization"
    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", name):
        return "person"
    if "." in name or "-" in name or "_" in name:
        return "product"
    return "concept"


def _has_causal_marker(text: str) -> bool:
    normalized = text.lower()
    return (
        any(marker in normalized for marker in ("because", "due to", "caused by")) or "因为" in text or "所以" in text
    )


def _entity_id(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.lower()).strip("-") or "entity"
    return f"{slug}-{_digest(name)[:8]}"


def _terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text.lower())


def _dedupe_facts(facts: list[RetainedFact]) -> list[RetainedFact]:
    seen: set[str] = set()
    deduped: list[RetainedFact] = []
    for fact in facts:
        key = fact.text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return deduped


def _digest(*parts: str) -> str:
    return hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:16]
