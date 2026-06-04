from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hindsight_lite.store import LocalMemoryStore, PageNotFoundError

USER_PROFILE_PAGE_ID = "user-profile"

_KNOWN_PROGRAMMING_LANGUAGES = (
    "rust",
    "python",
    "typescript",
    "javascript",
    "go",
    "golang",
    "java",
    "c++",
    "cpp",
    "c#",
    "csharp",
)


@dataclass(frozen=True)
class UserProfileFacts:
    name: str | None = None
    preferred_programming_language: str | None = None

    def has_facts(self) -> bool:
        return self.name is not None or self.preferred_programming_language is not None

    def merge(self, other: UserProfileFacts) -> UserProfileFacts:
        return UserProfileFacts(
            name=other.name or self.name,
            preferred_programming_language=(
                other.preferred_programming_language or self.preferred_programming_language
            ),
        )


def promote_user_profile_from_messages(store: LocalMemoryStore, messages: Sequence[Mapping[str, object]]) -> None:
    extracted = extract_user_profile_facts(messages)
    if not extracted.has_facts():
        return

    facts = _read_existing_user_profile(store).merge(extracted)
    lines = ["# User Profile", ""]
    if facts.name is not None:
        lines.append(f"Name: {facts.name}")
    if facts.preferred_programming_language is not None:
        lines.append(f"Preferred programming language: {facts.preferred_programming_language}")

    store.write_page(
        page_id=USER_PROFILE_PAGE_ID,
        title="User Profile",
        content="\n".join(lines),
        tags=["user", "identity", "preference", "programming-language"],
        metadata={"kind": "semantic-user-memory"},
    )


def extract_user_profile_facts(messages: Sequence[Mapping[str, object]]) -> UserProfileFacts:
    name: str | None = None
    preferred_language: str | None = None
    for message in messages:
        if message.get("role") != "user":
            continue
        text = _message_text(message.get("content"))
        name = _extract_name(text) or name
        preferred_language = _extract_preferred_programming_language(text) or preferred_language
    return UserProfileFacts(name=name, preferred_programming_language=preferred_language)


def expand_user_profile_query(query: str) -> str:
    additions: list[str] = []
    normalized = query.lower()
    if "我是谁" in query or "who am i" in normalized:
        additions.extend(["user", "identity", "name"])
    if "编程语言" in query or "programming language" in normalized:
        additions.extend(["user", "preference", "programming-language"])
    if not additions:
        return query
    return " ".join([query, *additions])


def _read_existing_user_profile(store: LocalMemoryStore) -> UserProfileFacts:
    try:
        page = store.get_page(USER_PROFILE_PAGE_ID)
    except (PageNotFoundError, OSError):
        return UserProfileFacts()

    return UserProfileFacts(
        name=_read_profile_line(page.content, "Name"),
        preferred_programming_language=_read_profile_line(page.content, "Preferred programming language"),
    )


def _read_profile_line(content: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in content.splitlines():
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            return value or None
    return None


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def _extract_name(text: str) -> str | None:
    patterns = [
        r"\bmy name is\s+([A-Za-z][A-Za-z0-9_-]{0,40})\b",
        r"\bi am\s+([A-Za-z][A-Za-z0-9_-]{0,40})\b",
        r"我(?:是|叫)\s*([A-Za-z][A-Za-z0-9_-]{0,40})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return None


def _extract_preferred_programming_language(text: str) -> str | None:
    normalized = text.lower()
    if not any(marker in normalized for marker in ("i like", "i love")) and not any(
        marker in text for marker in ("我喜欢", "我爱")
    ):
        return None

    for language in _KNOWN_PROGRAMMING_LANGUAGES:
        if _contains_language(normalized, language):
            return language
    return None


def _contains_language(text: str, language: str) -> bool:
    escaped = re.escape(language)
    return re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", text) is not None
