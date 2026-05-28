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
from unittest.mock import patch

import pytest
from conftest import FakeHTTPResponse, make_hook_input, make_memory, make_transcript_file, make_user_config

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

    def test_disabled_auto_recall_produces_no_output(self, monkeypatch, tmp_path):
        hook_input = make_hook_input(prompt="What is the capital of France?")
        output = _run_hook("recall", hook_input, monkeypatch, tmp_path, user_config={"autoRecall": False})
        assert output.strip() == ""


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
        assert data["hookSpecificOutput"]["permissionDecision"] == "allow"
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
    def test_writes_transcript_to_local_store(self, monkeypatch, tmp_path):
        messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        transcript = make_transcript_file(tmp_path, messages)

        hook_input = make_hook_input(transcript_path=transcript)
        _run_hook("retain", hook_input, monkeypatch, tmp_path)

        events = _retained_events(tmp_path)
        assert len(events) == 1
        assert "hello" in events[0].content

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
