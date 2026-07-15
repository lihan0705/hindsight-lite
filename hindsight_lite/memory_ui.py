from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hindsight_lite.index import recall_index_path, recall_index_status
from hindsight_lite.store import LocalMemoryStore

_SESSION_EVENT_SOURCE_LIMIT_BYTES = 256 * 1024
_SESSION_EVENT_CONTENT_LIMIT = 12_000
_SESSION_FILE_CONTENT_LIMIT = 80_000
_TRAJECTORY_STEP_SUMMARY_LIMIT = 180

_SECTION_HELP = {
    "pages": "Markdown knowledge pages promoted for direct human editing.",
    "sessions": "Raw Codex session snapshots. These are source evidence, not summaries.",
    "retains": "One retain operation envelope per session: settings, source id, extracted objects.",
    "facts": "First-class world/experience facts extracted from retain.",
    "entities": "Entity registry merged across retains.",
    "graph": "Graph data files: nodes are facts/entities, edges are links between them.",
    "observation-candidates": "Evidence-backed candidates only. These are not consolidated observations yet.",
    "reflections": "Reflection requests/results for failure, correction, and reusable trajectory review.",
    "index": "Derived recall index. Safe to rebuild or delete.",
}

_KIND_HELP = {
    "page": "Editable Markdown knowledge page.",
    "session": "Raw session source event.",
    "retain-record": "Retain operation envelope.",
    "retained-facts": "Extracted facts, one JSON object per line.",
    "json-list": "JSON list registry.",
    "graph-nodes": "Graph nodes for entities and facts.",
    "graph-edges": "Graph links between retained nodes.",
    "observation-candidate": "Reviewable observation candidate backed by facts.",
    "reflection-request": "Reflection request or candidate trajectory.",
    "reflection-result": "Evaluated reflection result.",
    "index": "Derived recall index summary.",
}


@dataclass(frozen=True)
class MemoryUiFile:
    id: str
    label: str
    kind: str
    path: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    description: str = ""
    editable: bool = False
    download_name: str = ""
    download_prefix: str = ""


@dataclass(frozen=True)
class MemoryUiSection:
    id: str
    label: str
    files: list[MemoryUiFile]
    description: str = ""


@dataclass(frozen=True)
class MemoryUiGraphNode:
    id: str
    label: str
    kind: str
    parent_id: str
    file_id: str = ""
    content: str = ""
    sample_status: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryUiGraph:
    root_id: str
    nodes: list[MemoryUiGraphNode]


@dataclass(frozen=True)
class MemoryUiSnapshot:
    bank_id: str
    bank_path: str
    sections: list[MemoryUiSection]
    graph: MemoryUiGraph | None = None
    save_url: str = ""
    section_help: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionUiPreview:
    content: str
    events: int
    source_bytes: int
    truncated: bool


@dataclass(frozen=True)
class IndexUiSummary:
    state: str
    documents: int
    source_files: int
    generated_at: str | None
    path: str


def write_memory_ui(store: LocalMemoryStore, output_path: Path | None = None) -> Path:
    path = output_path or store.paths.bank_dir / "memory-tree.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_memory_ui(store), encoding="utf-8")
    return path


def render_memory_ui(store: LocalMemoryStore, save_url: str = "") -> str:
    snapshot = _build_snapshot(store, save_url=save_url)
    payload = _script_safe_json(snapshot)
    return _HTML_TEMPLATE.replace("__MEMORY_SNAPSHOT__", payload)


def _script_safe_json(snapshot: MemoryUiSnapshot) -> str:
    payload = json.dumps(asdict(snapshot), ensure_ascii=False)
    return payload.replace("</", "<\\/")


def _build_snapshot(store: LocalMemoryStore, save_url: str = "") -> MemoryUiSnapshot:
    sections = [
        _pages_section(store),
        _jsonl_section("sessions", "Sessions", store.paths.sessions_dir),
        _json_section("retains", "Retains", store.paths.retains_dir),
        _jsonl_section("facts", "Facts", store.paths.facts_dir),
        _json_section("entities", "Entities", store.paths.entities_dir),
        _jsonl_section("graph", "Graph", store.paths.graph_dir),
        _json_section("observation-candidates", "Observation Candidates", store.paths.observation_candidates_dir),
        _reflections_section(store.paths.reflections_dir),
        _index_section(store),
    ]
    return MemoryUiSnapshot(
        bank_id=store.paths.bank_id,
        bank_path=str(store.paths.bank_dir),
        sections=sections,
        graph=_build_graph(store.paths.bank_id, sections),
        save_url=save_url,
        section_help=_SECTION_HELP,
    )


def _pages_section(store: LocalMemoryStore) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for page in store.list_pages():
        files.append(
            MemoryUiFile(
                id=f"page:{page.id}",
                label=page.id,
                kind="page",
                path=page.path,
                content=page.content,
                metadata={
                    "title": page.title,
                    "updated_at": page.updated_at or "",
                    "tags": ", ".join(page.tags),
                    **page.metadata,
                },
                description=_KIND_HELP["page"],
                editable=True,
                download_name=Path(page.path).name,
                download_prefix=_page_download_prefix(Path(page.path)),
            )
        )
    return MemoryUiSection(id="pages", label="Pages", files=files, description=_SECTION_HELP["pages"])


def _jsonl_section(section_id: str, label: str, directory: Path) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for path in sorted(directory.glob("*.jsonl")):
        if section_id == "sessions":
            preview = _session_ui_preview(path)
            rendered_content = preview.content
            metadata = {
                "events": str(preview.events),
                "size": _format_file_size(preview.source_bytes),
            }
            if preview.truncated:
                metadata["preview"] = "truncated"
        else:
            content = path.read_text(encoding="utf-8")
            rendered_content = content
            metadata = {"events": str(_count_jsonl_lines(content))}
        files.append(
            MemoryUiFile(
                id=f"{section_id}:{path.name}",
                label=path.name,
                kind=_jsonl_kind(section_id, path),
                path=str(path),
                content=rendered_content,
                metadata=metadata,
                description=_file_description(_jsonl_kind(section_id, path)),
            )
        )
    return MemoryUiSection(id=section_id, label=label, files=files, description=_SECTION_HELP.get(section_id, ""))


def _reflections_section(directory: Path) -> MemoryUiSection:
    parsed_files = [(path, _read_json_object(path)) for path in sorted(directory.glob("*.json"))]
    result_ids_by_request = _reflection_result_ids_by_request(parsed_files)
    files = [
        MemoryUiFile(
            id=f"reflections:{path.name}",
            label=path.name,
            kind=_reflection_kind(data),
            path=str(path),
            content=_format_json_value(data) if data is not None else path.read_text(encoding="utf-8"),
            metadata=_reflection_metadata(data, result_ids_by_request),
            description=_file_description(_reflection_kind(data)),
        )
        for path, data in parsed_files
    ]
    return MemoryUiSection(
        id="reflections",
        label="Reflections",
        files=files,
        description=_SECTION_HELP["reflections"],
    )


def _json_section(section_id: str, label: str, directory: Path) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for path in sorted(directory.glob("*.json")):
        data = _read_json_value(path)
        files.append(
            MemoryUiFile(
                id=f"{section_id}:{path.name}",
                label=path.name,
                kind=_json_kind(data),
                path=str(path),
                content=_format_json_value(data) if data is not None else path.read_text(encoding="utf-8"),
                metadata=_json_metadata(data),
                description=_file_description(_json_kind(data)),
            )
        )
    return MemoryUiSection(id=section_id, label=label, files=files, description=_SECTION_HELP.get(section_id, ""))


def _index_section(store: LocalMemoryStore) -> MemoryUiSection:
    status = recall_index_status(store)
    index_path = recall_index_path(store)
    files: list[MemoryUiFile] = []
    if index_path.exists():
        summary = IndexUiSummary(
            state=status.state,
            documents=status.document_count,
            source_files=status.source_file_count,
            generated_at=status.generated_at,
            path=status.path,
        )
        files.append(
            MemoryUiFile(
                id=f"index:{index_path.name}",
                label=index_path.name,
                kind="index",
                path=str(index_path),
                content=json.dumps(asdict(summary), ensure_ascii=False, indent=2, sort_keys=True),
                metadata={
                    "state": status.state,
                    "documents": str(status.document_count),
                    "source_files": str(status.source_file_count),
                    "generated_at": status.generated_at or "",
                },
                description=_KIND_HELP["index"],
            )
        )
    for path in sorted(item for item in store.paths.index_dir.iterdir() if item.is_file() and item != index_path):
        files.append(
            MemoryUiFile(
                id=f"index:{path.name}",
                label=path.name,
                kind="file",
                path=str(path),
                content=path.read_text(encoding="utf-8"),
                description="Derived index side file.",
            )
        )
    return MemoryUiSection(id="index", label="Index", files=files, description=_SECTION_HELP["index"])


