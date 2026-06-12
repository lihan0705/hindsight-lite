import json
from pathlib import Path

from hindsight_lite.models import (
    RecallResult,
    ReflectionPacket,
    ReflectionResult,
    ReflectionTrajectory,
    ReflectionTrajectoryStep,
)
from hindsight_lite.reflection_dataset import build_reflection_dataset_examples, export_reflection_dataset
from hindsight_lite.store import LocalMemoryStore


def test_build_reflection_dataset_examples_pairs_requests_and_results(tmp_path: Path) -> None:
    store = _store_with_reflection_pair(tmp_path)
    store.write_reflection_result(
        ReflectionResult(
            type="reflection_result",
            id="orphan-result",
            request_id="missing-request",
            timestamp="2026-05-30T10:05:00Z",
            bank_id="codex",
            session_id="session-1",
            trajectory=ReflectionTrajectory(
                state="state",
                action="action",
                observation="observation",
                outcome="outcome",
                lesson="lesson",
            ),
            confidence=0.4,
        )
    )
    store.write_reflection_result(
        ReflectionResult(
            type="reflection_result",
            id="other-bank-result",
            request_id="reflect-1",
            timestamp="2026-05-30T10:06:00Z",
            bank_id="other",
            session_id="session-1",
            trajectory=ReflectionTrajectory(
                state="state",
                action="action",
                observation="observation",
                outcome="outcome",
                lesson="lesson",
            ),
            confidence=0.4,
        )
    )

    examples = build_reflection_dataset_examples(store)

    assert [example.result_id for example in examples] == ["result-1"]
    example = examples[0]
    assert example.request_id == "reflect-1"
    assert example.query == "How should memory support eval?"
    assert example.retrieved_context[0].id == "project-rules"
    assert example.task_context == {"repo": "hindsight-lite"}
    assert example.trajectory.lesson == "Keep request/result pairs explicit for dataset export."
    assert example.confidence == 0.82


def test_export_reflection_dataset_writes_jsonl(tmp_path: Path) -> None:
    store = _store_with_reflection_pair(tmp_path)
    output_path = tmp_path / "exports" / "reflection-dataset.jsonl"

    result = export_reflection_dataset(store=store, output_path=output_path)

    assert result.output_path == output_path
    assert result.example_count == 1
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["request_id"] == "reflect-1"
    assert rows[0]["result_id"] == "result-1"
    assert rows[0]["retrieved_context"][0]["source"] == "page"
    assert rows[0]["trajectory"]["lesson"] == "Keep request/result pairs explicit for dataset export."
    assert rows[0]["trajectory"]["steps"][1]["correction_of"] == "failed-export"


def _store_with_reflection_pair(tmp_path: Path) -> LocalMemoryStore:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    store.write_reflection_packet(
        ReflectionPacket(
            type="reflection_request",
            id="reflect-1",
            timestamp="2026-05-30T10:00:00Z",
            bank_id="codex",
            session_id="session-1",
            query="How should memory support eval?",
            retrieved_context=[
                RecallResult(
                    id="project-rules",
                    source="page",
                    path="pages/project-rules.md",
                    score=3.0,
                    title="Project Rules",
                    excerpt="Keep eval data local and inspectable.",
                    metadata={"source": "test"},
                )
            ],
            task_context={"repo": "hindsight-lite"},
            reflection_prompt="Return a reflection_result.",
        )
    )
    store.write_reflection_result(
        ReflectionResult(
            type="reflection_result",
            id="result-1",
            request_id="reflect-1",
            timestamp="2026-05-30T10:01:00Z",
            bank_id="codex",
            session_id="session-1",
            trajectory=ReflectionTrajectory(
                state="Need an eval-ready memory artifact.",
                action="Export paired reflection data.",
                observation="The request and result share an id link.",
                outcome="A JSONL row can be consumed by later evaluation tooling.",
                lesson="Keep request/result pairs explicit for dataset export.",
                steps=[
                    ReflectionTrajectoryStep(
                        id="failed-export",
                        sequence=0,
                        kind="action",
                        status="failed",
                        content="Tried to export an unpaired result.",
                    ),
                    ReflectionTrajectoryStep(
                        id="paired-export",
                        parent_id="failed-export",
                        sequence=1,
                        kind="action",
                        status="success",
                        content="Paired the result with its request before export.",
                        correction_of="failed-export",
                    ),
                ],
            ),
            durable_facts=["Reflection requests and results are local JSON files."],
            reusable_procedures=["Export only paired request/result records."],
            uncertain_items=[],
            confidence=0.82,
        )
    )
    return store
