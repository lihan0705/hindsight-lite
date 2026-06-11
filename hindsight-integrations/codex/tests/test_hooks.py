"""End-to-end tests for recall.py and retain.py hook scripts.

Mocks the Codex hook runtime:
  - stdin  → io.StringIO(json.dumps(hook_input))
  - stdout → io.StringIO() captured for assertions
  - urllib.request.urlopen → fake HTTP responses
  - HOME → tmp_path (isolates ~/.hindsight/codex.json and state)
"""

import importlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import FakeHTTPResponse, make_hook_input, make_memory, make_transcript_file, make_user_config

from hindsight_lite.models import SessionMemoryEvent
from hindsight_lite.store import LocalMemoryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_hook(module_name, hook_input, monkeypatch, tmp_path, urlopen_side_effect=None, user_config=None):
    """Import and run a hook script's main() with mocked stdin/stdout/HTTP."""
    # Isolate HOME so ~/.hindsight/codex.json and state land in tmp_path
    monkeypatch.setenv("HOME", str(tmp_path))

    # Strip real HINDSIGHT_* env vars
    for k in list(os.environ):
        if k.startswith("HINDSIGHT_"):
            monkeypatch.delenv(k, raising=False)

    # Isolate local hindsight-lite memory files.
    monkeypatch.setenv("HINDSIGHT_LITE_HOME", str(tmp_path / ".hindsight-lite"))

    # Write user config (enables retain on every turn + any overrides)
    cfg = {"retainEveryNTurns": 1, "autoRecall": True, "autoRetain": True}
    if user_config:
        cfg.update(user_config)
    make_user_config(tmp_path, cfg)

    stdin_data = io.StringIO(json.dumps(hook_input))
    stdout_capture = io.StringIO()

    # Force reimport so the module picks up patched env
    scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
    spec = importlib.util.spec_from_file_location(
        module_name + "_fresh", os.path.join(scripts_dir, f"{module_name}.py")
    )
    mod = importlib.util.module_from_spec(spec)

    default_response = FakeHTTPResponse({"results": []})
    side_effect = urlopen_side_effect or (lambda *a, **kw: default_response)

    with (
        patch("sys.stdin", stdin_data),
        patch("sys.stdout", stdout_capture),
        patch("urllib.request.urlopen", side_effect=side_effect),
    ):
        spec.loader.exec_module(mod)
        mod.main()

    return stdout_capture.getvalue()


def _retained_events(tmp_path, session_id="sess-abc123"):
    return LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex").read_session_events(session_id)


# ---------------------------------------------------------------------------
# session start hook
# ---------------------------------------------------------------------------


