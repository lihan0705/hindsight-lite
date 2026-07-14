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
    def retains_dir(self) -> Path:
        return self.bank_dir / "retains"

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
        self.retains_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
