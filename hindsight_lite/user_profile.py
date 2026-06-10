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

_KNOWN_DRINKS = (
    "珍珠奶茶",
    "柠檬水",
    "lemon water",
    "咖啡",
    "coffee",
    "茶",
    "tea",
    "奶茶",
    "可乐",
    "牛奶",
    "milk",
    "气泡水",
    "苏打水",
    "矿泉水",
    "纯净水",
)

# Parse explicit first-person preference statements instead of maintaining a
# vocabulary for every possible food, drink, tool, activity, or media title.
_CHINESE_PREFERENCE_PATTERN = re.compile(
    r"我(?:还|也)?(?:最|更|很|非常|特别|挺)?(?:喜欢|爱|偏好)"
    r"(?P<action>吃|喝|用|玩|看|听)?\s*"
    r"(?P<value>[^，。！？；\n]{1,80})"
)
_ENGLISH_PREFERENCE_PATTERN = re.compile(
    r"\bi\s+(?:also\s+)?(?:like|love)\s+(?:to\s+)?"
    r"(?:(?P<action>eat|drink|use|play|watch|listen\s+to)\s+)?"
    r"(?P<value>[^.!?;\n]{1,80})",
    flags=re.IGNORECASE,
)
_PREFERENCE_CATEGORIES = {
    "吃": "food",
    "eat": "food",
    "喝": "drink",
    "drink": "drink",
    "用": "tool",
    "use": "tool",
    "玩": "activity",
    "play": "activity",
    "看": "media",
    "watch": "media",
    "听": "media",
    "listen to": "media",
}
_QUESTION_VALUES = ("什么", "哪些", "哪个", "what", "which")


@dataclass(frozen=True)
class UserPreference:
    category: str
    value: str