class TestSessionStartHook:
    def test_initializes_local_bank(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(session_id="sess-start")

        _run_hook("session_start", hook_input, monkeypatch, tmp_path)

        bank_dir = tmp_path / ".hindsight-lite" / "banks" / "codex"
        assert (bank_dir / "sessions").is_dir()
        assert (bank_dir / "pages").is_dir()
        assert (bank_dir / "reflections").is_dir()

    def test_disabled_memory_skips_local_bank_init(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(session_id="sess-start")

        _run_hook(
            "session_start", hook_input, monkeypatch, tmp_path, user_config={"autoRecall": False, "autoRetain": False}
        )

        assert not (tmp_path / ".hindsight-lite").exists()


# ---------------------------------------------------------------------------
# recall hook
# ---------------------------------------------------------------------------


class TestRecallHook:
    def test_outputs_additional_context_when_memories_found(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(page_id="france", title="France", content="Paris is the capital of France")

        hook_input = make_hook_input(prompt="What is the capital of France?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "Paris is the capital of France" in context
        assert "<hindsight_lite_memories>" in context

    def test_no_output_when_no_memories(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(prompt="hello there world")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)
        assert output.strip() == ""

    def test_no_output_for_short_prompt(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(prompt="hi")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)
        assert output.strip() == ""

    @pytest.mark.parametrize(
        "prompt",
        ["memorytree", "/memorytree", "$memorytree", "$hindsight-lite:memorytree"],
    )
    def test_memorytree_prompt_skips_recall_context(self, monkeypatch, tmp_path, prompt):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.append_session_event(
            SessionMemoryEvent(
                type="session_memory",
                id="evt-memorytree-history",
                timestamp="2026-06-11T07:00:00Z",
                bank_id="codex",
                session_id="memorytree-history",
                source="codex",
                document_id="memorytree-history",
                content="Previously opened memorytree with verbose tool output.",
                tags=["memorytree"],
            )
        )

        output = _run_hook("recall", make_hook_input(prompt=prompt), monkeypatch, tmp_path)

        assert output.strip() == ""

    def test_graceful_when_local_store_has_no_matches(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(prompt="What is my project about?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)
        assert output.strip() == ""

    def test_output_format_matches_codex_spec(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(page_id="python", title="Python", content="User prefers Python language choices")

        hook_input = make_hook_input(prompt="What language should I use?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "additionalContext" in data["hookSpecificOutput"]

    def test_multi_turn_context_from_transcript(self, monkeypatch, tmp_path):
        """When recallContextTurns > 1, prior transcript is included in query."""
        messages = [
            {"role": "user", "content": "I use Python for all my scripts"},
            {"role": "assistant", "content": "Noted!"},
        ]
        transcript = make_transcript_file(tmp_path, messages)

        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(page_id="python", title="Python", content="Python is the user's default scripting language.")

        hook_input = make_hook_input(prompt="What language should I use?", transcript_path=transcript)
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path, user_config={"recallContextTurns": 2})

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "Python is the user's default scripting language." in context

    def test_recall_max_results_is_configurable(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(page_id="python", title="Python", content="User prefers Python language choices")
        store.write_page(page_id="ruff", title="Ruff", content="User prefers Python language ruff checks")

        hook_input = make_hook_input(prompt="What language should I use?")
        output = _run_hook(
            "recall",
            hook_input,
            monkeypatch,
            tmp_path,
            user_config={"recallMaxResults": 1},
        )

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert context.count(" [page] ") == 1

    def test_recall_excerpt_budget_is_configurable(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(
            page_id="compact",
            title="Compact",
            content=" ".join(["compact"] * 60),
        )

        hook_input = make_hook_input(prompt="compact memory please")
        output = _run_hook(
            "recall",
            hook_input,
            monkeypatch,
            tmp_path,
            user_config={"recallMaxExcerptChars": 48},
        )

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        memory_line = next(line for line in context.splitlines() if line.startswith("- "))
        assert "..." in memory_line
        assert len(memory_line.split(" [page] ")[0]) <= 50

    def test_disabled_auto_recall_produces_no_output(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(prompt="What is the capital of France?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path, user_config={"autoRecall": False})
        assert output.strip() == ""

    def test_recall_filters_solved_bugs_to_recent_window(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        now = datetime.now(timezone.utc)
        store.append_session_event(
            SessionMemoryEvent(
                type="session_memory",
                id="evt-recent-bug",
                timestamp=(now - timedelta(days=5)).isoformat().replace("+00:00", "Z"),
                bank_id="codex",
                session_id="recent-auth",
                source="codex",
                document_id="codex-recent-auth",
                content="Resolved auth redirect loop bug by refreshing session state before redirect checks.",
                tags=["debugging"],
            )
        )
        store.append_session_event(
            SessionMemoryEvent(
                type="session_memory",
                id="evt-old-bug",
                timestamp=(now - timedelta(days=20)).isoformat().replace("+00:00", "Z"),
                bank_id="codex",
                session_id="old-cache",
                source="codex",
                document_id="codex-old-cache",
                content="Resolved stale cache bug by clearing the generated index.",
                tags=["debugging"],
            )
        )

        hook_input = make_hook_input(prompt="过去10天我解决了哪些bug")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "auth redirect loop bug" in context
        assert "stale cache bug" not in context


# ---------------------------------------------------------------------------
# file context hook
# ---------------------------------------------------------------------------


class TestFileContextHook:
    def test_injects_compact_context_for_read_file(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(
            page_id="cli-routing",
            title="CLI Routing",
            content="hindsight_lite/cli.py keeps user-facing memory commands in one argparse surface.",
        )
        hook_input = make_hook_input()
        hook_input.update(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "hindsight_lite/cli.py"},
            }
        )

        output = _run_hook("file_context", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "permissionDecision" not in data["hookSpecificOutput"]
        assert "<hindsight_lite_file_context>" in context
        assert "hindsight_lite/cli.py keeps user-facing memory commands" in context

    def test_file_context_skips_when_disabled(self, monkeypatch, tmp_path):
        hook_input = make_hook_input()
        hook_input.update(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "hindsight_lite/cli.py"},
            }
        )

        output = _run_hook("file_context", hook_input, monkeypatch, tmp_path, user_config={"autoFileContext": False})

        assert output.strip() == ""

    def test_file_context_skips_memory_store_paths(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(
            page_id="memory-path",
            title="Memory Path",
            content="Reading memory files should not recursively inject file context.",
        )
        hook_input = make_hook_input()
        hook_input.update(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": str(tmp_path / ".codex" / "memories")},
            }
        )

        output = _run_hook("file_context", hook_input, monkeypatch, tmp_path)

        assert output.strip() == ""

    def test_dispatcher_routes_pre_tool_use_to_file_context(self, monkeypatch, tmp_path):
        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        store.write_page(
            page_id="store-routing",
            title="Store Routing",
            content="hindsight_lite/store.py owns Markdown page reads and JSONL session writes.",
        )
        hook_input = make_hook_input()
        hook_input.update(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "hindsight_lite/store.py"},
            }
        )

        output = _run_hook("codex_hook", hook_input, monkeypatch, tmp_path)

        data = json.loads(output)
        assert data["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "hindsight_lite/store.py owns Markdown page reads" in data["hookSpecificOutput"]["additionalContext"]


# ---------------------------------------------------------------------------
# retain hook
# ---------------------------------------------------------------------------


class TestRetainHook:
    def test_packaged_defaults_retain_on_each_stop(self, monkeypatch, tmp_path):
        from lib.config import load_config

        monkeypatch.setenv("HOME", str(tmp_path))
        for key in list(os.environ):
            if key.startswith("HINDSIGHT_"):
                monkeypatch.delenv(key, raising=False)

        assert load_config()["retainEveryNTurns"] == 1

    def test_writes_transcript_to_local_store(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        events = _retained_events(tmp_path)
        assert len(events) == 1
        assert "hello" in events[0].content

    def test_retain_refreshes_memory_tree_ui(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "我喜欢喝柠檬水"}, {"role": "assistant", "content": "记住了。"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        ui_path = tmp_path / ".hindsight-lite" / "banks" / "codex" / "memory-tree.html"
        assert ui_path.exists()
        assert "柠檬水" in ui_path.read_text(encoding="utf-8")

    def test_retain_can_skip_memory_tree_ui_refresh(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path, user_config={"autoMemoryUi": False})

        ui_path = tmp_path / ".hindsight-lite" / "banks" / "codex" / "memory-tree.html"
        assert not ui_path.exists()

    def test_no_retain_on_empty_transcript(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(transcript_path="/nonexistent/transcript.jsonl")

        _run_hook("retain", hook_input, monkeypatch, tmp_path)
        assert _retained_events(tmp_path) == []

    def test_strips_memory_tags_before_retaining(self, monkeypatch, tmp_path):
        messages = [
            {"role": "user", "content": "<hindsight_memories>old memories</hindsight_memories> actual question"},
            {"role": "assistant", "content": "sure!"},
        ]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        content = _retained_events(tmp_path)[0].content
        assert "old memories" not in content
        assert "actual question" in content

    def test_retain_records_message_count_metadata(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        assert _retained_events(tmp_path)[0].metadata["message_count"] == "2"

    def test_retain_includes_codex_context_label(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        assert _retained_events(tmp_path)[0].source == "codex"

    def test_retain_skips_below_every_n_turns_threshold(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        # retainEveryNTurns=3 — first call should be skipped
        _run_hook("retain", hook_input, monkeypatch, tmp_path, user_config={"retainEveryNTurns": 3})
        assert _retained_events(tmp_path) == []

    def test_retain_uses_session_id_as_document_id(self, monkeypatch, tmp_path):
        messages = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]
        transcript = make_transcript_file(tmp_path, messages)
        hook_input = make_hook_input(transcript_path=transcript, session_id="sess-doc-test")

        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        assert _retained_events(tmp_path, session_id="sess-doc-test")[0].document_id == "sess-doc-test"

    def test_retain_does_not_call_http(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "test"}, {"role": "assistant", "content": "response"}]
        transcript = make_transcript_file(tmp_path, messages)
        hook_input = make_hook_input(transcript_path=transcript)

        def raise_error(req, timeout=None):
            raise OSError("HTTP should not be called")

        _run_hook("retain", hook_input, monkeypatch, tmp_path, urlopen_side_effect=raise_error)
        assert "test" in _retained_events(tmp_path)[0].content

    def test_disabled_auto_retain_does_not_call_api(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}]
        transcript = make_transcript_file(tmp_path, messages)
        hook_input = make_hook_input(transcript_path=transcript)

        _run_hook("retain", hook_input, monkeypatch, tmp_path, user_config={"autoRetain": False})
        assert _retained_events(tmp_path) == []

    def test_reads_codex_response_item_format(self, monkeypatch, tmp_path):
        """Retain should correctly parse the actual Codex on-disk transcript format."""
        messages = [
            {"role": "user", "content": "I like TypeScript"},
            {"role": "assistant", "content": "Great choice!"},
        ]
        transcript = make_transcript_file(tmp_path, messages, codex_format=True)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        content = _retained_events(tmp_path)[0].content
        assert "TypeScript" in content

    def test_promotes_user_profile_and_recalls_across_sessions(self, monkeypatch, tmp_path):
        messages = [
            {"role": "user", "content": "我是jack 我爱rust 我喜欢喝柠檬水"},
            {"role": "assistant", "content": "记住了。"},
        ]
        transcript = make_transcript_file(tmp_path, messages)

        retain_input = make_hook_input(transcript_path=transcript, session_id="sess-profile-source")
        _run_hook("retain", retain_input, monkeypatch, tmp_path)

        store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
        profile = store.get_page("user-profile")
        assert "jack" in profile.content
        assert "rust" in profile.content
        assert "柠檬水" in profile.content
        assert "user" in profile.tags
        assert "programming-language" in profile.tags
        assert "drink" in profile.tags

        recall_input = make_hook_input(
            prompt="我是谁 我喜欢什么编程语言 我喜欢喝什么",
            session_id="sess-profile-question",
        )
        output = _run_hook("recall", recall_input, monkeypatch, tmp_path)

        data = json.loads(output)
        context = data["hookSpecificOutput"]["additionalContext"]
        assert "jack" in context
        assert "rust" in context
        assert "柠檬水" in context
        assert "[page] (user-profile)" in context


class TestCodexPluginConfig:
    def test_plugin_manifest_and_hooks_are_relocatable(self):
        root_dir = Path(__file__).resolve().parents[3]
        manifest_path = root_dir / ".codex-plugin" / "plugin.json"
        hook_path = root_dir / "hindsight-integrations" / "codex" / "hooks" / "plugin-hooks.json"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        hooks = json.loads(hook_path.read_text(encoding="utf-8"))
        serialized_hooks = json.dumps(hooks)

        assert manifest["name"] == "hindsight-lite"
        assert "__SCRIPTS_DIR__" not in serialized_hooks
        for event_name in ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"):
            command = hooks["hooks"][event_name][0]["hooks"][0]["command"]
            assert "HINDSIGHT_LITE_PLUGIN_ROOT" in command
            assert "PYTHONPATH" in command
            assert f'codex_hook.py" {event_name}' in command
