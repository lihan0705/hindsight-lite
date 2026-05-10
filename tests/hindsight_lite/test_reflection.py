import json
from pathlib import Path

from hindsight_lite.reflection import create_reflection_packet
from hindsight_lite.store import LocalMemoryStore


def test_create_reflection_packet_retrieves_context_and_writes_json(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_page(
        page_id="rl-trajectory",
        title="RL Trajectory",
        content="Reflect packets preserve state action observation outcome lesson for agentic RL data.",
    )

    packet = create_reflection_packet(
        store=store,
        session_id="session-1",
        query="How should reflect preserve agentic RL data?",
        task_context={"repo": "hindsight-lite"},
    )

    assert packet.type == "reflection_request"
    assert packet.bank_id == "codex"
    assert packet.session_id == "session-1"
    assert packet.retrieved_context[0].id == "rl-trajectory"
    assert "state -> action -> observation -> outcome -> lesson" in packet.reflection_prompt

    saved_path = store.paths.reflections_dir / f"{packet.id}.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["type"] == "reflection_request"
    assert saved["retrieved_context"][0]["id"] == "rl-trajectory"
