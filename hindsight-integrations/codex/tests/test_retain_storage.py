import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import make_hook_input, make_transcript_file, make_user_config

from hindsight_lite.store import LocalMemoryStore


def _run_retain(hook_input: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HINDSIGHT_LITE_HOME", str(tmp_path / ".hindsight-lite"))
    for key in list(os.environ):
        if key.startswith("HINDSIGHT_") and key != "HINDSIGHT_LITE_HOME":
            monkeypatch.delenv(key, raising=False)
    make_user_config(tmp_path, {"autoMemoryUi": False, "autoReflect": False})

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "retain.py"
    spec = importlib.util.spec_from_file_location("retain_storage_test", script_path)
    if spec is None or spec.loader is None:
        raise AssertionError("retain hook could not be loaded")
    module = importlib.util.module_from_spec(spec)

    with (
        patch("sys.stdin", io.StringIO(json.dumps(hook_input))),
        patch("sys.stdout", io.StringIO()),
    ):
        spec.loader.exec_module(module)
        module.main()


def test_full_session_retain_replaces_previous_growing_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_id = "session-full-snapshot"
    transcript_path = make_transcript_file(
        tmp_path,
        [
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first response"},
        ],
    )
    hook_input = make_hook_input(session_id=session_id, transcript_path=transcript_path)
    _run_retain(hook_input, monkeypatch, tmp_path)

    transcript_path = make_transcript_file(
        tmp_path,
        [
            {"role": "user", "content": "first request"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "second request"},
            {"role": "assistant", "content": "second response"},
        ],
    )
    hook_input = make_hook_input(session_id=session_id, transcript_path=transcript_path)
    _run_retain(hook_input, monkeypatch, tmp_path)

    store = LocalMemoryStore(home=tmp_path / ".hindsight-lite", bank_id="codex")
    events = store.read_session_events(session_id)
    assert len(events) == 1
    assert events[0].metadata["message_count"] == "4"
    assert "second response" in events[0].content