def _count_jsonl_lines(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.strip())


def _jsonl_kind(section_id: str, path: Path) -> str:
    if section_id == "sessions":
        return "session"
    if section_id == "facts":
        return "retained-facts"
    if section_id == "graph" and path.name == "nodes.jsonl":
        return "graph-nodes"
    if section_id == "graph" and path.name == "edges.jsonl":
        return "graph-edges"
    return "jsonl"


def _file_description(kind: str) -> str:
    return _KIND_HELP.get(kind, "Memory file.")


def _session_ui_preview(path: Path) -> SessionUiPreview:
    rendered_events: list[str] = []
    rendered_size = 0
    event_count = 0
    truncated = False

    # Read bounded chunks because Codex tool output can make one JSONL event tens of MiB.
    # Embedding those events in the snapshot previously froze the browser when selected.
    with path.open("rb") as source:
        while line := source.readline(_SESSION_EVENT_SOURCE_LIMIT_BYTES + 1):
            if not line.strip():
                continue
            event_count += 1
            if len(line) > _SESSION_EVENT_SOURCE_LIMIT_BYTES and not line.endswith(b"\n"):
                while line and not line.endswith(b"\n"):
                    line = source.readline(_SESSION_EVENT_SOURCE_LIMIT_BYTES + 1)
                rendered = (
                    f"Event {event_count}\n[event omitted from UI preview because its serialized JSON exceeds 256 KiB]"
                )
                truncated = True
            else:
                rendered = _format_session_line(event_count, line.decode("utf-8", errors="replace"))

            separator_size = 7 if rendered_events else 0
            remaining = _SESSION_FILE_CONTENT_LIMIT - rendered_size - separator_size
            if remaining <= 0:
                truncated = True
                continue
            if len(rendered) > remaining:
                rendered_events.append(_truncate_preview(rendered, remaining))
                rendered_size = _SESSION_FILE_CONTENT_LIMIT
                truncated = True
                continue
            rendered_events.append(rendered)
            rendered_size += separator_size + len(rendered)

    content = "\n\n---\n\n".join(rendered_events)
    if truncated:
        content += (
            "\n\n---\n\n"
            "[Session preview truncated to keep the memory tree responsive. "
            "Open the source JSONL file for the complete record.]"
        )
    return SessionUiPreview(
        content=content,
        events=event_count,
        source_bytes=path.stat().st_size,
        truncated=truncated,
    )


def _format_session_line(index: int, line: str) -> str:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return f"Event {index}\nraw: {_truncate_preview(line, _SESSION_EVENT_CONTENT_LIMIT)}"
    if not isinstance(data, Mapping):
        return f"Event {index}\nraw: {_format_json_value(data)}"
    return _format_session_event(index, data)


