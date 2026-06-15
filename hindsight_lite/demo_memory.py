from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from hindsight_lite.index import rebuild_recall_index, recall_index_path
from hindsight_lite.models import (
    ReflectionPacket,
    ReflectionResult,
    ReflectionTrajectory,
    ReflectionTrajectoryStep,
    SessionMemoryEvent,
)
from hindsight_lite.store import LocalMemoryStore


class DemoMemoryExistsError(FileExistsError):
    pass


@dataclass(frozen=True)
class DemoMemorySeedResult:
    pages: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    reflections: list[str] = field(default_factory=list)
    index_files: list[str] = field(default_factory=list)


def seed_demo_memory(store: LocalMemoryStore, overwrite: bool = False) -> DemoMemorySeedResult:
    targets = [
        store.paths.pages_dir / "project-direction.md",
        store.paths.pages_dir / "coding-preferences.md",
        store.paths.sessions_dir / "auth-redirect-loop.jsonl",
        store.paths.sessions_dir / "memory-ui-feedback.jsonl",
        store.paths.reflections_dir / "ui-review-reflection.json",
        store.paths.reflections_dir / "ui-review-success.json",
        store.paths.reflections_dir / "ui-review-negative.json",
        recall_index_path(store),
    ]
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise DemoMemoryExistsError(", ".join(str(path) for path in existing))

    pages = _write_demo_pages(store)
    sessions = _write_demo_sessions(store)
    reflections = _write_demo_reflections(store)
    index_files = _write_demo_index(store)
    return DemoMemorySeedResult(pages=pages, sessions=sessions, reflections=reflections, index_files=index_files)


def _write_demo_pages(store: LocalMemoryStore) -> list[str]:
    direction = store.write_page(
        page_id="project-direction",
        title="Project Direction",
        content="\n".join(
            [
                "hindsight-lite is a local-first memory runtime for coding agents.",
                "",
                "The repo should stay small: no server, no daemon, no database, and no generated clients.",
                "",
                "Good contributions make memory easier to inspect, edit, recall, or evaluate.",
            ]
        ),
        tags=["direction", "architecture"],
        metadata={"source": "demo"},
    )
    preferences = store.write_page(
        page_id="coding-preferences",
        title="Coding Preferences",
        content="\n".join(
            [
                "Prefer typed dataclasses for known memory shapes.",
                "Keep sessions and reflections append-only or read-only in UI flows.",
                "Use focused tests before opening a merge request.",
            ]
        ),
        tags=["preferences", "workflow"],
        metadata={"source": "demo"},
    )
    return [direction.id, preferences.id]


def _write_demo_sessions(store: LocalMemoryStore) -> list[str]:
    auth_events = [
        SessionMemoryEvent(
            type="session_memory",
            id="demo-auth-redirect-loop-1",
            timestamp="2026-05-20T09:15:00Z",
            bank_id=store.paths.bank_id,
            session_id="auth-redirect-loop",
            source="codex",
            document_id="codex-auth-redirect-loop",
            content="Investigated an auth redirect loop. The useful clue was that middleware ran before cookie refresh.",
            tags=["debugging", "auth"],
            metadata={"source": "demo"},
        ),
        SessionMemoryEvent(
            type="session_memory",
            id="demo-auth-redirect-loop-2",
            timestamp="2026-05-20T09:34:00Z",
            bank_id=store.paths.bank_id,
            session_id="auth-redirect-loop",
            source="codex",
            document_id="codex-auth-redirect-loop",
            content="Resolution: refresh session state before redirect checks and add a regression test for stale cookies.",
            tags=["fix", "test"],
            metadata={"source": "demo"},
        ),
    ]
    ui_events = [
        SessionMemoryEvent(
            type="session_memory",
            id="demo-memory-ui-feedback-1",
            timestamp="2026-05-24T14:05:00Z",
            bank_id=store.paths.bank_id,
            session_id="memory-ui-feedback",
            source="codex",
            document_id="codex-memory-ui-feedback",
            content="User wanted a tree-like memory UI that can show pages, sessions, reflections, and index data together.",
            tags=["ui", "memory-tree"],
            metadata={"source": "demo"},
        ),
        SessionMemoryEvent(
            type="session_memory",
            id="demo-memory-ui-feedback-2",
            timestamp="2026-05-24T14:42:00Z",
            bank_id=store.paths.bank_id,
            session_id="memory-ui-feedback",
            source="codex",
            document_id="codex-memory-ui-feedback",
            content="Design decision: allow editing Markdown pages, keep sessions/reflections read-only, and download pages with frontmatter.",
            tags=["ui", "decision"],
            metadata={"source": "demo"},
        ),
    ]
    _write_session_file(store, "auth-redirect-loop", auth_events)
    _write_session_file(store, "memory-ui-feedback", ui_events)
    return ["auth-redirect-loop", "memory-ui-feedback"]


