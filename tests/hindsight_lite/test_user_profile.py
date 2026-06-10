from pathlib import Path

from hindsight_lite.store import LocalMemoryStore
from hindsight_lite.user_profile import (
    expand_user_profile_query,
    extract_user_profile_facts,
    promote_user_profile_from_messages,
)


def test_extract_user_profile_facts_uses_user_messages_only() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "assistant", "content": [{"type": "text", "text": "The user is jane and likes python."}]},
            {"role": "user", "content": [{"type": "text", "text": "我是jack 我爱rust"}]},
        ]
    )

    assert facts.name == "jack"
    assert facts.preferred_programming_language == "rust"


def test_extract_user_profile_facts_detects_drink_preference() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": [{"type": "text", "text": "我喜欢喝柠檬水"}]},
        ]
    )

    assert facts.preferred_drink == "柠檬水"


def test_promote_user_profile_merges_new_facts_with_existing_page(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我是jack"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我喜欢rust"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我爱喝柠檬水"}])

    profile = store.get_page("user-profile")

    assert "Name: jack" in profile.content
    assert "Preferred programming language: rust" in profile.content
    assert "Preferred drink: 柠檬水" in profile.content
    assert profile.metadata == {"kind": "semantic-user-memory"}


def test_expand_user_profile_query_adds_semantic_terms_for_identity_and_language() -> None:
    expanded = expand_user_profile_query("我是谁 我喜欢什么编程语言")

    assert "identity" in expanded
    assert "programming-language" in expanded


def test_expand_user_profile_query_adds_semantic_terms_for_drinks() -> None:
    expanded = expand_user_profile_query("我喜欢喝什么")

    assert "drink" in expanded
    assert "beverage" in expanded