@dataclass(frozen=True)
class UserProfileFacts:
    name: str | None = None
    preferred_programming_language: str | None = None
    preferred_drink: str | None = None
    preferences: tuple[UserPreference, ...] = ()

    def has_facts(self) -> bool:
        return (
            self.name is not None
            or self.preferred_programming_language is not None
            or self.preferred_drink is not None
            or bool(self.preferences)
        )

    def merge(self, other: UserProfileFacts) -> UserProfileFacts:
        return UserProfileFacts(
            name=other.name or self.name,
            preferred_programming_language=_merge_preference_values(
                self.preferred_programming_language,
                other.preferred_programming_language,
            ),
            preferred_drink=_merge_preference_values(self.preferred_drink, other.preferred_drink),
            preferences=_merge_preferences(self.preferences, other.preferences),
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
    if facts.preferred_drink is not None:
        lines.append(f"Preferred drink: {facts.preferred_drink}")
    for preference in facts.preferences:
        lines.append(f"Preference ({preference.category}): {preference.value}")

    preference_tags = [preference.category for preference in facts.preferences]
    store.write_page(
        page_id=USER_PROFILE_PAGE_ID,
        title="User Profile",
        content="\n".join(lines),
        tags=["user", "identity", "preference", "programming-language", "drink", *preference_tags],
        metadata={"kind": "semantic-user-memory"},
    )


def extract_user_profile_facts(messages: Sequence[Mapping[str, object]]) -> UserProfileFacts:
    name: str | None = None
    preferred_language: str | None = None
    preferred_drink: str | None = None
    preferences: tuple[UserPreference, ...] = ()
    for message in messages:
        if message.get("role") != "user":
            continue
        text = _message_text(message.get("content"))
        name = _extract_name(text) or name
        preferred_language = _merge_preference_values(
            preferred_language,
            _extract_preferred_programming_language(text),
        )
        preferred_drink = _merge_preference_values(preferred_drink, _extract_preferred_drink(text))
        preferences = _merge_preferences(preferences, _extract_general_preferences(text))
    return UserProfileFacts(
        name=name,
        preferred_programming_language=preferred_language,
        preferred_drink=preferred_drink,
        preferences=preferences,
    )


def expand_user_profile_query(query: str) -> str:
    additions: list[str] = []
    normalized = query.lower()
    if "我是谁" in query or "who am i" in normalized:
        additions.extend(["user", "identity", "name"])
    if "编程语言" in query or "programming language" in normalized:
        additions.extend(["user", "preference", "programming-language"])
    if "我喜欢" in query or "我爱" in query or "like" in normalized or "love" in normalized or "prefer" in normalized:
        additions.extend(["user", "preference"])
    if "喜欢喝" in query or "喝什么" in query or any(marker in normalized for marker in ("drink", "beverage", "water")):
        additions.extend(["drink", "beverage"])
    if "喜欢吃" in query or "吃什么" in query or any(marker in normalized for marker in ("food", "eat")):
        additions.append("food")
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
        preferred_drink=_read_profile_line(page.content, "Preferred drink"),
        preferences=_read_preferences(page.content),
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
    if not _extract_preferences(text):
        return None

    for language in _KNOWN_PROGRAMMING_LANGUAGES:
        if _contains_language(normalized, language):
            return language
    return None


def _extract_preferred_drink(text: str) -> str | None:
    extracted = _extract_preferences(text)
    for preference in extracted:
        if preference.category == "drink":
            return preference.value

    normalized = text.lower()
    for drink in _KNOWN_DRINKS:
        if extracted and _contains_value(text, normalized, drink):
            return drink
    return None


def _extract_general_preferences(text: str) -> tuple[UserPreference, ...]:
    preferences = []
    for preference in _extract_preferences(text):
        if preference.category == "drink":
            continue
        if any(_contains_value(preference.value, preference.value.lower(), drink) for drink in _KNOWN_DRINKS):
            continue
        if any(_contains_language(preference.value.lower(), language) for language in _KNOWN_PROGRAMMING_LANGUAGES):
            continue
        preferences.append(preference)
    return tuple(preferences)


def _extract_preferences(text: str) -> tuple[UserPreference, ...]:
    preferences: list[UserPreference] = []
    for pattern in (_CHINESE_PREFERENCE_PATTERN, _ENGLISH_PREFERENCE_PATTERN):
        for match in pattern.finditer(text):
            value = match.group("value").strip(" \t、,，")
            normalized_value = value.lower()
            if (
                not value
                or any(question in normalized_value for question in _QUESTION_VALUES)
                or value.endswith(("吗", "么"))
                or "?" in text
                or "？" in text
            ):
                continue
            action = (match.group("action") or "").lower()
            preferences.append(
                UserPreference(
                    category=_PREFERENCE_CATEGORIES.get(action, "general"),
                    value=value,
                )
            )
    return tuple(preferences)


def _merge_preference_values(existing: str | None, new: str | None) -> str | None:
    if new is None:
        return existing
    if existing is None:
        return new
    if _contains_value(existing, existing.lower(), new):
        return existing
    return f"{existing}、{new}"


def _merge_preferences(
    existing: tuple[UserPreference, ...],
    new: tuple[UserPreference, ...],
) -> tuple[UserPreference, ...]:
    merged = list(existing)
    for preference in new:
        for index, current in enumerate(merged):
            if current.category != preference.category:
                continue
            merged[index] = UserPreference(
                category=current.category,
                value=_merge_preference_values(current.value, preference.value) or current.value,
            )
            break
        else:
            merged.append(preference)
    return tuple(merged)


def _read_preferences(content: str) -> tuple[UserPreference, ...]:
    preferences: list[UserPreference] = []
    for line in content.splitlines():
        match = re.fullmatch(r"Preference \(([^)]+)\):\s*(.+)", line)
        if match:
            preferences.append(UserPreference(category=match.group(1), value=match.group(2).strip()))
    return tuple(preferences)


def _contains_language(text: str, language: str) -> bool:
    escaped = re.escape(language)
    return re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", text) is not None


def _contains_value(text: str, normalized: str, value: str) -> bool:
    if any("\u4e00" <= character <= "\u9fff" for character in value):
        return value in text
    escaped = re.escape(value)
    return re.search(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", normalized) is not None