def _write_session_file(store: LocalMemoryStore, session_id: str, events: list[SessionMemoryEvent]) -> None:
    session_path = store.paths.sessions_dir / f"{session_id}.jsonl"
    lines = [json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) for event in events]
    session_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_demo_reflections(store: LocalMemoryStore) -> list[str]:
    packet = ReflectionPacket(
        type="reflection_request",
        id="ui-review-reflection",
        timestamp="2026-05-24T15:00:00Z",
        bank_id=store.paths.bank_id,
        session_id="memory-ui-feedback",
        query="What should the memory tree UI make easier to evaluate?",
        retrieved_context=[],
        task_context={"feature": "editable memory tree", "source": "demo"},
        reflection_prompt="Summarize whether the UI makes long-term memory review easier.",
    )
    store.write_reflection_packet(packet)
    success = ReflectionResult(
        type="reflection_result",
        id="ui-review-success",
        request_id=packet.id,
        timestamp="2026-05-24T15:07:00Z",
        bank_id=store.paths.bank_id,
        session_id="memory-ui-feedback",
        trajectory=ReflectionTrajectory(
            state="Need to make memory review inspectable without a server.",
            action="Render pages, sessions, and reflections in one static tree UI.",
            observation="Editable pages remain separate from read-only audit records.",
            outcome="The UI made review faster while preserving local files as source of truth.",
            lesson="Keep the graph deterministic and tied to source files.",
            steps=[
                ReflectionTrajectoryStep(
                    id="inspect-source",
                    sequence=0,
                    kind="state",
                    status="neutral",
                    content="Need to update the memory UI from the current generated output.",
                ),
                ReflectionTrajectoryStep(
                    id="stale-preview",
                    parent_id="inspect-source",
                    sequence=1,
                    kind="action",
                    status="failed",
                    content="Used a stale preview without checking the generated HTML.",
                ),
                ReflectionTrajectoryStep(
                    id="verify-output",
                    parent_id="inspect-source",
                    sequence=2,
                    kind="tool",
                    status="success",
                    content="Regenerated and inspected the current memory tree output.",
                    tool_name="memory-ui",
                    correction_of="stale-preview",
                ),
                ReflectionTrajectoryStep(
                    id="final-result",
                    parent_id="verify-output",
                    sequence=3,
                    kind="outcome",
                    status="success",
                    content="The final preview matched the source files and trajectory data.",
                ),
            ],
        ),
        durable_facts=["The memory UI can expose reflection results as local trajectory samples."],
        reusable_procedures=["Review graph branches before promoting reflection lessons into pages."],
        uncertain_items=[],
        confidence=0.86,
    )
    negative = ReflectionResult(
        type="reflection_result",
        id="ui-review-negative",
        request_id=packet.id,
        timestamp="2026-05-24T15:12:00Z",
        bank_id=store.paths.bank_id,
        session_id="memory-ui-feedback",
        trajectory=ReflectionTrajectory(
            state="Agent needed to update the memory UI preview.",
            action="Used an old draft instead of checking the generated HTML.",
            observation="The preview missed the trajectory graph and gave reviewers stale evidence.",
            outcome="Task failed because the agent treated a stale draft as final.",
            lesson="Treat stale-preview mistakes as negative RL trajectory samples.",
        ),
        durable_facts=[],
        reusable_procedures=[],
        uncertain_items=["A reviewer should confirm whether this sample is useful for training export."],
        confidence=0.28,
    )
    store.write_reflection_result(success)
    store.write_reflection_result(negative)
    return [packet.id, success.id, negative.id]


def _write_demo_index(store: LocalMemoryStore) -> list[str]:
    rebuild_recall_index(store)
    return [recall_index_path(store).name]
