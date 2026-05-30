import json
from pathlib import Path

from hindsight_lite.models import ReflectionResult, ReflectionTrajectory
from hindsight_lite.reflection import ReflectionResultError, create_reflection_packet, parse_reflection_result
from hindsight_lite.store import LocalMemoryStore, UnsafeReflectionIdError


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
    assert "trajectory: state -> action -> observation -> outcome -> lesson" in packet.reflection_prompt
    assert packet.result_schema.version == "1.0"
    assert packet.result_schema.result_type == "reflection_result"
    assert [field.name for field in packet.result_schema.fields] == [
        "trajectory",
        "durable_facts",
        "reusable_procedures",
        "uncertain_items",
        "confidence",
    ]

    saved_path = store.paths.reflections_dir / f"{packet.id}.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["type"] == "reflection_request"
    assert saved["retrieved_context"][0]["id"] == "rl-trajectory"
    assert saved["result_schema"]["result_type"] == "reflection_result"
    assert saved["result_schema"]["fields"][0]["name"] == "trajectory"


def test_reflection_result_schema_matches_result_model() -> None:
    result = ReflectionResult(
        type="reflection_result",
        id="result-1",
        request_id="reflect-1",
        timestamp="2026-05-28T10:00:00Z",
        bank_id="codex",
        session_id="session-1",
        trajectory=ReflectionTrajectory(
            state="Need to make memory data reviewable.",
            action="Added an editable memory tree page flow.",
            observation="Pages can be edited and downloaded while sessions remain read-only.",
            outcome="The agent has a cleaner review loop for long-term memory.",
            lesson="Keep mutable knowledge pages separate from audit-style event logs.",
        ),
        durable_facts=["Pages are user-editable long-term memory."],
        reusable_procedures=["Review pages in the memory tree before promoting new facts."],
        uncertain_items=["Whether direct browser file writes are worth the permission tradeoff."],
        confidence=0.82,
    )

    assert result.trajectory.lesson == "Keep mutable knowledge pages separate from audit-style event logs."
    assert result.durable_facts == ["Pages are user-editable long-term memory."]
    assert result.confidence == 0.82


def test_parse_reflection_result_validates_and_writes_json(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    result = parse_reflection_result(
        {
            "type": "reflection_result",
            "id": "result-1",
            "request_id": "reflect-1",
            "timestamp": "2026-05-30T10:00:00Z",
            "bank_id": "codex",
            "session_id": "session-1",
            "trajectory": {
                "state": "Need a stable eval record.",
                "action": "Stored a typed reflection result.",
                "observation": "The result is a local JSON file.",
                "outcome": "Future eval tooling can inspect it.",
                "lesson": "Keep request and result records explicit.",
            },
            "durable_facts": ["Reflection results are stored locally."],
            "reusable_procedures": ["Validate evaluator output before writing memory."],
            "uncertain_items": [],
            "confidence": 0.9,
        }
    )

    saved_path = store.write_reflection_result(result)

    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["type"] == "reflection_result"
    assert saved["request_id"] == "reflect-1"
    assert saved["trajectory"]["lesson"] == "Keep request and result records explicit."


def test_parse_reflection_result_rejects_invalid_confidence() -> None:
    try:
        parse_reflection_result(
            {
                "type": "reflection_result",
                "id": "result-1",
                "request_id": "reflect-1",
                "timestamp": "2026-05-30T10:00:00Z",
                "bank_id": "codex",
                "session_id": "session-1",
                "trajectory": {
                    "state": "state",
                    "action": "action",
                    "observation": "observation",
                    "outcome": "outcome",
                    "lesson": "lesson",
                },
                "confidence": 1.2,
            }
        )
    except ReflectionResultError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("expected invalid confidence to be rejected")


def test_write_reflection_result_rejects_unsafe_id(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    result = ReflectionResult(
        type="reflection_result",
        id="../escape",
        request_id="reflect-1",
        timestamp="2026-05-30T10:00:00Z",
        bank_id="codex",
        session_id="session-1",
        trajectory=ReflectionTrajectory(
            state="state",
            action="action",
            observation="observation",
            outcome="outcome",
            lesson="lesson",
        ),
        confidence=0.5,
    )

    try:
        store.write_reflection_result(result)
    except UnsafeReflectionIdError as exc:
        assert "../escape" in str(exc)
    else:
        raise AssertionError("expected unsafe reflection id to be rejected")
