from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from hindsight_lite.models import KnowledgePage, ReflectionPacket, ReflectionResult, SessionMemoryEvent
from hindsight_lite.paths import MemoryPaths, default_home, unsafe_page_id


class UnsafePageIdError(ValueError):
    pass


class UnsafeReflectionIdError(ValueError):
    pass


class PageNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class PageFrontmatter:
    id: str | None = None
    title: str | None = None
    updated_at: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class PageDocument:
    frontmatter: PageFrontmatter
    body: str


class LocalMemoryStore:
    def __init__(self, bank_id: str, home: Path | None = None) -> None:
        self.paths = MemoryPaths(home=home or default_home(), bank_id=bank_id)
        self.paths.ensure_bank_dirs()

    def append_session_event(self, event: SessionMemoryEvent) -> Path:
        session_path = self.paths.sessions_dir / f"{event.session_id}.jsonl"
        with session_path.open("a", encoding="utf-8") as file:
            file.write(_session_event_line(event))
        from hindsight_lite.index import append_session_event_to_recall_index

        append_session_event_to_recall_index(self, event)
        return session_path

    def replace_session_event(self, event: SessionMemoryEvent) -> Path:
        session_path = self.paths.sessions_dir / f"{event.session_id}.jsonl"
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=session_path.parent,
            prefix=f".{session_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(_session_event_line(event))
            temporary_path = Path(temporary_file.name)
        # Full-session retention previously appended every growing snapshot.
        # Replace atomically so readers see either the old or latest complete event.
        try:
            temporary_path.replace(session_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        from hindsight_lite.index import replace_session_event_in_recall_index

        replace_session_event_in_recall_index(self, event)
        return session_path

    def read_session_events(self, session_id: str) -> list[SessionMemoryEvent]:
        session_path = self.paths.sessions_dir / f"{session_id}.jsonl"
        if not session_path.exists():
            return []

        events: list[SessionMemoryEvent] = []
        with session_path.open(encoding="utf-8") as file:
            for line in file:
                raw_line = line.strip()
                if raw_line:
                    events.append(SessionMemoryEvent(**json.loads(raw_line)))
        return events

    def list_session_events(self) -> list[SessionMemoryEvent]:
        events: list[SessionMemoryEvent] = []
        for session_path in sorted(self.paths.sessions_dir.glob("*.jsonl")):
            events.extend(self.read_session_events(session_path.stem))
        return events

    def write_page(
        self,
        page_id: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> KnowledgePage:
        page_path = self._page_path(page_id)
        updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        page = KnowledgePage(
            id=page_id,
            title=title,
            content=content,
            path=str(page_path),
            updated_at=updated_at,
            tags=tags or [],
            metadata=metadata or {},
        )
        page_path.write_text(self._render_page(page), encoding="utf-8")
        from hindsight_lite.index import update_page_in_recall_index

        update_page_in_recall_index(self, page)
        return page

    def list_pages(self) -> list[KnowledgePage]:
        pages = [self._read_page_path(path) for path in sorted(self.paths.pages_dir.glob("*.md"))]
        return pages

    def get_page(self, page_id: str) -> KnowledgePage:
        page_path = self._page_path(page_id)
        if not page_path.exists():
            raise PageNotFoundError(page_id)
        return self._read_page_path(page_path)

    def write_reflection_packet(self, packet: ReflectionPacket) -> Path:
        packet_path = self._reflection_path(packet.id)
        packet_path.write_text(
            json.dumps(asdict(packet), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        return packet_path

    def write_reflection_result(self, result: ReflectionResult) -> Path:
        result_path = self._reflection_path(result.id)
        result_path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        return result_path

    def _page_path(self, page_id: str) -> Path:
        if unsafe_page_id(page_id):
            raise UnsafePageIdError(page_id)
        return self.paths.pages_dir / f"{page_id}.md"

    def _reflection_path(self, reflection_id: str) -> Path:
        if unsafe_page_id(reflection_id):
            raise UnsafeReflectionIdError(reflection_id)
        return self.paths.reflections_dir / f"{reflection_id}.json"

    def _read_page_path(self, page_path: Path) -> KnowledgePage:
        document = self._parse_page(page_path.read_text(encoding="utf-8"))
        page_id = document.frontmatter.id or page_path.stem
        title = document.frontmatter.title or page_id
        return KnowledgePage(
            id=page_id,
            title=title,
            content=document.body,
            path=str(page_path),
            updated_at=document.frontmatter.updated_at,
            tags=document.frontmatter.tags or [],
            metadata=document.frontmatter.metadata or {},
        )

    @staticmethod
    def _render_page(page: KnowledgePage) -> str:
        frontmatter = {
            "id": page.id,
            "title": page.title,
            "updated_at": page.updated_at,
            "tags": page.tags,
            "metadata": page.metadata,
        }
        lines = ["---"]
        for key, value in frontmatter.items():
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.append("---")
        lines.append(page.content.rstrip())
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_page(text: str) -> PageDocument:
        if not text.startswith("---\n"):
            return PageDocument(frontmatter=PageFrontmatter(), body=text.rstrip("\n"))

        marker = "\n---\n"
        end_index = text.find(marker, len("---\n"))
        if end_index == -1:
            return PageDocument(frontmatter=PageFrontmatter(), body=text.rstrip("\n"))

        frontmatter_text = text[len("---\n") : end_index]
        body = text[end_index + len(marker) :].rstrip("\n")
        frontmatter = PageFrontmatter()
        for line in frontmatter_text.splitlines():
            key, separator, raw_value = line.partition(":")
            if not separator:
                continue
            frontmatter = _with_frontmatter_value(frontmatter, key.strip(), json.loads(raw_value.strip()))
        return PageDocument(frontmatter=frontmatter, body=body)


def _coerce_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _session_event_line(event: SessionMemoryEvent) -> str:
    return f"{json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)}\n"


def _coerce_str_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _with_frontmatter_value(frontmatter: PageFrontmatter, key: str, value: object) -> PageFrontmatter:
    if key == "id" and isinstance(value, str):
        return PageFrontmatter(value, frontmatter.title, frontmatter.updated_at, frontmatter.tags, frontmatter.metadata)
    if key == "title" and isinstance(value, str):
        return PageFrontmatter(frontmatter.id, value, frontmatter.updated_at, frontmatter.tags, frontmatter.metadata)
    if key == "updated_at" and isinstance(value, str):
        return PageFrontmatter(frontmatter.id, frontmatter.title, value, frontmatter.tags, frontmatter.metadata)
    if key == "tags":
        return PageFrontmatter(
            frontmatter.id,
            frontmatter.title,
            frontmatter.updated_at,
            _coerce_str_list(value),
            frontmatter.metadata,
        )
    if key == "metadata":
        return PageFrontmatter(
            frontmatter.id,
            frontmatter.title,
            frontmatter.updated_at,
            frontmatter.tags,
            _coerce_str_map(value),
        )
    return frontmatter