def _format_session_event(index: int, data: Mapping[str, object]) -> str:
    title = _string_value(data.get("id")) or f"event-{index}"
    lines = [f"Event {index}: {title}"]
    for key in ("timestamp", "session_id", "source", "document_id"):
        value = _string_value(data.get(key))
        if value:
            lines.append(f"{key}: {value}")
    tags = data.get("tags")
    if isinstance(tags, list) and tags:
        lines.append("tags: " + ", ".join(str(tag) for tag in tags))
    metadata = data.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        lines.append("metadata: " + json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    content = _string_value(data.get("content")).strip()
    if content:
        lines.append("")
        lines.append(_truncate_preview(content, _SESSION_EVENT_CONTENT_LIMIT))
    return "\n".join(lines)


def _truncate_preview(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    omitted = len(content) - limit
    return f"{content[:limit]}\n\n[... {omitted} characters omitted from UI preview]"


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _format_json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _read_json_object(path: Path) -> Mapping[str, object] | None:
    parsed = _read_json_value(path)
    return parsed if isinstance(parsed, Mapping) else None


def _read_json_value(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _reflection_kind(data: Mapping[str, object] | None) -> str:
    return _json_kind(data)


def _json_kind(data: object | None) -> str:
    if isinstance(data, list):
        return "json-list"
    if data is None:
        return "json"
    if not isinstance(data, Mapping):
        return "json"
    result_type = data.get("type")
    if result_type == "retain_record":
        return "retain-record"
    if result_type == "reflection_request":
        return "reflection-request"
    if result_type == "reflection_result":
        return "reflection-result"
    if result_type == "observation_candidate":
        return "observation-candidate"
    return "json"


def _json_metadata(data: object | None) -> dict[str, str]:
    if isinstance(data, list):
        return {"items": str(len(data))}
    if not isinstance(data, Mapping):
        return {}
    metadata = {"type": _string_value(data.get("type"))}
    facts = _list_count(data.get("facts"))
    if facts:
        metadata["facts"] = facts
    entities = _list_count(data.get("entities"))
    if entities:
        metadata["entities"] = entities
    relationships = _list_count(data.get("relationships"))
    if relationships:
        metadata["relationships"] = relationships
    proof_count = _int_value(data.get("proof_count"))
    if proof_count:
        metadata["proof_count"] = proof_count
    return {key: value for key, value in metadata.items() if value}


def _reflection_metadata(
    data: Mapping[str, object] | None,
    result_ids_by_request: Mapping[str, list[str]],
) -> dict[str, str]:
    if data is None:
        return {}

    metadata = {"type": _string_value(data.get("type"))}
    request_id = _string_value(data.get("request_id"))
    if request_id:
        metadata["request_id"] = request_id
    result_ids = result_ids_by_request.get(_string_value(data.get("id")), [])
    if result_ids:
        metadata["result_ids"] = ", ".join(result_ids)
    confidence = _confidence_value(data.get("confidence"))
    if confidence:
        metadata["confidence"] = confidence
    lesson = _trajectory_lesson(data.get("trajectory"))
    if not lesson:
        lesson = _trajectory_lesson(data.get("candidate_trajectory"))
    if lesson:
        metadata["lesson"] = lesson
    trigger_reason = _string_value(data.get("trigger_reason"))
    if trigger_reason:
        metadata["trigger_reason"] = trigger_reason
    entry_state = _reflection_entry_state(data)
    if entry_state:
        metadata["entry_state"] = entry_state
    return metadata


def _reflection_result_ids_by_request(
    parsed_files: list[tuple[Path, Mapping[str, object] | None]],
) -> dict[str, list[str]]:
    result_ids_by_request: dict[str, list[str]] = {}
    for _path, data in parsed_files:
        if data is None or data.get("type") != "reflection_result":
            continue
        request_id = _string_value(data.get("request_id"))
        result_id = _string_value(data.get("id"))
        if request_id and result_id:
            result_ids_by_request.setdefault(request_id, []).append(result_id)
    return result_ids_by_request


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _confidence_value(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return ""
    return f"{float(value):.2f}"


def _list_count(value: object) -> str:
    return str(len(value)) if isinstance(value, list) else ""


def _int_value(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return ""
    return str(value)


def _trajectory_lesson(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return _string_value(value.get("lesson"))


def _reflection_entry_state(data: Mapping[str, object]) -> str:
    trajectory = data.get("trajectory")
    if not isinstance(trajectory, Mapping):
        trajectory = data.get("candidate_trajectory")
    if not isinstance(trajectory, Mapping):
        return ""
    return _trajectory_entry_state(trajectory)


def _build_graph(bank_id: str, sections: list[MemoryUiSection]) -> MemoryUiGraph:
    root_id = "bank"
    nodes = [
        MemoryUiGraphNode(id=root_id, label=bank_id, kind="bank", parent_id=""),
        MemoryUiGraphNode(id="memory-files", label="Memory Files", kind="group", parent_id=root_id),
        MemoryUiGraphNode(id="trajectory-samples", label="Reflection Graph", kind="group", parent_id=root_id),
        MemoryUiGraphNode(
            id="trajectory-success", label="Success", kind="sample-group", parent_id="trajectory-samples"
        ),
        MemoryUiGraphNode(
            id="trajectory-negative",
            label="Error / Negative Candidates",
            kind="sample-group",
            parent_id="trajectory-samples",
        ),
        MemoryUiGraphNode(
            id="trajectory-uncertain", label="Uncertain", kind="sample-group", parent_id="trajectory-samples"
        ),
    ]
    for section in sections:
        section_id = f"section-{section.id}"
        nodes.append(
            MemoryUiGraphNode(
                id=section_id,
                label=section.label,
                kind="section",
                parent_id="memory-files",
                metadata={"files": str(len(section.files))},
            )
        )
        for file in section.files:
            file_node_id = f"file-{file.id}"
            nodes.append(
                MemoryUiGraphNode(
                    id=file_node_id,
                    label=file.label,
                    kind=file.kind,
                    parent_id=section_id,
                    file_id=file.id,
                    metadata=file.metadata,
                )
            )
            nodes.extend(_trajectory_graph_nodes(file))
    return MemoryUiGraph(root_id=root_id, nodes=_group_trajectory_sample_entries(nodes))


def _trajectory_graph_nodes(file: MemoryUiFile) -> list[MemoryUiGraphNode]:
    data = _json_object_from_content(file.content)
    if data is None:
        return []
    record_type = data.get("type")
    if record_type == "reflection_request":
        if file.metadata.get("result_ids"):
            return []
        trajectory = data.get("candidate_trajectory")
        sample_status = "uncertain"
    elif record_type == "reflection_result":
        trajectory = data.get("trajectory")
        sample_status = _trajectory_sample_status(data)
    else:
        return []
    if not isinstance(trajectory, Mapping):
        return []

    sample_id = f"trajectory-{_safe_graph_id(_string_value(data.get('id')) or file.id)}"
    nodes = [
        MemoryUiGraphNode(
            id=sample_id,
            label=_string_value(data.get("id")) or file.label,
            kind="trajectory-sample",
            parent_id=f"trajectory-{sample_status}",
            file_id=file.id,
            content=_string_value(trajectory.get("lesson")),
            sample_status=sample_status,
            metadata={
                "request_id": _string_value(data.get("request_id")),
                "session_id": _string_value(data.get("session_id")),
                "confidence": _confidence_value(data.get("confidence")),
                "stage": "candidate" if record_type == "reflection_request" else "evaluated",
                "trigger_reason": _string_value(data.get("trigger_reason")),
                "entry_state": _trajectory_entry_state(trajectory),
            },
        )
    ]
    raw_steps = trajectory.get("steps")
    if isinstance(raw_steps, list) and raw_steps:
        nodes.extend(_branching_trajectory_step_nodes(raw_steps, sample_id, file.id, sample_status))
        return nodes

    parent_id = sample_id
    for step in ("state", "action", "observation", "outcome", "lesson"):
        content = _string_value(trajectory.get(step))
        if not content:
            continue
        node_id = f"{sample_id}-{step}"
        nodes.append(
            MemoryUiGraphNode(
                id=node_id,
                label=step,
                kind="trajectory-step",
                parent_id=parent_id,
                file_id=file.id,
                content=content,
                sample_status=sample_status,
            )
        )
        parent_id = node_id
    return nodes


def _group_trajectory_sample_entries(nodes: list[MemoryUiGraphNode]) -> list[MemoryUiGraphNode]:
    groups: dict[str, list[MemoryUiGraphNode]] = {}
    for node in nodes:
        if node.kind != "trajectory-sample":
            continue
        entry_state = node.metadata.get("entry_state", "")
        if not entry_state:
            continue
        groups.setdefault(f"{node.parent_id}:{entry_state}", []).append(node)

    repeated_groups = {key: samples for key, samples in groups.items() if len(samples) > 1}
    if not repeated_groups:
        return nodes

    group_nodes: list[MemoryUiGraphNode] = []
    parent_by_sample_id: dict[str, str] = {}
    for group_key, samples in sorted(repeated_groups.items()):
        parent_id, entry_state = group_key.split(":", 1)
        group_id = f"{parent_id}-entry-{_safe_graph_id(entry_state)}"
        group_nodes.append(
            MemoryUiGraphNode(
                id=group_id,
                label=entry_state,
                kind="trajectory-entry",
                parent_id=parent_id,
                content=f"{len(samples)} related reflection episodes",
                sample_status=samples[0].sample_status,
                metadata={"episodes": str(len(samples))},
            )
        )
        for sample in samples:
            parent_by_sample_id[sample.id] = group_id

    regrouped_nodes = [*nodes, *group_nodes]
    return [
        node if node.id not in parent_by_sample_id else _replace_graph_node_parent(node, parent_by_sample_id[node.id])
        for node in regrouped_nodes
    ]


def _replace_graph_node_parent(node: MemoryUiGraphNode, parent_id: str) -> MemoryUiGraphNode:
    return MemoryUiGraphNode(
        id=node.id,
        label=node.label,
        kind=node.kind,
        parent_id=parent_id,
        file_id=node.file_id,
        content=node.content,
        sample_status=node.sample_status,
        metadata=node.metadata,
    )


def _trajectory_entry_state(trajectory: Mapping[str, object]) -> str:
    raw_steps = trajectory.get("steps")
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if not isinstance(step, Mapping):
                continue
            if _string_value(step.get("kind")) == "state":
                return _trajectory_step_summary(_string_value(step.get("content")))
    return _trajectory_step_summary(_string_value(trajectory.get("state")))


def _branching_trajectory_step_nodes(
    raw_steps: list[object],
    sample_id: str,
    file_id: str,
    sample_status: str,
) -> list[MemoryUiGraphNode]:
    steps = [step for step in raw_steps if isinstance(step, Mapping)]
    step_ids = {_string_value(step.get("id")) for step in steps}
    nodes: list[MemoryUiGraphNode] = []
    for step in sorted(steps, key=_trajectory_step_sequence):
        step_id = _string_value(step.get("id"))
        if not step_id:
            continue
        parent_step_id = _string_value(step.get("parent_id"))
        parent_id = f"{sample_id}-step-{_safe_graph_id(parent_step_id)}" if parent_step_id in step_ids else sample_id
        status = _trajectory_step_status(_string_value(step.get("status")), sample_status)
        content = _string_value(step.get("content"))
        summary = _trajectory_step_summary(content)
        metadata = {
            "sequence": str(_trajectory_step_sequence(step)),
            "tool_name": _string_value(step.get("tool_name")),
            "correction_of": _string_value(step.get("correction_of")),
            "repeat_count": _positive_int_string(step.get("repeat_count")),
        }
        if summary != content:
            metadata["detail"] = content
        nodes.append(
            MemoryUiGraphNode(
                id=f"{sample_id}-step-{_safe_graph_id(step_id)}",
                label=_string_value(step.get("kind")) or "step",
                kind="trajectory-step",
                parent_id=parent_id,
                file_id=file_id,
                content=summary,
                sample_status=status,
                metadata=metadata,
            )
        )
    return nodes


def _trajectory_step_summary(content: str) -> str:
    cleaned = _clean_trajectory_step_content(content)
    if len(cleaned) <= _TRAJECTORY_STEP_SUMMARY_LIMIT:
        return cleaned
    return f"{cleaned[: _TRAJECTORY_STEP_SUMMARY_LIMIT - 3]}..."


def _clean_trajectory_step_content(content: str) -> str:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, Mapping):
        command = _string_value(parsed.get("cmd"))
        if command:
            return command
        file_path = _string_value(parsed.get("file")) or _string_value(parsed.get("path"))
        if file_path:
            return file_path

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    kept: list[str] = []
    for line in lines:
        if line.startswith(("Chunk ID:", "Wall time:", "Original token count:", "Output:")):
            continue
        if line.startswith("Process exited") or line.startswith("Process running"):
            continue
        kept.append(line)
    return " ".join(kept)


def _trajectory_step_sequence(step: Mapping[str, object]) -> int:
    sequence = step.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        return 0
    return sequence


def _positive_int_string(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 1:
        return ""
    return str(value)


def _trajectory_step_status(status: str, fallback: str) -> str:
    if status == "failed":
        return "negative"
    if status == "uncertain":
        return "uncertain"
    if status == "success":
        return "success"
    return fallback


def _json_object_from_content(content: str) -> Mapping[str, object] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _trajectory_sample_status(data: Mapping[str, object]) -> str:
    confidence = _numeric_confidence(data.get("confidence"))
    if confidence is not None and confidence < 0.5:
        return "negative"

    trajectory = data.get("trajectory")
    if isinstance(trajectory, Mapping) and _contains_negative_signal(trajectory):
        return "negative"

    uncertain_items = data.get("uncertain_items")
    if isinstance(uncertain_items, list) and uncertain_items:
        return "uncertain"

    return "success"


def _numeric_confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _contains_negative_signal(trajectory: Mapping[str, object]) -> bool:
    text = " ".join(
        _string_value(trajectory.get(key)) for key in ("action", "observation", "outcome", "lesson")
    ).lower()
    return any(
        term in text
        for term in (
            "failed",
            "failure",
            "wrong",
            "incorrect",
            "error",
            "negative",
            "skipped validation",
            "失败",
            "错误",
        )
    )


def _safe_graph_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value).strip("-") or "sample"


def _page_download_prefix(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return ""

    marker = "\n---\n"
    end_index = text.find(marker, len("---\n"))
    if end_index == -1:
        return ""
    return text[: end_index + len(marker)]


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>hindsight-lite memory tree</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --soft: #f9fafb;
      --line: #d8dde6;
      --text: #151922;
      --muted: #626c7a;
      --green: #1d7a50;
      --blue: #2563a9;
      --gold: #a56516;
      --violet: #6a4cad;
      --red: #a33d3d;
      --shadow: 0 8px 24px rgba(21, 25, 34, 0.08);
    }
    * { box-sizing: border-box; }
    html {
      height: 100%;
      overflow: hidden;
    }
    body {
      margin: 0;
      height: 100%;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      height: 100vh;
      display: grid;
      grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
      overflow: hidden;
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
      min-height: 0;
    }
    main {
      padding: 18px;
      min-width: 0;
      min-height: 0;
      overflow: auto;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
    }
    .path {
      margin-top: 6px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 16px 0;
    }
    .metric {
      border: 1px solid var(--line);
      background: var(--soft);
      padding: 8px;
      border-radius: 6px;
      min-width: 0;
    }
    .metric strong { display: block; font-size: 16px; }
    .metric span {
      color: var(--muted);
      display: block;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .pipeline {
      display: grid;
      gap: 6px;
      margin: 16px 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
    }
    .pipeline-title {
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .pipeline-flow {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .pipeline-step {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 6px;
      padding: 3px 7px;
      color: var(--text);
      font-weight: 600;
    }
    .section {
      margin-top: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    .section-title {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      color: var(--text);
      font-size: 13px;
      font-weight: 700;
      padding: 10px 10px 2px;
    }
    .section-help {
      color: var(--muted);
      font-size: 12px;
      padding: 0 10px 8px;
      border-bottom: 1px solid var(--line);
    }
    .tree-button {
      width: 100%;
      display: grid;
      grid-template-columns: 10px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: var(--text);
      padding: 8px 10px;
      text-align: left;
      cursor: pointer;
      font: inherit;
    }
    .tree-button:hover,
    .tree-button.active {
      background: #eef3f8;
    }
    .tree-entry-group {
      margin: 8px 0 4px;
      padding-left: 8px;
      border-left: 2px solid var(--line);
    }
    .tree-entry-title {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      margin: 4px 0;
      padding: 5px 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .tree-entry-title span:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
    }
    .kind-jsonl { background: var(--blue); }
    .kind-json { background: var(--violet); }
    .kind-session { background: var(--blue); }
    .kind-retain-record { background: var(--green); }
    .kind-retained-facts { background: var(--green); }
    .kind-json-list { background: var(--violet); }
    .kind-graph-nodes { background: var(--gold); }
    .kind-graph-edges { background: var(--gold); }
    .kind-observation-candidate { background: var(--red); }
    .kind-reflection-request { background: var(--violet); }
    .kind-reflection-result { background: var(--gold); }
    .kind-index { background: var(--blue); }
    .kind-file { background: var(--gold); }
    .label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .pill {
      color: var(--muted);
      font-size: 11px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 1px 6px;
    }
    .viewer {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto auto minmax(320px, auto);
      overflow: visible;
    }
    .viewer-header {
      padding: 12px 16px 8px;
      border-bottom: 1px solid var(--line);
    }
    .file-summary {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: start;
      padding: 8px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--soft);
    }
    .file-summary-text {
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .file-summary-kind {
      color: var(--text);
      font-weight: 700;
      white-space: nowrap;
    }
    .viewer-title-row {
      display: flex;
      gap: 12px;
      align-items: start;
      justify-content: space-between;
    }
    .viewer-header h2 {
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
    }
    .viewer-header .path { margin-top: 4px; }
    .view-switch {
      display: inline-flex;
      gap: 4px;
      padding: 3px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f8faf5;
      flex: 0 0 auto;
    }
    .view-tab {
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      padding: 5px 9px;
    }
    .view-tab.active {
      background: var(--panel);
      color: var(--text);
      box-shadow: 0 1px 3px rgba(24, 32, 27, 0.08);
    }
    .metadata {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 8px 16px;
      border-bottom: 1px solid var(--line);
    }
    .metadata:empty { display: none; }
    .meta {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 4px 9px;
      color: var(--muted);
      font-size: 12px;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 8px 16px;
      border-bottom: 1px solid var(--line);
      align-items: center;
    }
    .toolbar:empty { display: none; }
    .action {
      border: 1px solid var(--line);
      background: #f8faf5;
      color: var(--text);
      border-radius: 8px;
      padding: 7px 10px;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
    }
    .action:hover { background: #edf3e8; }
    .action:disabled {
      cursor: not-allowed;
      color: var(--muted);
      background: #f3f4ef;
    }
    .dirty {
      color: var(--red);
      border-color: rgba(162, 59, 59, 0.35);
    }
    textarea,
    pre {
      margin: 0;
      border: 0;
      width: 100%;
      min-height: 320px;
      padding: 12px 16px;
      color: var(--text);
      background: #ffffff;
      font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace;
      resize: none;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      outline: none;
    }
    .graph-view {
      min-height: 320px;
      overflow: visible;
      padding: 22px;
      background: #fffefb;
    }
    .memory-graph-view {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 280px;
      gap: 14px;
      padding: 14px;
      background: #ffffff;
      min-height: 520px;
    }
    .memory-graph-canvas {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
      min-width: 0;
      overflow: auto;
    }
    .memory-graph-svg {
      display: block;
      min-width: 920px;
      min-height: 560px;
    }
    .memory-edge {
      stroke: #aab5c4;
      stroke-width: 1.2;
      opacity: 0.65;
    }
    .memory-edge.causes {
      stroke: var(--red);
      stroke-width: 1.8;
      opacity: 0.8;
    }
    .memory-edge.co_occurs {
      stroke: var(--gold);
    }
    .memory-node {
      cursor: pointer;
    }
    .memory-node circle {
      stroke: #ffffff;
      stroke-width: 2;
      filter: drop-shadow(0 2px 4px rgba(21, 25, 34, 0.18));
    }
    .memory-node.entity circle { fill: var(--blue); }
    .memory-node.fact circle { fill: var(--green); }
    .memory-node.active circle {
      stroke: var(--red);
      stroke-width: 3;
    }
    .memory-node text {
      fill: var(--text);
      font: 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      paint-order: stroke;
      stroke: #ffffff;
      stroke-width: 3px;
      stroke-linejoin: round;
    }
    .memory-graph-side {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
      padding: 12px;
      min-width: 0;
    }
    .memory-graph-side h3 {
      margin: 0 0 8px;
      font-size: 14px;
    }
    .memory-graph-side p {
      margin: 0 0 10px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .memory-graph-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }
    .structured-view {
      display: grid;
      gap: 12px;
      padding: 12px 16px 18px;
      background: #ffffff;
    }
    .structured-section {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    .structured-section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 9px 11px;
      border-bottom: 1px solid var(--line);
      background: var(--soft);
      font-weight: 700;
    }
    .structured-list {
      display: grid;
      gap: 8px;
      padding: 10px;
    }
    .fact-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #ffffff;
    }
    .fact-text {
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .fact-evidence {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .structured-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .structured-source {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--soft);
      overflow: hidden;
    }
    .structured-source summary {
      cursor: pointer;
      padding: 9px 11px;
      font-weight: 700;
    }
    .structured-source pre {
      border-top: 1px solid var(--line);
      min-height: 0;
      max-height: 460px;
      overflow: auto;
      background: #ffffff;
    }
    .branch-map {
      min-width: 760px;
      margin-bottom: 20px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 4px 14px rgba(24, 32, 27, 0.05);
      overflow: hidden;
    }
    .branch-map-head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .branch-map-title {
      font-weight: 700;
    }
    .branch-flow {
      position: relative;
      display: grid;
      gap: 12px;
      padding: 16px;
    }
    .branch-flow::before {
      content: "";
      position: absolute;
      top: 18px;
      bottom: 18px;
      left: 50%;
      width: 2px;
      background: #cbd8c4;
    }
    .branch-row {
      position: relative;
      display: grid;
      grid-template-columns: minmax(220px, 1fr) 48px minmax(220px, 1fr);
      gap: 12px;
      align-items: center;
      min-height: 76px;
    }
    .branch-row::after {
      content: "";
      position: absolute;
      top: 50%;
      height: 2px;
      background: var(--line);
      transform: translateY(-50%);
    }
    .branch-row.branch-side::after {
      left: 16%;
      right: 50%;
    }
    .branch-row.branch-main::after {
      left: 50%;
      right: 16%;
    }
    .branch-slot {
      min-width: 0;
      z-index: 1;
    }
    .branch-dot {
      z-index: 2;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      border: 3px solid var(--panel);
      background: var(--green);
      box-shadow: 0 0 0 1px var(--line);
      justify-self: center;
    }
    .branch-dot.status-negative { background: var(--red); }
    .branch-dot.status-uncertain { background: var(--gold); }
    .branch-card {
      width: 100%;
      border: 1px solid rgba(31, 122, 76, 0.35);
      border-radius: 8px;
      background: #f8fbf5;
      color: var(--text);
      cursor: pointer;
      font: inherit;
      padding: 10px 12px;
      text-align: left;
      box-shadow: 0 3px 10px rgba(24, 32, 27, 0.05);
    }
    .branch-card:hover { background: #eef6eb; }
    .branch-card.status-negative {
      border-color: rgba(162, 59, 59, 0.42);
      background: #fff8f6;
    }
    .branch-card.status-negative:hover { background: #fff0eb; }
    .branch-card.status-uncertain {
      border-color: rgba(155, 107, 18, 0.42);
      background: #fffaf0;
    }
    .branch-card.status-uncertain:hover { background: #fff4db; }
    .branch-card-label {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      font-weight: 650;
      min-width: 0;
    }
    .branch-card-label span:first-child {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .branch-card-body {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .branch-card-detail {
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .branch-card-detail summary {
      cursor: pointer;
      width: fit-content;
    }
    .branch-card-detail pre {
      margin-top: 7px;
      max-height: 180px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 0;
      padding: 9px;
      background: #fffefb;
      font-size: 11px;
    }
    .graph-tree {
      min-width: 760px;
    }
    .graph-children {
      margin-left: 26px;
      padding-left: 18px;
      border-left: 1px solid var(--line);
    }
    .graph-row {
      position: relative;
      padding: 8px 0;
    }
    .graph-row::before {
      content: "";
      position: absolute;
      left: -18px;
      top: 26px;
      width: 18px;
      height: 1px;
      background: var(--line);
    }
    .graph-tree > .graph-row::before { display: none; }
    .graph-node {
      width: min(680px, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 9px 11px;
      box-shadow: 0 4px 14px rgba(24, 32, 27, 0.05);
    }
    .graph-node.clickable { cursor: pointer; }
    .graph-node.clickable:hover { background: #f8faf5; }
    .graph-node.trajectory-sample {
      border-color: rgba(155, 107, 18, 0.38);
    }
    .graph-node.trajectory-step {
      background: #fbfbf7;
      box-shadow: none;
    }
    .graph-node.status-negative {
      border-color: rgba(162, 59, 59, 0.42);
      background: #fff8f6;
    }
    .graph-node.status-uncertain {
      border-color: rgba(155, 107, 18, 0.42);
      background: #fffaf0;
    }
    .graph-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
    }
    .graph-label {
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .graph-content {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .graph-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 7px;
    }
    .empty {
      padding: 40px;
      color: var(--muted);
    }
    @media (max-width: 760px) {
      .app { grid-template-columns: 1fr; }
      aside {
        border-right: 0;
        border-bottom: 1px solid var(--line);
        max-height: 42vh;
      }
      main { padding: 14px; }
      .viewer { min-height: 58vh; }
      .viewer-title-row { display: block; }
      .file-summary { grid-template-columns: 1fr; }
      .view-switch { margin-top: 12px; }
      .branch-map { min-width: 560px; }
      .branch-row { grid-template-columns: minmax(180px, 1fr) 40px minmax(180px, 1fr); }
      .graph-tree { min-width: 560px; }
      .memory-graph-view { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1 id="bank-title"></h1>
      <div class="path" id="bank-path"></div>
      <div class="summary" id="summary"></div>
      <div class="pipeline">
        <div class="pipeline-title">Retain Model</div>
        <div class="pipeline-flow">
          <span class="pipeline-step">sessions</span><span>source</span>
          <span>→</span><span class="pipeline-step">retains</span><span>extract</span>
          <span>→</span><span class="pipeline-step">facts</span><span>memory</span>
          <span>→</span><span class="pipeline-step">graph</span><span>links</span>
          <span>→</span><span class="pipeline-step">observations</span><span>candidates</span>
        </div>
      </div>
      <div id="tree"></div>
    </aside>
    <main>
      <section class="viewer">
        <div class="viewer-header">
          <div class="viewer-title-row">
            <h2 id="file-title"></h2>
            <div class="view-switch" id="view-switch"></div>
          </div>
          <div class="path" id="file-path"></div>
        </div>
        <div class="metadata" id="metadata"></div>
        <div class="file-summary" id="file-summary"></div>
        <div class="toolbar" id="toolbar"></div>
        <div id="content"></div>
      </section>
    </main>
  </div>
  <script>
    const snapshot = __MEMORY_SNAPSHOT__;
    const files = snapshot.sections.flatMap((section) => section.files);
    let activeId = files[0]?.id || "";
    let activeView = "file";
    const drafts = new Map();

    function render() {
      document.getElementById("bank-title").textContent = snapshot.bank_id;
      document.getElementById("bank-path").textContent = snapshot.bank_path;
      renderSummary();
      renderTree();
      renderViewSwitch();
      renderActiveView();
    }

    function renderSummary() {
      const summary = document.getElementById("summary");
      summary.innerHTML = "";
      snapshot.sections.forEach((section) => {
        const metric = document.createElement("div");
        metric.className = "metric";
        metric.innerHTML = `<strong>${section.files.length}</strong><span>${section.label}</span>`;
        summary.append(metric);
      });
    }

    function renderTree() {
      const tree = document.getElementById("tree");
      tree.innerHTML = "";
      snapshot.sections.forEach((section) => {
        const wrapper = document.createElement("section");
        wrapper.className = "section";
        const title = document.createElement("div");
        title.className = "section-title";
        title.innerHTML = `<span>${section.label}</span><span>${section.files.length}</span>`;
        wrapper.append(title);
        if (section.description) {
          const help = document.createElement("div");
          help.className = "section-help";
          help.textContent = section.description;
          wrapper.append(help);
        }
        renderSectionFiles(wrapper, section);
        tree.append(wrapper);
      });
    }

    function renderSectionFiles(wrapper, section) {
      if (section.id !== "reflections") {
        section.files.forEach((file) => wrapper.append(treeButton(file)));
        return;
      }
      groupedReflectionFiles(section.files).forEach((item) => {
        if (item.files.length === 1) {
          wrapper.append(treeButton(item.files[0]));
          return;
        }
        const group = document.createElement("div");
        group.className = "tree-entry-group";
        const title = document.createElement("div");
        title.className = "tree-entry-title";
        const label = document.createElement("span");
        label.textContent = item.entryState;
        const count = document.createElement("span");
        count.className = "pill";
        count.textContent = `${item.files.length} episodes`;
        title.append(label, count);
        group.append(title);
        item.files.forEach((file) => group.append(treeButton(file)));
        wrapper.append(group);
      });
    }

    function groupedReflectionFiles(files) {
      const groups = new Map();
      files.forEach((file) => {
        const key = file.metadata?.entry_state || file.id;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(file);
      });
      const consumed = new Set();
      const items = [];
      files.forEach((file) => {
        const key = file.metadata?.entry_state || file.id;
        if (consumed.has(key)) return;
        consumed.add(key);
        items.push({ entryState: key, files: groups.get(key) || [file] });
      });
      return items;
    }

    function treeButton(file) {
      const button = document.createElement("button");
      button.className = `tree-button ${file.id === activeId ? "active" : ""}`;
      button.type = "button";
      button.innerHTML = `<span class="dot kind-${file.kind}"></span><span class="label"></span><span class="pill">${file.kind}</span>`;
      button.querySelector(".label").textContent = file.label;
      if (hasDraft(file)) {
        button.querySelector(".pill").textContent = "edited";
        button.querySelector(".pill").classList.add("dirty");
      }
      button.addEventListener("click", () => {
        activeId = file.id;
        renderTree();
        renderActiveView();
      });
      return button;
    }

    function renderViewSwitch() {
      const switcher = document.getElementById("view-switch");
      switcher.innerHTML = "";
      [
        ["file", "File"],
        ["memory-graph", "Memory Graph"],
        ["graph", "Reflection Graph"],
      ].forEach(([mode, label]) => {
        const button = document.createElement("button");
        button.className = `view-tab ${activeView === mode ? "active" : ""}`;
        button.type = "button";
        button.textContent = label;
        button.addEventListener("click", () => {
          activeView = mode;
          renderViewSwitch();
          renderActiveView();
        });
        switcher.append(button);
      });
    }

    function renderActiveView() {
      if (activeView === "memory-graph") {
        renderMemoryGraph();
        return;
      }
      if (activeView === "graph") {
        renderGraph();
        return;
      }
      renderFile();
    }

    function renderFile() {
      const file = files.find((item) => item.id === activeId);
      document.getElementById("file-title").textContent = file ? file.label : "No memory files";
      document.getElementById("file-path").textContent = file ? file.path : "";
      renderMetadata(file);
      renderFileSummary(file);
      renderToolbar(file);
      const content = document.getElementById("content");
      content.innerHTML = "";
      if (!file) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No pages, sessions, reflections, or index files found.";
        content.append(empty);
        return;
      }
      if (file.editable) {
        const editor = document.createElement("textarea");
        editor.value = currentContent(file);
        editor.addEventListener("input", () => {
          drafts.set(file.id, editor.value);
          renderToolbar(file);
          renderTree();
        });
        content.append(editor);
        return;
      }
      const interpreted = renderStructuredMemory(file);
      if (interpreted) {
        content.append(interpreted);
        return;
      }
      const pre = document.createElement("pre");
      pre.textContent = file.content;
      content.append(pre);
    }

    function renderMemoryGraph() {
      const graphData = memoryGraphData();
      document.getElementById("file-title").textContent = "Memory Graph";
      document.getElementById("file-path").textContent = `${snapshot.bank_path}/graph`;
      renderMemoryGraphMetadata(graphData);
      renderMemoryGraphSummary(graphData);
      document.getElementById("toolbar").innerHTML = "";

      const content = document.getElementById("content");
      content.innerHTML = "";
      if (!graphData.nodes.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No retain graph nodes found. Run retain first.";
        content.append(empty);
        return;
      }

      const view = document.createElement("div");
      view.className = "memory-graph-view";
      const canvas = document.createElement("div");
      canvas.className = "memory-graph-canvas";
      const side = document.createElement("div");
      side.className = "memory-graph-side";
      const positions = memoryGraphPositions(graphData.nodes);
      canvas.append(memoryGraphSvg(graphData, positions, side));
      renderMemoryGraphNodeDetails(side, graphData.nodes[0], graphData);
      view.append(canvas, side);
      content.append(view);
    }

    function memoryGraphData() {
      const nodesFile = files.find((file) => file.kind === "graph-nodes");
      const edgesFile = files.find((file) => file.kind === "graph-edges");
      const nodes = nodesFile ? parseJsonLines(nodesFile.content) : [];
      const knownIds = new Set(nodes.map((node) => node.id));
      const edges = (edgesFile ? parseJsonLines(edgesFile.content) : []).filter(
        (edge) => knownIds.has(edge.source_id) && knownIds.has(edge.target_id),
      );
      return { nodes, edges };
    }

    function renderMemoryGraphMetadata(graphData) {
      const metadata = document.getElementById("metadata");
      metadata.innerHTML = "";
      [
        ["nodes", graphData.nodes.length],
        ["edges", graphData.edges.length],
        ["entities", graphData.nodes.filter((node) => node.kind === "entity").length],
        ["facts", graphData.nodes.filter((node) => node.kind === "fact").length],
      ].forEach(([key, value]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = `${key}: ${value}`;
        metadata.append(item);
      });
    }

    function renderMemoryGraphSummary(graphData) {
      const summary = document.getElementById("file-summary");
      summary.innerHTML = "";
      const text = document.createElement("div");
      text.className = "file-summary-text";
      text.textContent = "Retain graph visualization. Blue nodes are entities, green nodes are facts, and edges are retain relationships.";
      const kind = document.createElement("div");
      kind.className = "file-summary-kind";
      kind.textContent = `${graphData.nodes.length} nodes / ${graphData.edges.length} edges`;
      summary.append(text, kind);
    }

    function memoryGraphPositions(nodes) {
      const width = 920;
      const height = 560;
      const centerX = width / 2;
      const centerY = height / 2;
      const entityNodes = nodes.filter((node) => node.kind === "entity");
      const factNodes = nodes.filter((node) => node.kind !== "entity");
      const positions = new Map();
      placeRing(entityNodes, 185, centerX, centerY, positions);
      placeRing(factNodes, 255, centerX, centerY, positions);
      return positions;
    }

    function placeRing(nodes, radius, centerX, centerY, positions) {
      const count = Math.max(nodes.length, 1);
      nodes.forEach((node, index) => {
        const angle = -Math.PI / 2 + (index / count) * Math.PI * 2;
        positions.set(node.id, {
          x: Math.round(centerX + Math.cos(angle) * radius),
          y: Math.round(centerY + Math.sin(angle) * radius),
        });
      });
    }

    function memoryGraphSvg(graphData, positions, side) {
      const namespace = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(namespace, "svg");
      svg.classList.add("memory-graph-svg");
      svg.setAttribute("viewBox", "0 0 920 560");
      const edgeLayer = document.createElementNS(namespace, "g");
      const nodeLayer = document.createElementNS(namespace, "g");
      graphData.edges.forEach((edge) => {
        const source = positions.get(edge.source_id);
        const target = positions.get(edge.target_id);
        if (!source || !target) return;
        const line = document.createElementNS(namespace, "line");
        line.setAttribute("x1", source.x);
        line.setAttribute("y1", source.y);
        line.setAttribute("x2", target.x);
        line.setAttribute("y2", target.y);
        line.classList.add("memory-edge", edge.kind || "edge");
        const title = document.createElementNS(namespace, "title");
        title.textContent = edge.kind || "edge";
        line.append(title);
        edgeLayer.append(line);
      });
      graphData.nodes.forEach((node) => {
        const position = positions.get(node.id);
        if (!position) return;
        const group = document.createElementNS(namespace, "g");
        group.classList.add("memory-node", node.kind === "entity" ? "entity" : "fact");
        group.setAttribute("transform", `translate(${position.x}, ${position.y})`);
        group.addEventListener("click", () => {
          svg.querySelectorAll(".memory-node.active").forEach((item) => item.classList.remove("active"));
          group.classList.add("active");
          renderMemoryGraphNodeDetails(side, node, graphData);
        });
        const circle = document.createElementNS(namespace, "circle");
        circle.setAttribute("r", node.kind === "entity" ? "12" : "10");
        const text = document.createElementNS(namespace, "text");
        text.setAttribute("x", "16");
        text.setAttribute("y", "4");
        text.textContent = compactLabel(node.label || node.id, 30);
        const title = document.createElementNS(namespace, "title");
        title.textContent = node.label || node.id;
        group.append(title, circle, text);
        nodeLayer.append(group);
      });
      svg.append(edgeLayer, nodeLayer);
      const firstNode = nodeLayer.querySelector(".memory-node");
      if (firstNode) firstNode.classList.add("active");
      return svg;
    }

    function renderMemoryGraphNodeDetails(container, node, graphData) {
      container.innerHTML = "";
      const title = document.createElement("h3");
      title.textContent = node.label || node.id || "node";
      const body = document.createElement("p");
      body.textContent = node.kind === "entity" ? "Entity node" : "Fact node";
      container.append(title, body);
      container.append(
        metaRow([
          ["id", node.id],
          ["kind", node.kind],
          ["entity_kind", node.entity_kind],
          ["fact_kind", node.fact_kind],
          ["retain", node.retain_id],
        ]),
      );
      const connected = graphData.edges.filter((edge) => edge.source_id === node.id || edge.target_id === node.id);
      const section = structuredSection(
        "Connected Edges",
        connected.map((edge) =>
          summaryCard(edge.kind || edge.id || "edge", [
            ["from", edge.source_id],
            ["to", edge.target_id],
            ["facts", Array.isArray(edge.fact_ids) ? edge.fact_ids.length : ""],
          ]),
        ),
      );
      container.append(section);
      const legend = document.createElement("div");
      legend.className = "memory-graph-legend";
      [["entity", "blue"], ["fact", "green"], ["causes", "red"], ["co_occurs", "gold"]].forEach(([label]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = label;
        legend.append(item);
      });
      container.append(legend);
    }

    function compactLabel(value, limit) {
      if (!value || value.length <= limit) return value || "";
      return `${value.slice(0, limit - 3)}...`;
    }

    function renderStructuredMemory(file) {
      if (file.kind === "retain-record") return renderRetainRecord(file);
      if (file.kind === "retained-facts") return renderRetainedFacts(file);
      return null;
    }

    function renderRetainRecord(file) {
      const record = parseJsonObject(file.content);
      if (!record) return null;
      const view = structuredView();
      view.append(
        structuredSection("Retain", [
          summaryCard(record.id || file.label, [
            ["session", record.session_id],
            ["mode", record.extraction_mode],
            ["mention_time", record.mention_time],
            ["source_event", record.source_event_id],
            ["mission", record.retain_mission],
          ]),
        ]),
      );
      view.append(structuredSection("Facts", (record.facts || []).map(factCard)));
      view.append(structuredSection("Entities", (record.entities || []).map(entityCard)));
      view.append(structuredSection("Relationships", (record.relationships || []).map(relationshipCard)));
      if (Array.isArray(record.security_events) && record.security_events.length) {
        view.append(structuredSection("Security Events", record.security_events.map(securityEventCard)));
      }
      view.append(sourceDetails(file.content, "Source JSON"));
      return view;
    }

    function renderRetainedFacts(file) {
      const facts = parseJsonLines(file.content);
      if (!facts.length) return null;
      const view = structuredView();
      view.append(structuredSection("Extracted Facts", facts.map(factCard)));
      view.append(sourceDetails(file.content, "Source JSONL"));
      return view;
    }

    function structuredView() {
      const view = document.createElement("div");
      view.className = "structured-view";
      return view;
    }

    function structuredSection(title, children) {
      const section = document.createElement("section");
      section.className = "structured-section";
      const head = document.createElement("div");
      head.className = "structured-section-head";
      const label = document.createElement("span");
      label.textContent = title;
      const count = document.createElement("span");
      count.className = "pill";
      count.textContent = String(children.length);
      head.append(label, count);
      const list = document.createElement("div");
      list.className = "structured-list";
      if (children.length) {
        children.forEach((child) => list.append(child));
      } else {
        const empty = document.createElement("div");
        empty.className = "fact-evidence";
        empty.textContent = "No items extracted.";
        list.append(empty);
      }
      section.append(head, list);
      return section;
    }

    function summaryCard(title, entries) {
      const card = document.createElement("div");
      card.className = "fact-card";
      const text = document.createElement("div");
      text.className = "fact-text";
      text.textContent = title || "retain";
      card.append(text, metaRow(entries));
      return card;
    }

    function factCard(fact) {
      const card = document.createElement("div");
      card.className = "fact-card";
      const text = document.createElement("div");
      text.className = "fact-text";
      text.textContent = fact.text || fact.evidence || fact.id || "fact";
      card.append(text);
      const entries = [
        ["kind", fact.kind],
        ["role", fact.source_role],
        ["occurred", fact.occurred_at],
        ["mentioned", fact.mentioned_at],
        ["emotion", fact.emotion],
        ["entities", Array.isArray(fact.entity_ids) ? fact.entity_ids.length : ""],
      ];
      card.append(metaRow(entries));
      if (fact.reasoning) card.append(evidenceLine(`reasoning: ${fact.reasoning}`));
      if (fact.evidence && fact.evidence !== fact.text) card.append(evidenceLine(`evidence: ${fact.evidence}`));
      return card;
    }

    function entityCard(entity) {
      return summaryCard(entity.name || entity.id || "entity", [
        ["kind", entity.kind],
        ["aliases", Array.isArray(entity.aliases) ? entity.aliases.length : ""],
        ["mentions", Array.isArray(entity.mentions) ? entity.mentions.length : ""],
      ]);
    }

    function relationshipCard(relationship) {
      return summaryCard(relationship.kind || relationship.id || "relationship", [
        ["from", relationship.source_entity_id],
        ["to", relationship.target_entity_id],
        ["facts", Array.isArray(relationship.fact_ids) ? relationship.fact_ids.length : ""],
      ]);
    }

    function securityEventCard(event) {
      const card = summaryCard(event.detector || "security", [
        ["severity", event.severity],
        ["receipt", event.receipt_uri],
      ]);
      if (event.message) card.append(evidenceLine(event.message));
      if (event.evidence) card.append(evidenceLine(`evidence: ${event.evidence}`));
      return card;
    }

    function metaRow(entries) {
      const row = document.createElement("div");
      row.className = "structured-meta";
      entries.filter((entry) => entry[1] !== undefined && entry[1] !== null && entry[1] !== "").forEach(([key, value]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = `${key}: ${value}`;
        row.append(item);
      });
      return row;
    }

    function evidenceLine(text) {
      const line = document.createElement("div");
      line.className = "fact-evidence";
      line.textContent = text;
      return line;
    }

    function sourceDetails(content, title) {
      const details = document.createElement("details");
      details.className = "structured-source";
      const summary = document.createElement("summary");
      summary.textContent = title;
      const pre = document.createElement("pre");
      pre.textContent = content;
      details.append(summary, pre);
      return details;
    }

    function parseJsonObject(content) {
      try {
        const parsed = JSON.parse(content);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : null;
      } catch (_error) {
        return null;
      }
    }

    function parseJsonLines(content) {
      return content
        .split("\\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          try {
            return JSON.parse(line);
          } catch (_error) {
            return null;
          }
        })
        .filter((item) => item && typeof item === "object" && !Array.isArray(item));
    }

    function renderGraph() {
      const graph = graphForActiveFile(snapshot.graph);
      const activeFile = files.find((item) => item.id === activeId);
      const focusedSample = graph?.nodes.find((node) => node.kind === "trajectory-sample" && node.file_id === activeId);
      document.getElementById("file-title").textContent = focusedSample
        ? `Reflection: ${activeFile?.label || focusedSample.label}`
        : "Reflection Graph";
      document.getElementById("file-path").textContent = focusedSample ? activeFile?.path || "" : snapshot.bank_path;
      renderGraphMetadata(graph);
      renderGraphSummary(graph, focusedSample);
      document.getElementById("toolbar").innerHTML = "";

      const content = document.getElementById("content");
      content.innerHTML = "";
      if (!graph || !graph.nodes.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "No graph nodes found.";
        content.append(empty);
        return;
      }

      const view = document.createElement("div");
      view.className = "graph-view";
      const branchMap = renderTrajectoryBranchMap(graph);
      if (branchMap) {
        view.append(branchMap);
        content.append(view);
        return;
      }
      const tree = document.createElement("div");
      tree.className = "graph-tree";
      tree.append(graphRow(graph.root_id, graphNodesByParent(graph.nodes)));
      view.append(tree);
      content.append(view);
    }

    function graphForActiveFile(graph) {
      if (!graph) return null;
      const sample = graph.nodes.find((node) => node.kind === "trajectory-sample" && node.file_id === activeId);
      if (!sample) {
        return {
          root_id: graph.root_id,
          nodes: graph.nodes.filter(
            (node) =>
              node.kind === "bank" ||
              node.id === "trajectory-samples" ||
              node.kind === "sample-group" ||
              node.kind === "trajectory-sample",
          ),
        };
      }

      const childIds = new Map();
      graph.nodes.forEach((node) => {
        if (!childIds.has(node.parent_id)) childIds.set(node.parent_id, []);
        childIds.get(node.parent_id).push(node.id);
      });
      const visibleIds = new Set([sample.id]);
      const pending = [sample.id];
      while (pending.length) {
        const parentId = pending.pop();
        (childIds.get(parentId) || []).forEach((childId) => {
          visibleIds.add(childId);
          pending.push(childId);
        });
      }
      const focusedNodes = graph.nodes.filter((node) => visibleIds.has(node.id));
      return {
        root_id: sample.id,
        nodes: [sample, ...relevantTrajectorySteps(focusedNodes)],
      };
    }

    function relevantTrajectorySteps(nodes) {
      const allSteps = nodes.filter((node) => node.kind === "trajectory-step");
      const correctionIds = new Set(allSteps.filter((node) => node.metadata?.correction_of).map((node) => node.id));
      return allSteps.filter(
        (node) =>
          node.sample_status === "negative" ||
          node.metadata?.correction_of ||
          correctionIds.has(node.parent_id) ||
          node.label === "outcome" ||
          (node.label === "state" && !node.content.includes("<environment_context>")),
      );
    }

    function renderTrajectoryBranchMap(graph) {
      const sample = graph.nodes.find((node) => node.kind === "trajectory-sample" && node.file_id === activeId);
      const steps = graph.nodes
        .filter((node) => node.kind === "trajectory-step")
        .sort((left, right) => Number(left.metadata?.sequence || 0) - Number(right.metadata?.sequence || 0));
      if (!sample || !steps.length) return null;

      const branchMap = document.createElement("section");
      branchMap.className = "branch-map";

      const failures = steps.filter((node) => node.sample_status === "negative");
      const corrections = steps.filter((node) => node.metadata?.correction_of);
      const head = document.createElement("div");
      head.className = "branch-map-head";
      const title = document.createElement("div");
      title.className = "branch-map-title";
      title.textContent = "Reflection Branch";
      const count = document.createElement("span");
      count.className = "meta";
      count.textContent = `${failures.length} failed nodes / ${corrections.length} corrections`;
      head.append(title, count);
      branchMap.append(head);

      const flow = document.createElement("div");
      flow.className = "branch-flow";
      steps.forEach((step) => {
        const branchType = step.sample_status === "negative" ? "side" : "main";
        flow.append(branchRow(step, branchType));
      });
      branchMap.append(flow);
      return branchMap;
    }

    function branchRow(node, branchType) {
      const row = document.createElement("div");
      row.className = `branch-row branch-${branchType}`;
      const left = document.createElement("div");
      left.className = "branch-slot";
      const dot = document.createElement("span");
      dot.className = `branch-dot status-${node.sample_status || "success"}`;
      const right = document.createElement("div");
      right.className = "branch-slot";

      if (branchType === "side") {
        left.append(branchCard(node, "failed branch"));
      } else {
        right.append(branchCard(node, node.metadata?.correction_of ? "correction" : "correct path"));
      }
      row.append(left, dot, right);
      return row;
    }

    function branchCard(node, laneLabel) {
      const card = document.createElement("div");
      card.className = `branch-card status-${node.sample_status || "success"}`;
      card.role = "button";
      card.tabIndex = 0;
      card.addEventListener("click", () => {
        activeId = node.file_id;
        activeView = "file";
        renderTree();
        renderViewSwitch();
        renderActiveView();
      });
      card.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        card.click();
      });
      const label = document.createElement("div");
      label.className = "branch-card-label";
      const name = document.createElement("span");
      name.textContent =
        node.metadata?.tool_name ||
        (node.label === "observation" ? (node.sample_status === "negative" ? "failure" : "result") : node.label);
      const status = document.createElement("span");
      status.className = "pill";
      status.textContent = laneLabel;
      label.append(name, status);
      card.append(label);
      if (node.content) {
        const body = document.createElement("div");
        body.className = "branch-card-body";
        body.textContent = branchContent(node.content);
        card.append(body);
      }
      if (node.metadata?.detail) {
        const details = document.createElement("details");
        details.className = "branch-card-detail";
        details.addEventListener("click", (event) => event.stopPropagation());
        const summary = document.createElement("summary");
        summary.textContent = "Details";
        const pre = document.createElement("pre");
        pre.textContent = node.metadata.detail;
        details.append(summary, pre);
        card.append(details);
      }
      return card;
    }

    function branchContent(content) {
      let text = content;
      try {
        const parsed = JSON.parse(text);
        text = parsed.cmd || parsed.file || parsed.path || text;
      } catch (_error) {
        const commandMatch = text.match(/"cmd":\\s*"([^"]+)"/);
        if (commandMatch) text = commandMatch[1];
      }
      text = text
        .replace(/^Chunk ID:.*$/gm, "")
        .replace(/^Wall time:.*$/gm, "")
        .replace(/^Process (?:exited|running).*$/gm, "")
        .replace(/^Original token count:.*$/gm, "")
        .replace(/^Output:\\s*$/gm, "")
        .split("\\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\\n");
      if (text.length <= 260) return text;
      return `${text.slice(0, 257)}...`;
    }

    function renderGraphMetadata(graph) {
      const metadata = document.getElementById("metadata");
      metadata.innerHTML = "";
      if (!graph) return;
      const focused = graph.nodes.some((node) => node.kind === "trajectory-step");
      const counts = [
        ["nodes", graph.nodes.length],
        ["trajectories", graph.nodes.filter((node) => node.kind === "trajectory-sample").length],
        [
          focused ? "failed" : "negative",
          graph.nodes.filter(
            (node) =>
              node.sample_status === "negative" &&
              node.kind === (focused ? "trajectory-step" : "trajectory-sample"),
          ).length,
        ],
      ];
      counts.forEach(([key, value]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = `${key}: ${value}`;
        metadata.append(item);
      });
    }

    function renderFileSummary(file) {
      const summary = document.getElementById("file-summary");
      summary.innerHTML = "";
      if (!file) return;
      const text = document.createElement("div");
      text.className = "file-summary-text";
      text.textContent = file.description || "Memory file.";
      const kind = document.createElement("div");
      kind.className = "file-summary-kind";
      kind.textContent = file.kind;
      summary.append(text, kind);
    }

    function renderGraphSummary(graph, focusedSample) {
      const summary = document.getElementById("file-summary");
      summary.innerHTML = "";
      const text = document.createElement("div");
      text.className = "file-summary-text";
      text.textContent = focusedSample
        ? "Focused reflection trajectory. This view shows failed branches, corrections, and outcome nodes."
        : "Reflection-only graph overview. Retain graph data lives in graph/nodes.jsonl and graph/edges.jsonl.";
      const kind = document.createElement("div");
      kind.className = "file-summary-kind";
      kind.textContent = graph ? `${graph.nodes.length} nodes` : "0 nodes";
      summary.append(text, kind);
    }

    function graphNodesByParent(nodes) {
      const groups = new Map();
      nodes.forEach((node) => {
        const parent = node.parent_id || "";
        if (!groups.has(parent)) groups.set(parent, []);
        groups.get(parent).push(node);
      });
      return groups;
    }

    function graphRow(nodeId, groups) {
      const node = snapshot.graph.nodes.find((item) => item.id === nodeId);
      const row = document.createElement("div");
      row.className = "graph-row";
      if (!node) return row;
      row.append(graphNode(node));
      const children = groups.get(node.id) || [];
      if (children.length) {
        const wrapper = document.createElement("div");
        wrapper.className = "graph-children";
        children.forEach((child) => wrapper.append(graphRow(child.id, groups)));
        row.append(wrapper);
      }
      return row;
    }

    function graphNode(node) {
      const element = document.createElement("div");
      element.className = `graph-node ${node.kind} ${node.sample_status ? `status-${node.sample_status}` : ""}`;
      if (node.file_id) {
        element.classList.add("clickable");
        element.addEventListener("click", (event) => {
          event.stopPropagation();
          activeId = node.file_id;
          activeView = "file";
          renderTree();
          renderViewSwitch();
          renderActiveView();
        });
      }
      const head = document.createElement("div");
      head.className = "graph-head";
      const label = document.createElement("div");
      label.className = "graph-label";
      label.textContent = node.label;
      const kind = document.createElement("span");
      kind.className = "pill";
      kind.textContent = node.sample_status || node.kind;
      head.append(label, kind);
      element.append(head);
      if (node.content) {
        const body = document.createElement("div");
        body.className = "graph-content";
        body.textContent = node.content;
        element.append(body);
      }
      const metadata = Object.entries(node.metadata || {}).filter((entry) => entry[1]);
      if (metadata.length) {
        const meta = document.createElement("div");
        meta.className = "graph-meta";
        metadata.forEach(([key, value]) => {
          const item = document.createElement("span");
          item.className = "meta";
          item.textContent = `${key}: ${value}`;
          meta.append(item);
        });
        element.append(meta);
      }
      return element;
    }

    function renderMetadata(file) {
      const metadata = document.getElementById("metadata");
      metadata.innerHTML = "";
      if (!file) return;
      Object.entries(file.metadata || {}).filter((entry) => entry[1]).forEach(([key, value]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = `${key}: ${value}`;
        metadata.append(item);
      });
    }

    function renderToolbar(file) {
      const toolbar = document.getElementById("toolbar");
      toolbar.innerHTML = "";
      if (!file || !file.editable) return;

      if (snapshot.save_url) {
        const save = document.createElement("button");
        save.className = "action";
        save.type = "button";
        save.textContent = "Save page";
        save.disabled = !hasDraft(file);
        save.addEventListener("click", () => savePage(file, save));
        toolbar.append(save);
      }

      const download = document.createElement("button");
      download.className = "action";
      download.type = "button";
      download.textContent = "Download Markdown";
      download.addEventListener("click", () => downloadMarkdown(file));
      toolbar.append(download);

      const reset = document.createElement("button");
      reset.className = "action";
      reset.type = "button";
      reset.textContent = "Reset changes";
      reset.disabled = !hasDraft(file);
      reset.addEventListener("click", () => {
        drafts.delete(file.id);
        renderTree();
        renderActiveView();
      });
      toolbar.append(reset);

      if (hasDraft(file)) {
        const badge = document.createElement("span");
        badge.className = "meta dirty";
        badge.textContent = "Unsaved draft";
        toolbar.append(badge);
      }
    }

    function hasDraft(file) {
      return drafts.has(file.id) && drafts.get(file.id) !== file.content;
    }

    function currentContent(file) {
      return drafts.has(file.id) ? drafts.get(file.id) : file.content;
    }

    async function savePage(file, button) {
      button.disabled = true;
      button.textContent = "Saving...";
      try {
        const pageId = file.id.replace(/^page:/, "");
        const response = await fetch(`${snapshot.save_url}/${encodeURIComponent(pageId)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: currentContent(file) }),
        });
        if (!response.ok) {
          throw new Error(await response.text());
        }
        file.content = currentContent(file);
        drafts.delete(file.id);
        renderTree();
        button.textContent = "Saved";
      } catch (error) {
        button.disabled = false;
        button.textContent = "Save failed";
        button.title = String(error);
      }
    }

    function downloadMarkdown(file) {
      const body = currentContent(file).replace(/\\s+$/u, "");
      const text = `${file.download_prefix || ""}${body}\n`;
      const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.download_name || `${file.label}.md`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    render();
  </script>
</body>
</html>
"""
