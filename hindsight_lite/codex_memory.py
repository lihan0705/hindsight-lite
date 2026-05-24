from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from hindsight_lite.store import LocalMemoryStore

_SUPPORTED_SUFFIXES = {".json", ".jsonl", ".md", ".markdown", ".toml", ".txt"}


@dataclass(frozen=True)
class CodexMemoryDocument:
    page_id: str
    title: str
    content: str
    source_path: Path


@dataclass(frozen=True)
class CodexMemoryImportResult:
    imported_pages: list[str]
    skipped_files: list[str]


def default_codex_memory_dir() -> Path:
    return Path.home() / ".codex" / "memories"


def import_codex_memories(
    store: LocalMemoryStore,
    source_dir: Path | None = None,
    dry_run: bool = False,
) -> CodexMemoryImportResult:
    root = (source_dir or default_codex_memory_dir()).expanduser()
    if not root.exists():
        return CodexMemoryImportResult(imported_pages=[], skipped_files=[str(root)])

    documents = _read_codex_memory_documents(root)
    imported_pages: list[str] = []
    for document in documents:
        imported_pages.append(document.page_id)
        if dry_run:
            continue
        store.write_page(
            page_id=document.page_id,
            title=document.title,
            content=document.content,
            tags=["codex-memory"],
            metadata={
                "source": "codex-memory",
                "source_path": str(document.source_path),
            },
        )

    return CodexMemoryImportResult(imported_pages=imported_pages, skipped_files=[])


def _read_codex_memory_documents(root: Path) -> list[CodexMemoryDocument]:
    documents: list[CodexMemoryDocument] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        documents.append(_document_from_file(root, path, text))
    return documents


def _document_from_file(root: Path, path: Path, text: str) -> CodexMemoryDocument:
    relative_path = path.relative_to(root)
    page_id = _page_id_for_path(relative_path)
    rendered_text = _render_memory_text(path, text)
    return CodexMemoryDocument(
        page_id=page_id,
        title=_title_for_path(path, text),
        content=f"Imported from Codex memory file: {relative_path}\n\n{rendered_text}",
        source_path=path,
    )


def _page_id_for_path(relative_path: Path) -> str:
    safe_parts = [part.replace(" ", "-") for part in relative_path.with_suffix("").parts]
    raw_id = "codex-memory-" + "-".join(safe_parts)
    safe_id = "".join(char if char.isalnum() or char in "._-" else "-" for char in raw_id).strip(".-_")
    digest = hashlib.sha1(str(relative_path).encode("utf-8")).hexdigest()[:8]
    return f"{safe_id or 'codex-memory'}-{digest}"


def _title_for_path(path: Path, text: str) -> str:
    if path.suffix.lower() in {".md", ".markdown"}:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped.removeprefix("# ").strip() or path.stem
    return path.stem.replace("-", " ").replace("_", " ").title()


def _render_memory_text(path: Path, text: str) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _render_json_text(text)
    if suffix == ".jsonl":
        return _render_jsonl_text(text)
    return text


def _render_json_text(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True)


def _render_jsonl_text(text: str) -> str:
    rendered_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            rendered_lines.append(stripped)
            continue
        rendered_lines.append(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
    return "\n".join(rendered_lines)
