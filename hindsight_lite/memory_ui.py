from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hindsight_lite.store import LocalMemoryStore


@dataclass(frozen=True)
class MemoryUiFile:
    id: str
    label: str
    kind: str
    path: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    editable: bool = False
    download_name: str = ""
    download_prefix: str = ""


@dataclass(frozen=True)
class MemoryUiSection:
    id: str
    label: str
    files: list[MemoryUiFile]


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


def write_memory_ui(store: LocalMemoryStore, output_path: Path | None = None) -> Path:
    path = output_path or store.paths.bank_dir / "memory-tree.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_memory_ui(store), encoding="utf-8")
    return path


def render_memory_ui(store: LocalMemoryStore) -> str:
    snapshot = _build_snapshot(store)
    payload = _script_safe_json(snapshot)
    return _HTML_TEMPLATE.replace("__MEMORY_SNAPSHOT__", payload)


def _script_safe_json(snapshot: MemoryUiSnapshot) -> str:
    payload = json.dumps(asdict(snapshot), ensure_ascii=False)
    return payload.replace("</", "<\\/")


def _build_snapshot(store: LocalMemoryStore) -> MemoryUiSnapshot:
    sections = [
        _pages_section(store),
        _jsonl_section("sessions", "Sessions", store.paths.sessions_dir),
        _reflections_section(store.paths.reflections_dir),
        _raw_section("index", "Index", store.paths.index_dir),
    ]
    return MemoryUiSnapshot(
        bank_id=store.paths.bank_id,
        bank_path=str(store.paths.bank_dir),
        sections=sections,
        graph=_build_graph(store.paths.bank_id, sections),
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
                editable=True,
                download_name=Path(page.path).name,
                download_prefix=_page_download_prefix(Path(page.path)),
            )
        )
    return MemoryUiSection(id="pages", label="Pages", files=files)


def _jsonl_section(section_id: str, label: str, directory: Path) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for path in sorted(directory.glob("*.jsonl")):
        content = path.read_text(encoding="utf-8")
        files.append(
            MemoryUiFile(
                id=f"{section_id}:{path.name}",
                label=path.name,
                kind="jsonl",
                path=str(path),
                content=content,
                metadata={"events": str(_count_jsonl_lines(content))},
            )
        )
    return MemoryUiSection(id=section_id, label=label, files=files)


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
        )
        for path, data in parsed_files
    ]
    return MemoryUiSection(id="reflections", label="Reflections", files=files)


def _raw_section(section_id: str, label: str, directory: Path) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for path in sorted(item for item in directory.iterdir() if item.is_file()):
        files.append(
            MemoryUiFile(
                id=f"{section_id}:{path.name}",
                label=path.name,
                kind="file",
                path=str(path),
                content=path.read_text(encoding="utf-8"),
            )
        )
    return MemoryUiSection(id=section_id, label=label, files=files)


def _count_jsonl_lines(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.strip())


def _format_json_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _read_json_object(path: Path) -> Mapping[str, object] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _reflection_kind(data: Mapping[str, object] | None) -> str:
    if data is None:
        return "json"
    result_type = data.get("type")
    if result_type == "reflection_request":
        return "reflection-request"
    if result_type == "reflection_result":
        return "reflection-result"
    return "json"


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
    if lesson:
        metadata["lesson"] = lesson
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


