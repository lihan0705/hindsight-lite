import json
from dataclasses import asdict, dataclass
from pathlib import Path

from hindsight_lite.reflection_cleanup import scan_reflection_cleanup
from hindsight_lite.store import LocalMemoryStore


@dataclass(frozen=True)
class StepPayload:
    id: str
    sequence: int
    kind: str
    status: str
    content: str


def test_scan_reflection_cleanup_reports_repeated_environment_and_oversized_candidates(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    _write_reflection(
        store,
        "repeat-a",
        {
            "type": "reflection_request",
            "id": "repeat-a",
            "query": "$hindsight-lite:memorytree",
            "candidate_trajectory": {
                "state": "$hindsight-lite:memorytree",
                "action": "Open memory tree.",
                "observation": "Tool failed.",
                "outcome": "Retried launcher.",
                "lesson": "Review before promotion.",
                "steps": [
                    asdict(_step("state-0", 0, "state", "neutral", "$hindsight-lite:memorytree")),
                    asdict(
                        _step(
                            "tool-1",
                            1,
                            "tool",
                            "failed",
                            "python3 /Users/gongping/.codex/plugins/cache/personal-local/hindsight-lite/open.py",
                        )
                    ),
                    asdict(_step("observation-2", 2, "observation", "failed", "Operation not permitted")),
                ],
            },
        },
    )
    _write_reflection(
        store,
        "repeat-b",
        {
            "type": "reflection_request",
            "id": "repeat-b",
            "query": "$hindsight-lite:memorytree",
            "candidate_trajectory": {
                "state": "$hindsight-lite:memorytree",
                "action": "Open memory tree again.",
                "observation": "Different follow-up.",
                "outcome": "Retried launcher.",
                "lesson": "Review before promotion.",
                "steps": [asdict(_step("state-0", 0, "state", "neutral", "$hindsight-lite:memorytree"))],
            },
        },
    )
    _write_reflection(
        store,
        "large",
        {
            "type": "reflection_result",
            "id": "large",
            "trajectory": {
                "state": "Need a concise graph.",
                "action": "Captured too many retries.",
                "observation": "The trajectory is noisy.",
                "outcome": "Reviewer should inspect before export.",
                "lesson": "Keep eval records compact.",
                "steps": [
                    asdict(_step(f"failed-{index}", index, "tool", "failed", f"failed command {index}"))
                    for index in range(8)
                ],
            },
        },
    )

    report = scan_reflection_cleanup(store)

    assert report.scanned == 3
    candidates = {candidate.id: candidate for candidate in report.candidates}
    assert set(candidates) == {"repeat-a", "repeat-b", "large"}
    assert candidates["repeat-a"].issue_codes == ["repeated-entry", "environment-noise"]
    assert candidates["repeat-b"].issue_codes == ["repeated-entry"]
    assert candidates["large"].issue_codes == ["oversized-trajectory"]


def test_scan_reflection_cleanup_ignores_clean_reflection(tmp_path: Path) -> None:
    store = LocalMemoryStore(home=tmp_path, bank_id="codex")
    _write_reflection(
        store,
        "clean",
        {
            "type": "reflection_result",
            "id": "clean",
            "trajectory": {
                "state": "Need to verify recall.",
                "action": "Ran the deterministic eval.",
                "observation": "The expected memory ranked first.",
                "outcome": "The eval passed.",
                "lesson": "Keep local eval fixtures small.",
            },
        },
    )

    report = scan_reflection_cleanup(store)

    assert report.scanned == 1
    assert report.candidates == []


def _write_reflection(store: LocalMemoryStore, reflection_id: str, payload: object) -> None:
    path = store.paths.reflections_dir / f"{reflection_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _step(step_id: str, sequence: int, kind: str, status: str, content: str) -> StepPayload:
    return StepPayload(id=step_id, sequence=sequence, kind=kind, status=status, content=content)
