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
    assert facts.preferences == ()


def test_extract_user_profile_facts_detects_drink_preference() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": [{"type": "text", "text": "我喜欢喝柠檬水"}]},
        ]
    )

    assert facts.preferred_drink == "柠檬水"


def test_extract_user_profile_facts_detects_additional_specific_drink() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": [{"type": "text", "text": "我还喜欢珍珠奶茶"}]},
        ]
    )

    assert facts.preferred_drink == "珍珠奶茶"


def test_extract_user_profile_facts_detects_general_food_preference() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": [{"type": "text", "text": "我也喜欢吃火锅"}]},
        ]
    )

    assert [(preference.category, preference.value) for preference in facts.preferences] == [("food", "火锅")]


def test_extract_user_profile_facts_detects_unknown_drink_without_a_whitelist() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": [{"type": "text", "text": "我喜欢喝杨枝甘露"}]},
        ]
    )

    assert facts.preferred_drink == "杨枝甘露"


def test_extract_user_profile_facts_ignores_preference_questions() -> None:
    facts = extract_user_profile_facts(
        [
            {"role": "user", "content": "我喜欢吃什么"},
            {"role": "user", "content": "我喜欢喝珍珠奶茶吗？"},
            {"role": "user", "content": "what food do I like?"},
        ]
    )

    assert not facts.has_facts()


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


def test_promote_user_profile_appends_new_drink_without_replacing_existing_drinks(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我喜欢喝柠檬水"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我还喜欢珍珠奶茶"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我也喜欢珍珠奶茶"}])

    profile = store.get_page("user-profile")

    assert "Preferred drink: 柠檬水、珍珠奶茶" in profile.content


def test_promote_user_profile_appends_programming_languages(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我喜欢rust"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我也喜欢go"}])

    profile = store.get_page("user-profile")

    assert "Preferred programming language: rust、go" in profile.content


def test_promote_user_profile_merges_general_preferences_by_category(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我也喜欢吃火锅"}])
    promote_user_profile_from_messages(store, [{"role": "user", "content": "我还喜欢吃寿司"}])

    profile = store.get_page("user-profile")

    assert "Preference (food): 火锅、寿司" in profile.content
    assert "food" in profile.tags


def test_expand_user_profile_query_adds_semantic_terms_for_identity_and_language() -> None:
    expanded = expand_user_profile_query("我是谁 我喜欢什么编程语言")

    assert "identity" in expanded
    assert "programming-language" in expanded


def test_expand_user_profile_query_adds_semantic_terms_for_drinks() -> None:
    expanded = expand_user_profile_query("我喜欢喝什么")

    assert "drink" in expanded
    assert "beverage" in expanded


def test_expand_user_profile_query_adds_food_terms() -> None:
    expanded = expand_user_profile_query("我喜欢吃什么")

    assert "preference" in expanded
    assert "food" in expanded
