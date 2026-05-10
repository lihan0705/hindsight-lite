# Codex Local Memory Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Codex-first local memory runtime for `agent_knowledge_retain`, `agent_knowledge_recall`, `agent_knowledge_reflect`, `agent_knowledge_list_pages`, and `agent_knowledge_get_page`.

**Architecture:** Add a small local Python core under `hindsight_lite/` that stores memory in Markdown/JSONL under `~/.hindsight-lite`. Keep Codex hook entrypoints but replace HTTP/daemon calls with local core calls.

**Tech Stack:** Python 3.11+ standard library, pytest, existing Codex hook scripts, Markdown frontmatter parsing implemented locally.

---

## File Map

- Create `hindsight_lite/__init__.py`: package exports.
- Create `hindsight_lite/__main__.py`: `python -m hindsight_lite` entrypoint.
- Create `hindsight_lite/models.py`: dataclasses for memory events, pages, recall results, and reflection packets.
- Create `hindsight_lite/paths.py`: safe bank path resolution.
- Create `hindsight_lite/store.py`: JSONL append/read and Markdown page list/get.
- Create `hindsight_lite/scoring.py`: deterministic local text scoring.
- Create `hindsight_lite/formatting.py`: Codex `<hindsight_memories>` formatter.
- Create `hindsight_lite/reflection.py`: reflection packet builder and request persistence.
- Create `hindsight_lite/cli.py`: `agent_knowledge_*` commands.
- Create `tests/hindsight_lite/test_store.py`.
- Create `tests/hindsight_lite/test_recall.py`.
- Create `tests/hindsight_lite/test_reflection.py`.
- Create `tests/hindsight_lite/test_cli.py`.
- Modify `hindsight-integrations/codex/scripts/recall.py`: local recall adapter.
- Modify `hindsight-integrations/codex/scripts/retain.py`: local retain adapter.
- Modify `hindsight-integrations/codex/scripts/session_start.py`: local directory init.
- Modify `hindsight-integrations/codex/scripts/lib/config.py`: local-only config keys.
- Modify `hindsight-integrations/codex/scripts/lib/bank.py`: remove mission setup dependency.
- Modify `hindsight-integrations/codex/tests/test_hooks.py`: assert local behavior, no HTTP.

## Task 1: Local Store Models And Paths

**Files:**
- Create: `hindsight_lite/__init__.py`
- Create: `hindsight_lite/models.py`
- Create: `hindsight_lite/paths.py`
- Test: `tests/hindsight_lite/test_store.py`

- [ ] **Step 1: Write failing tests for path resolution and page ID safety**

Add `tests/hindsight_lite/test_store.py`:

```python
from pathlib import Path

import pytest

from hindsight_lite.paths import MemoryPaths, unsafe_page_id


def test_memory_paths_create_bank_dirs(tmp_path: Path) -> None:
    paths = MemoryPaths(home=tmp_path, bank_id="codex::project")

    paths.ensure_bank_dirs()

    assert paths.bank_dir == tmp_path / "banks" / "codex__project"
    assert paths.sessions_dir.is_dir()
    assert paths.pages_dir.is_dir()
    assert paths.reflections_dir.is_dir()
    assert paths.index_dir.is_dir()


@pytest.mark.parametrize("page_id", ["../secret", "a/b", "", ".", "x\\y"])
def test_unsafe_page_id_rejects_traversal(page_id: str) -> None:
    assert unsafe_page_id(page_id)


def test_unsafe_page_id_allows_slug() -> None:
    assert not unsafe_page_id("project-rules_2026")
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_store.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'hindsight_lite'`.

- [ ] **Step 3: Implement models and safe paths**

Create `hindsight_lite/__init__.py`:

```python
"""Local-first memory runtime for hindsight-lite."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

Create `hindsight_lite/models.py`:

```python
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
```

Create `hindsight_lite/paths.py`:

```python
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_SAFE_PAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def default_home() -> Path:
    override = os.environ.get("HINDSIGHT_LITE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hindsight-lite"


def safe_bank_dir_name(bank_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "__", bank_id).strip("._") or "default"


def unsafe_page_id(page_id: str) -> bool:
    return _SAFE_PAGE_ID.fullmatch(page_id) is None


@dataclass(frozen=True)
class MemoryPaths:
    home: Path
    bank_id: str

    @property
    def bank_dir(self) -> Path:
        return self.home / "banks" / safe_bank_dir_name(self.bank_id)

    @property
    def sessions_dir(self) -> Path:
        return self.bank_dir / "sessions"

    @property
    def pages_dir(self) -> Path:
        return self.bank_dir / "pages"

    @property
    def reflections_dir(self) -> Path:
        return self.bank_dir / "reflections"

    @property
    def index_dir(self) -> Path:
        return self.bank_dir / "index"

    @property
    def metadata_path(self) -> Path:
        return self.bank_dir / "metadata.json"

    def ensure_bank_dirs(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.reflections_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight_lite/__init__.py hindsight_lite/models.py hindsight_lite/paths.py tests/hindsight_lite/test_store.py
git commit -m "feat: add local memory path primitives"
```

## Task 2: JSONL Sessions And Markdown Pages

**Files:**
- Create: `hindsight_lite/store.py`
- Modify: `tests/hindsight_lite/test_store.py`

- [ ] **Step 1: Add failing store tests**

Append to `tests/hindsight_lite/test_store.py`:

```python
from hindsight_lite.store import LocalMemoryStore


def test_append_and_read_session_memory(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    event = store.append_session_memory(
        session_id="sess-1",
        content="User prefers local Markdown memory.",
        document_id="sess-1",
        tags=["sess-1"],
        metadata={"cwd": "/repo", "message_count": "2"},
    )

    events = store.read_session_memories()
    assert event.id.startswith("mem_")
    assert events[0].content == "User prefers local Markdown memory."
    assert events[0].metadata["cwd"] == "/repo"


def test_list_and_get_pages_with_frontmatter(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.paths.ensure_bank_dirs()
    (store.paths.pages_dir / "project-rules.md").write_text(
        "---\n"
        "id: project-rules\n"
        "title: Project Rules\n"
        "tags: [project, rules]\n"
        "updated_at: 2026-05-10T00:00:00Z\n"
        "---\n\n"
        "Always start from .understand-anything.\n",
        encoding="utf-8",
    )

    pages = store.list_pages()
    page = store.get_page("project-rules")

    assert pages[0].id == "project-rules"
    assert pages[0].title == "Project Rules"
    assert pages[0].tags == ["project", "rules"]
    assert page.content == "Always start from .understand-anything.\n"


def test_get_page_rejects_traversal(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")

    with pytest.raises(ValueError, match="Invalid page_id"):
        store.get_page("../secret")
```

- [ ] **Step 2: Run failing store tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_store.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `LocalMemoryStore`.

- [ ] **Step 3: Implement store**

Create `hindsight_lite/store.py`:

```python
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .models import KnowledgePage, SessionMemoryEvent
from .paths import MemoryPaths, default_home, unsafe_page_id


class LocalMemoryStore:
    def __init__(self, bank_id: str, home: Path | None = None):
        self.paths = MemoryPaths(home=home or default_home(), bank_id=bank_id)
        self.bank_id = bank_id

    def append_session_memory(
        self,
        session_id: str,
        content: str,
        document_id: str,
        tags: list[str] | None = None,
        metadata: dict[str, str] | None = None,
        source: str = "codex",
    ) -> SessionMemoryEvent:
        self.paths.ensure_bank_dirs()
        event = SessionMemoryEvent(
            type="session_memory",
            id=f"mem_{uuid.uuid4().hex}",
            timestamp=_now_iso(),
            bank_id=self.bank_id,
            session_id=session_id,
            source=source,
            document_id=document_id,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
        )
        path = self.paths.sessions_dir / f"{_safe_filename(session_id)}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def read_session_memories(self) -> list[SessionMemoryEvent]:
        self.paths.ensure_bank_dirs()
        events: list[SessionMemoryEvent] = []
        for path in sorted(self.paths.sessions_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    events.append(SessionMemoryEvent(**data))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
        return events

    def list_pages(self) -> list[KnowledgePage]:
        self.paths.ensure_bank_dirs()
        return [self._read_page(path) for path in sorted(self.paths.pages_dir.glob("*.md"))]

    def get_page(self, page_id: str) -> KnowledgePage:
        if unsafe_page_id(page_id):
            raise ValueError(f"Invalid page_id: {page_id}")
        path = self.paths.pages_dir / f"{page_id}.md"
        if not path.exists():
            raise FileNotFoundError(page_id)
        return self._read_page(path)

    def _read_page(self, path: Path) -> KnowledgePage:
        raw = path.read_text(encoding="utf-8")
        metadata, content = _parse_frontmatter(raw)
        page_id = metadata.get("id") or path.stem
        title = metadata.get("title") or page_id.replace("-", " ").title()
        tags = _parse_tags(metadata.get("tags", ""))
        return KnowledgePage(
            id=page_id,
            title=title,
            content=content,
            path=str(path),
            updated_at=metadata.get("updated_at"),
            tags=tags,
            metadata={k: v for k, v in metadata.items() if k not in {"id", "title", "tags", "updated_at"}},
        )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value) or "unknown"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw
    end = raw.find("\n---", 4)
    if end == -1:
        return {}, raw
    frontmatter = raw[4:end].strip()
    body = raw[end + len("\n---") :]
    if body.startswith("\n"):
        body = body[1:]
    metadata: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body


def _parse_tags(value: str) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        stripped = stripped[1:-1]
    return [item.strip().strip("\"'") for item in stripped.split(",") if item.strip()]
```

- [ ] **Step 4: Run store tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight_lite/store.py tests/hindsight_lite/test_store.py
git commit -m "feat: store local sessions and pages"
```

## Task 3: Local Recall And Codex Formatting

**Files:**
- Create: `hindsight_lite/scoring.py`
- Create: `hindsight_lite/formatting.py`
- Test: `tests/hindsight_lite/test_recall.py`

- [ ] **Step 1: Write failing recall tests**

Create `tests/hindsight_lite/test_recall.py`:

```python
from pathlib import Path

from hindsight_lite.formatting import format_hindsight_context
from hindsight_lite.scoring import recall
from hindsight_lite.store import LocalMemoryStore


def test_recall_ranks_page_title_match(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.paths.ensure_bank_dirs()
    (store.paths.pages_dir / "project-rules.md").write_text(
        "---\nid: project-rules\ntitle: Project Rules\n---\n\nUse .understand-anything first.\n",
        encoding="utf-8",
    )
    store.append_session_memory("sess", "Unrelated note about lunch", "sess")

    results = recall(store, "project rules understand anything", limit=3)

    assert results[0].source == "page"
    assert results[0].id == "project-rules"
    assert "understand-anything" in results[0].excerpt


def test_recall_finds_session_memory(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_memory("sess", "The repo is Codex-first and local-first.", "sess")

    results = recall(store, "Codex local memory", limit=3)

    assert results
    assert results[0].source == "session"
    assert "Codex-first" in results[0].excerpt


def test_format_hindsight_context_wraps_results(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_memory("sess", "Use local Markdown memory.", "sess")

    context = format_hindsight_context(recall(store, "Markdown memory", limit=3), preamble="Relevant memory:")

    assert context.startswith("<hindsight_memories>")
    assert "Relevant memory:" in context
    assert "Use local Markdown memory." in context
    assert context.endswith("</hindsight_memories>")
```

- [ ] **Step 2: Run failing recall tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_recall.py -v
```

Expected: FAIL because `hindsight_lite.scoring` and `formatting` do not exist.

- [ ] **Step 3: Implement scoring and formatting**

Create `hindsight_lite/scoring.py`:

```python
from __future__ import annotations

import re

from .models import RecallResult
from .store import LocalMemoryStore

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+")


def recall(store: LocalMemoryStore, query: str, limit: int = 5) -> list[RecallResult]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    results: list[RecallResult] = []
    for event in store.read_session_memories():
        score = _score(query_tokens, event.content)
        if score <= 0:
            continue
        results.append(
            RecallResult(
                id=event.id,
                source="session",
                path=f"sessions/{event.session_id}.jsonl",
                score=score,
                title=event.document_id,
                excerpt=_excerpt(event.content, query_tokens),
                timestamp=event.timestamp,
                metadata=event.metadata,
            )
        )
    for page in store.list_pages():
        text = f"{page.id} {page.title}\n{page.content}"
        score = _score(query_tokens, text)
        if score <= 0:
            continue
        results.append(
            RecallResult(
                id=page.id,
                source="page",
                path=f"pages/{page.id}.md",
                score=score + _title_bonus(query_tokens, page.id, page.title),
                title=page.title,
                excerpt=_excerpt(page.content, query_tokens),
                timestamp=page.updated_at,
                metadata=page.metadata,
            )
        )
    return sorted(results, key=lambda r: (r.score, r.timestamp or ""), reverse=True)[:limit]


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def _score(query_tokens: list[str], text: str) -> float:
    text_tokens = _tokens(text)
    if not text_tokens:
        return 0.0
    counts = {token: text_tokens.count(token) for token in set(text_tokens)}
    score = sum(1.0 + counts.get(token, 0) for token in set(query_tokens) if token in counts)
    phrase = " ".join(query_tokens)
    if phrase and phrase in " ".join(text_tokens):
        score += 5.0
    return score


def _title_bonus(query_tokens: list[str], page_id: str, title: str) -> float:
    title_tokens = set(_tokens(f"{page_id} {title}"))
    return sum(2.0 for token in set(query_tokens) if token in title_tokens)


def _excerpt(text: str, query_tokens: list[str], max_chars: int = 320) -> str:
    if len(text) <= max_chars:
        return text.strip()
    lower = text.lower()
    positions = [lower.find(token) for token in query_tokens if lower.find(token) >= 0]
    start = max(0, min(positions) - 80) if positions else 0
    return text[start : start + max_chars].strip()
```

Create `hindsight_lite/formatting.py`:

```python
from __future__ import annotations

from .models import RecallResult


def format_hindsight_context(results: list[RecallResult], preamble: str, max_chars: int = 4000) -> str:
    lines = ["<hindsight_memories>", preamble.strip(), ""]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"{index}. [{result.source}] {result.title}",
                f"   score: {result.score:.2f}",
                f"   path: {result.path}",
                f"   text: {result.excerpt}",
                "",
            ]
        )
    lines.append("</hindsight_memories>")
    context = "\n".join(lines)
    if len(context) <= max_chars:
        return context
    return context[: max_chars - len("\n</hindsight_memories>")] + "\n</hindsight_memories>"
```

- [ ] **Step 4: Run recall tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_recall.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight_lite/scoring.py hindsight_lite/formatting.py tests/hindsight_lite/test_recall.py
git commit -m "feat: add local recall scoring"
```

## Task 4: Reflection Packets

**Files:**
- Create: `hindsight_lite/reflection.py`
- Test: `tests/hindsight_lite/test_reflection.py`

- [ ] **Step 1: Write failing reflection tests**

Create `tests/hindsight_lite/test_reflection.py`:

```python
import json
from pathlib import Path

from hindsight_lite.reflection import build_reflection_packet
from hindsight_lite.store import LocalMemoryStore


def test_reflect_writes_request_and_returns_packet(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_memory("sess-1", "The repo is local-first.", "sess-1")

    packet = build_reflection_packet(
        store=store,
        query="What is this repo direction?",
        session_id="sess-1",
        task_context={"cwd": "/repo", "git_commit": "abc", "recent_prompt": "continue"},
    )

    assert packet.type == "reflection_request"
    assert packet.retrieved_context
    path = store.paths.reflections_dir / "sess-1.jsonl"
    saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert saved["type"] == "reflection_request"
    assert saved["query"] == "What is this repo direction?"
```

- [ ] **Step 2: Run failing reflection tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_reflection.py -v
```

Expected: FAIL because `hindsight_lite.reflection` does not exist.

- [ ] **Step 3: Implement reflection**

Create `hindsight_lite/reflection.py`:

```python
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict

from .models import ReflectionPacket
from .scoring import recall
from .store import LocalMemoryStore


def build_reflection_packet(
    store: LocalMemoryStore,
    query: str,
    session_id: str,
    task_context: dict[str, str],
    limit: int = 5,
) -> ReflectionPacket:
    results = recall(store, query, limit=limit)
    packet = ReflectionPacket(
        type="reflection_request",
        id=f"refl_{uuid.uuid4().hex}",
        timestamp=_now_iso(),
        bank_id=store.bank_id,
        session_id=session_id,
        query=query,
        retrieved_context=results,
        task_context=task_context,
        reflection_prompt=(
            "Use the retrieved evidence to produce a concise decision-oriented reflection. "
            "Preserve uncertainty and cite memory IDs when possible."
        ),
    )
    store.paths.ensure_bank_dirs()
    path = store.paths.reflections_dir / f"{_safe_filename(session_id)}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(packet), ensure_ascii=False) + "\n")
    return packet


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value) or "unknown"
```

- [ ] **Step 4: Run reflection tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_reflection.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight_lite/reflection.py tests/hindsight_lite/test_reflection.py
git commit -m "feat: persist reflection requests"
```

## Task 5: CLI Commands

**Files:**
- Create: `hindsight_lite/cli.py`
- Create: `hindsight_lite/__main__.py`
- Test: `tests/hindsight_lite/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/hindsight_lite/test_cli.py`:

```python
import json
from pathlib import Path

from hindsight_lite.cli import main
from hindsight_lite.store import LocalMemoryStore


def test_cli_list_and_get_pages(tmp_path: Path, capsys) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.paths.ensure_bank_dirs()
    (store.paths.pages_dir / "project-rules.md").write_text("---\ntitle: Project Rules\n---\n\nRules body\n")

    assert main(["--home", str(tmp_path), "--bank", "codex", "agent_knowledge_list_pages", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["id"] == "project-rules"

    assert main(["--home", str(tmp_path), "--bank", "codex", "agent_knowledge_get_page", "project-rules", "--json"]) == 0
    page = json.loads(capsys.readouterr().out)
    assert page["content"] == "Rules body\n"


def test_cli_recall_json(tmp_path: Path, capsys) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.append_session_memory("sess", "Local Markdown memory matters.", "sess")

    assert main(["--home", str(tmp_path), "--bank", "codex", "agent_knowledge_recall", "Markdown memory", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["results"][0]["source"] == "session"
```

- [ ] **Step 2: Run failing CLI tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_cli.py -v
```

Expected: FAIL because CLI is missing.

- [ ] **Step 3: Implement CLI**

Create `hindsight_lite/cli.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .formatting import format_hindsight_context
from .reflection import build_reflection_packet
from .scoring import recall
from .store import LocalMemoryStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hindsight_lite")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--bank", default="codex")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_query_command(subparsers, "agent_knowledge_recall")
    _add_query_command(subparsers, "agent_knowledge_reflect")

    list_pages = subparsers.add_parser("agent_knowledge_list_pages")
    list_pages.add_argument("--json", action="store_true")

    get_page = subparsers.add_parser("agent_knowledge_get_page")
    get_page.add_argument("page_id")
    get_page.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    store = LocalMemoryStore(home=args.home, bank_id=args.bank)

    if args.command == "agent_knowledge_recall":
        results = recall(store, args.query, limit=args.limit)
        _print_json({"results": [asdict(result) for result in results]})
        return 0
    if args.command == "agent_knowledge_reflect":
        packet = build_reflection_packet(store, args.query, session_id=args.session_id, task_context={})
        _print_json(asdict(packet))
        return 0
    if args.command == "agent_knowledge_list_pages":
        _print_json([asdict(page) for page in store.list_pages()])
        return 0
    if args.command == "agent_knowledge_get_page":
        try:
            _print_json(asdict(store.get_page(args.page_id)))
            return 0
        except (FileNotFoundError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    return 1


def _add_query_command(subparsers: argparse._SubParsersAction, name: str) -> None:
    command = subparsers.add_parser(name)
    command.add_argument("query")
    command.add_argument("--limit", type=int, default=5)
    command.add_argument("--session-id", default="manual")
    command.add_argument("--json", action="store_true")


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
```

Create `hindsight_lite/__main__.py`:

```python
from __future__ import annotations

from .cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
uv run pytest tests/hindsight_lite/test_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight_lite/cli.py hindsight_lite/__main__.py tests/hindsight_lite/test_cli.py
git commit -m "feat: add local memory cli"
```

## Task 6: Switch Codex Recall Hook To Local Store

**Files:**
- Modify: `hindsight-integrations/codex/scripts/recall.py`
- Modify: `hindsight-integrations/codex/tests/test_hooks.py`

- [ ] **Step 1: Replace recall hook test HTTP mock with local memory fixture**

Edit `hindsight-integrations/codex/tests/test_hooks.py` so `TestRecallHook.test_outputs_additional_context_when_memories_found` writes local memory instead of mocking HTTP:

```python
    def test_outputs_additional_context_when_memories_found(self, monkeypatch, tmp_path):
        from hindsight_lite.store import LocalMemoryStore

        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.append_session_memory("sess", "Paris is the capital of France", "sess")

        hook_input = make_hook_input(prompt="What is the capital of France?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "Paris is the capital of France" in context
        assert "<hindsight_memories>" in context
```

Update `_run_hook` to set local home:

```python
    monkeypatch.setenv("HINDSIGHT_LITE_HOME", str(tmp_path / ".hindsight-lite"))
```

Remove the required fake `HINDSIGHT_API_URL` setup from `_run_hook`.

- [ ] **Step 2: Run recall hook test and verify failure**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests/test_hooks.py::TestRecallHook::test_outputs_additional_context_when_memories_found -v
```

Expected: FAIL because `recall.py` still calls `get_api_url`.

- [ ] **Step 3: Implement local recall hook**

Modify `hindsight-integrations/codex/scripts/recall.py`:

- remove imports of `ensure_bank_mission`, `HindsightClient`, and `get_api_url`
- import `format_hindsight_context`, `recall`, and `LocalMemoryStore`
- after deriving `bank_id`, call local store
- emit the same `hookSpecificOutput.additionalContext`

The core replacement block should be:

```python
    bank_id = derive_bank_id(hook_input, config)
    store = LocalMemoryStore(bank_id=bank_id)
    results = recall(store, query, limit=5)
    if not results:
        debug_log(config, "No memories found")
        return

    context_message = format_hindsight_context(
        results,
        preamble=config.get("recallPromptPreamble", ""),
        max_chars=config.get("recallMaxTokens", 1024) * 4,
    )
```

Keep the final output JSON unchanged.

- [ ] **Step 4: Run Codex recall hook tests**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests/test_hooks.py::TestRecallHook -v
```

Expected: PASS after applying these concrete test migrations:

- Delete `test_graceful_on_api_error`; local recall no longer opens a network connection.
- Replace `test_recall_timeout_is_configurable` with a test that sets `recallMaxTokens` and asserts the emitted `additionalContext` length is bounded.
- Keep `test_multi_turn_context_from_transcript`, but assert a local session memory containing `"Python"` is found when transcript context is enabled.

- [ ] **Step 5: Commit**

```bash
git add hindsight-integrations/codex/scripts/recall.py hindsight-integrations/codex/tests/test_hooks.py
git commit -m "feat: use local recall in codex hook"
```

## Task 7: Switch Codex Retain Hook To Local Store

**Files:**
- Modify: `hindsight-integrations/codex/scripts/retain.py`
- Modify: `hindsight-integrations/codex/tests/test_hooks.py`

- [ ] **Step 1: Replace retain HTTP test with JSONL assertion**

Edit `TestRetainHook.test_posts_transcript_to_hindsight` into:

```python
    def test_retains_transcript_to_local_jsonl(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        session_file = tmp_path / ".hindsight-lite" / "banks" / "codex" / "sessions" / "sess-abc123.jsonl"
        content = session_file.read_text(encoding="utf-8")
        assert "hello" in content
        assert "world" in content
```

Update `test_strips_memory_tags_before_retaining` to read the JSONL file and assert `"old memories"` is absent.

- [ ] **Step 2: Run retain hook tests and verify failure**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests/test_hooks.py::TestRetainHook -v
```

Expected: FAIL because `retain.py` still calls HTTP.

- [ ] **Step 3: Implement local retain hook**

Modify `hindsight-integrations/codex/scripts/retain.py`:

- remove imports of `ensure_bank_mission`, `HindsightClient`, and `get_api_url`
- import `LocalMemoryStore`
- after transcript/tags/metadata are prepared, append session memory locally

The replacement block should be:

```python
    bank_id = derive_bank_id(hook_input, config)
    store = LocalMemoryStore(bank_id=bank_id)
    store.append_session_memory(
        session_id=session_id,
        content=transcript,
        document_id=document_id,
        tags=tags or [],
        metadata=metadata,
        source=config.get("retainContext", "codex"),
    )
    debug_log(config, f"Retained local memory for bank '{bank_id}', doc '{document_id}'")
```

- [ ] **Step 4: Run retain hook tests**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests/test_hooks.py::TestRetainHook -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hindsight-integrations/codex/scripts/retain.py hindsight-integrations/codex/tests/test_hooks.py
git commit -m "feat: use local retain in codex hook"
```

## Task 8: Localize Session Start And Config

**Files:**
- Modify: `hindsight-integrations/codex/scripts/session_start.py`
- Modify: `hindsight-integrations/codex/scripts/lib/config.py`
- Modify: `hindsight-integrations/codex/scripts/lib/bank.py`
- Modify: `hindsight-integrations/codex/settings.json`
- Modify: `hindsight-integrations/codex/tests/test_bank.py`
- Modify: `hindsight-integrations/codex/tests/test_hooks.py`

- [ ] **Step 1: Add session start test**

Add to `hindsight-integrations/codex/tests/test_hooks.py`:

```python
class TestSessionStartHook:
    def test_session_start_initializes_local_bank(self, monkeypatch, tmp_path):
        hook_input = make_hook_input()
        _run_hook("session_start", hook_input, monkeypatch, tmp_path)

        bank_dir = tmp_path / ".hindsight-lite" / "banks" / "codex"
        assert (bank_dir / "sessions").is_dir()
        assert (bank_dir / "pages").is_dir()
        assert (bank_dir / "reflections").is_dir()
```

- [ ] **Step 2: Run session start test and verify failure**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests/test_hooks.py::TestSessionStartHook -v
```

Expected: FAIL because `session_start.py` still checks daemon health.

- [ ] **Step 3: Implement local session start and config cleanup**

Modify `session_start.py` to:

```python
#!/usr/bin/env python3
"""SessionStart hook: initialize local hindsight-lite memory directories."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hindsight_lite.store import LocalMemoryStore
from lib.bank import derive_bank_id
from lib.config import debug_log, load_config


def main():
    config = load_config()
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}
    bank_id = derive_bank_id(hook_input, config)
    LocalMemoryStore(bank_id=bank_id).paths.ensure_bank_dirs()
    debug_log(config, f"Initialized local memory bank: {bank_id}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] SessionStart error: {e}", file=sys.stderr)
        sys.exit(0)
```

In `config.py`, remove local-only dead settings from `DEFAULTS` and `ENV_OVERRIDES`: API URL, token, port, daemon, embed, LLM, bank mission, retain mission. Add `"home": None` and `HINDSIGHT_LITE_HOME`.

In `bank.py`, remove `ensure_bank_mission()` or leave it unused if tests still import it. If left for compatibility, make it a no-op:

```python
def ensure_bank_mission(client, bank_id: str, config: dict, debug_fn=None):
    if debug_fn:
        debug_fn(f"Skipping bank mission for local memory bank: {bank_id}")
```

- [ ] **Step 4: Run Codex tests**

Run:

```bash
uv run pytest hindsight-integrations/codex/tests -v
```

Expected: PASS after applying these concrete test migrations:

- Replace `test_retain_posts_async_true` with a test that the saved JSONL event has `"type": "session_memory"`.
- Replace `test_retain_includes_codex_context_label` with a test that the saved JSONL event has `"source": "codex"`.
- Keep `test_retain_skips_below_every_n_turns_threshold`, but assert the local session JSONL file is absent.
- Keep `test_retain_uses_session_id_as_document_id`, but assert the saved JSONL event has `"document_id": "sess-doc-test"`.
- Delete `test_graceful_on_retain_api_error`; local retain no longer opens a network connection.
- Keep `test_disabled_auto_retain_does_not_call_api`, but rename it to `test_disabled_auto_retain_does_not_write_jsonl`.
- Keep `test_reads_codex_response_item_format`, but assert the local JSONL content contains `"TypeScript"`.

- [ ] **Step 5: Commit**

```bash
git add hindsight-integrations/codex/scripts/session_start.py hindsight-integrations/codex/scripts/lib/config.py hindsight-integrations/codex/scripts/lib/bank.py hindsight-integrations/codex/settings.json hindsight-integrations/codex/tests
git commit -m "feat: make codex plugin local-only"
```

## Task 9: Final Verification And Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-05-10-codex-local-memory-plugin-design.md` if implementation details drifted.

- [ ] **Step 1: Run full local memory test suite**

Run:

```bash
uv run pytest tests/hindsight_lite hindsight-integrations/codex/tests -v
```

Expected: PASS.

- [ ] **Step 2: Run lint**

Run:

```bash
./scripts/hooks/lint.sh
```

Expected: PASS, or only existing unrelated failures. If unrelated failures appear, record them in the final handoff and do not silently change unrelated code.

- [ ] **Step 3: Smoke test CLI manually**

Run:

```bash
tmp_home="$(mktemp -d)"
HINDSIGHT_LITE_HOME="$tmp_home" uv run python -m hindsight_lite agent_knowledge_list_pages --bank codex --json
```

Expected output:

```json
[]
```

- [ ] **Step 4: Update README status if V1 works**

If all tests and smoke tests pass, change README feature table statuses from `design` to `alpha` for implemented Codex capabilities. Do not claim Claude Code or OpenCode support.

- [ ] **Step 5: Commit docs update**

```bash
git add README.md docs/superpowers/specs/2026-05-10-codex-local-memory-plugin-design.md
git commit -m "docs: document codex local memory alpha"
```