def _trajectory_lesson(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return _string_value(value.get("lesson"))


def _build_graph(bank_id: str, sections: list[MemoryUiSection]) -> MemoryUiGraph:
    root_id = "bank"
    nodes = [
        MemoryUiGraphNode(id=root_id, label=bank_id, kind="bank", parent_id=""),
        MemoryUiGraphNode(id="memory-files", label="Memory Files", kind="group", parent_id=root_id),
        MemoryUiGraphNode(id="trajectory-samples", label="Trajectory Samples", kind="group", parent_id=root_id),
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
    return MemoryUiGraph(root_id=root_id, nodes=nodes)


def _trajectory_graph_nodes(file: MemoryUiFile) -> list[MemoryUiGraphNode]:
    data = _json_object_from_content(file.content)
    if data is None or data.get("type") != "reflection_result":
        return []
    trajectory = data.get("trajectory")
    if not isinstance(trajectory, Mapping):
        return []

    sample_status = _trajectory_sample_status(data)
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
            },
        )
    ]
    for step in ("state", "action", "observation", "outcome", "lesson"):
        content = _string_value(trajectory.get(step))
        if not content:
            continue
        nodes.append(
            MemoryUiGraphNode(
                id=f"{sample_id}-{step}",
                label=step,
                kind="trajectory-step",
                parent_id=sample_id,
                file_id=file.id,
                content=content,
                sample_status=sample_status,
            )
        )
    return nodes


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
      --bg: #f7f7f3;
      --panel: #ffffff;
      --line: #d9ded2;
      --text: #18201b;
      --muted: #667065;
      --green: #1f7a4c;
      --blue: #245f9f;
      --gold: #9b6b12;
      --violet: #6848a8;
      --red: #a23b3b;
      --shadow: 0 10px 30px rgba(24, 32, 27, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #fbfbf7;
      padding: 20px;
    }
    main { padding: 24px; min-width: 0; }
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
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 18px 0 22px;
    }
    .metric {
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 10px;
      border-radius: 8px;
      min-width: 0;
    }
    .metric strong { display: block; font-size: 18px; }
    .metric span {
      color: var(--muted);
      display: block;
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .section {
      margin-top: 16px;
    }
    .section-title {
      display: flex;
      justify-content: space-between;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
      margin-bottom: 6px;
    }
    .tree-button {
      width: 100%;
      display: grid;
      grid-template-columns: 10px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: var(--text);
      padding: 8px 10px;
      text-align: left;
      cursor: pointer;
      font: inherit;
    }
    .tree-button:hover,
    .tree-button.active {
      background: #eef3e9;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--green);
    }
    .kind-jsonl { background: var(--blue); }
    .kind-json { background: var(--violet); }
    .kind-reflection-request { background: var(--violet); }
    .kind-reflection-result { background: var(--gold); }
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
      min-height: calc(100vh - 48px);
      display: grid;
      grid-template-rows: auto auto auto minmax(320px, 1fr);
      overflow: hidden;
    }
    .viewer-header {
      padding: 18px 20px 12px;
      border-bottom: 1px solid var(--line);
    }
    .viewer-title-row {
      display: flex;
      gap: 12px;
      align-items: start;
      justify-content: space-between;
    }
    .viewer-header h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }
    .viewer-header .path { margin-top: 8px; }
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
      gap: 8px;
      padding: 12px 20px;
      border-bottom: 1px solid var(--line);
      min-height: 48px;
    }
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
      padding: 12px 20px;
      border-bottom: 1px solid var(--line);
      min-height: 54px;
      align-items: center;
    }
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
      min-height: 100%;
      padding: 20px;
      color: var(--text);
      background: #fffefb;
      font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace;
      resize: none;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      outline: none;
    }
    .graph-view {
      min-height: 100%;
      overflow: auto;
      padding: 22px;
      background: #fffefb;
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
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { padding: 14px; }
      .viewer { min-height: 70vh; }
      .viewer-title-row { display: block; }
      .view-switch { margin-top: 12px; }
      .graph-tree { min-width: 560px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1 id="bank-title"></h1>
      <div class="path" id="bank-path"></div>
      <div class="summary" id="summary"></div>
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
        section.files.forEach((file) => wrapper.append(treeButton(file)));
        tree.append(wrapper);
      });
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
        activeView = "file";
        renderTree();
        renderActiveView();
      });
      return button;
    }

    function renderViewSwitch() {
      const switcher = document.getElementById("view-switch");
      switcher.innerHTML = "";
      ["file", "graph"].forEach((mode) => {
        const button = document.createElement("button");
        button.className = `view-tab ${activeView === mode ? "active" : ""}`;
        button.type = "button";
        button.textContent = mode === "file" ? "File" : "Graph";
        button.addEventListener("click", () => {
          activeView = mode;
          renderViewSwitch();
          renderActiveView();
        });
        switcher.append(button);
      });
    }

    function renderActiveView() {
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
      const pre = document.createElement("pre");
      pre.textContent = file.content;
      content.append(pre);
    }

    function renderGraph() {
      const graph = snapshot.graph;
      document.getElementById("file-title").textContent = "Memory Graph";
      document.getElementById("file-path").textContent = snapshot.bank_path;
      renderGraphMetadata(graph);
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
      const tree = document.createElement("div");
      tree.className = "graph-tree";
      tree.append(graphRow(graph.root_id, graphNodesByParent(graph.nodes)));
      view.append(tree);
      content.append(view);
    }

    function renderGraphMetadata(graph) {
      const metadata = document.getElementById("metadata");
      metadata.innerHTML = "";
      if (!graph) return;
      const counts = [
        ["nodes", graph.nodes.length],
        ["trajectories", graph.nodes.filter((node) => node.kind === "trajectory-sample").length],
        ["negative", graph.nodes.filter((node) => node.sample_status === "negative" && node.kind === "trajectory-sample").length],
      ];
      counts.forEach(([key, value]) => {
        const item = document.createElement("span");
        item.className = "meta";
        item.textContent = `${key}: ${value}`;
        metadata.append(item);
      });
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
