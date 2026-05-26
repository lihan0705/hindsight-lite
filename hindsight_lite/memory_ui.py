from __future__ import annotations

import json
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


@dataclass(frozen=True)
class MemoryUiSection:
    id: str
    label: str
    files: list[MemoryUiFile]


@dataclass(frozen=True)
class MemoryUiSnapshot:
    bank_id: str
    bank_path: str
    sections: list[MemoryUiSection]


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
    return MemoryUiSnapshot(
        bank_id=store.paths.bank_id,
        bank_path=str(store.paths.bank_dir),
        sections=[
            _pages_section(store),
            _jsonl_section("sessions", "Sessions", store.paths.sessions_dir),
            _json_section("reflections", "Reflections", store.paths.reflections_dir),
            _raw_section("index", "Index", store.paths.index_dir),
        ],
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


def _json_section(section_id: str, label: str, directory: Path) -> MemoryUiSection:
    files: list[MemoryUiFile] = []
    for path in sorted(directory.glob("*.json")):
        files.append(
            MemoryUiFile(
                id=f"{section_id}:{path.name}",
                label=path.name,
                kind="json",
                path=str(path),
                content=_format_json_file(path),
            )
        )
    return MemoryUiSection(id=section_id, label=label, files=files)


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


def _format_json_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)


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
      grid-template-rows: auto auto minmax(320px, 1fr);
      overflow: hidden;
    }
    .viewer-header {
      padding: 18px 20px 12px;
      border-bottom: 1px solid var(--line);
    }
    .viewer-header h2 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
    }
    .viewer-header .path { margin-top: 8px; }
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
    .empty {
      padding: 40px;
      color: var(--muted);
    }
    @media (max-width: 760px) {
      .app { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { padding: 14px; }
      .viewer { min-height: 70vh; }
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
          <h2 id="file-title"></h2>
          <div class="path" id="file-path"></div>
        </div>
        <div class="metadata" id="metadata"></div>
        <div id="content"></div>
      </section>
    </main>
  </div>
  <script>
    const snapshot = __MEMORY_SNAPSHOT__;
    const files = snapshot.sections.flatMap((section) => section.files);
    let activeId = files[0]?.id || "";

    function render() {
      document.getElementById("bank-title").textContent = snapshot.bank_id;
      document.getElementById("bank-path").textContent = snapshot.bank_path;
      renderSummary();
      renderTree();
      renderFile();
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
      button.addEventListener("click", () => {
        activeId = file.id;
        renderTree();
        renderFile();
      });
      return button;
    }

    function renderFile() {
      const file = files.find((item) => item.id === activeId);
      document.getElementById("file-title").textContent = file ? file.label : "No memory files";
      document.getElementById("file-path").textContent = file ? file.path : "";
      renderMetadata(file);
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
        editor.value = file.content;
        content.append(editor);
        return;
      }
      const pre = document.createElement("pre");
      pre.textContent = file.content;
      content.append(pre);
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

    render();
  </script>
</body>
</html>
"""
