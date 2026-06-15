from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from hindsight_lite.models import ReflectionTrajectory, ReflectionTrajectoryStep

_FAILURE_PATTERNS = (
    re.compile(r"\bexit_code:\s*[1-9]\d*\b", re.IGNORECASE),
    re.compile(r"\bprocess exited with code [1-9]\d*\b", re.IGNORECASE),
    re.compile(r"\bstatus:\s*(failed|error|cancelled|timed[_ -]?out)\b", re.IGNORECASE),
    re.compile(r"(?:^|\n)FAILED\b"),
    re.compile(r"\b[1-9]\d*\s+failed\b", re.IGNORECASE),
    re.compile(r"\b(traceback|assertionerror|command not found)\b", re.IGNORECASE),
    re.compile(r"(失败|错误|报错|未通过|找不到命令)"),
)
_CORRECTION_PATTERNS = (
    re.compile(r"^(不对|不是这样|错了|你弄错了|重新来|应该是|我说的是)"),
    re.compile(r"\b(that(?:'s| is) wrong|not what i meant|try again|you misunderstood)\b", re.IGNORECASE),
)
_ENVIRONMENT_CONTEXT_PATTERN = re.compile(
    r"<environment_context>.*?</environment_context>",
    re.IGNORECASE | re.DOTALL,
)
_RESULT_HEADER_PATTERNS = (
    re.compile(r"^Chunk ID:.*$", re.MULTILINE),
    re.compile(r"^Wall time:.*$", re.MULTILINE),
    re.compile(r"^Process (?:exited|running).*$", re.MULTILINE),
    re.compile(r"^Original token count:.*$", re.MULTILINE),
    re.compile(r"^Output:\s*$", re.MULTILINE),
)
_LOW_INFORMATION_RESULT_PATTERNS = (
    re.compile(r"(?:status:\s*)?(?:completed|success|succeeded|ok)", re.IGNORECASE),
    re.compile(r"tool completed\.?", re.IGNORECASE),
)


@dataclass(frozen=True)
class ReflectionCandidate:
    query: str
    trigger_reason: str
    trajectory: ReflectionTrajectory


@dataclass(frozen=True)
class ToolAttempt:
    name: str
    input_summary: str
    result: str
    failed: bool
    repeat_count: int = 1


@dataclass(frozen=True)
class UserCorrection:
    content: str


@dataclass
class ReflectionEpisode:
    query: str
    events: list[ToolAttempt | UserCorrection] = field(default_factory=list)
    trigger_reasons: set[str] = field(default_factory=set)
    outcome: str = ""


def extract_reflection_candidate(messages: list[Mapping[str, object]]) -> ReflectionCandidate | None:
    episode = _latest_completed_episode(messages)
    if episode is None:
        return None

    return _build_reflection_candidate(episode)


def _latest_completed_episode(messages: list[Mapping[str, object]]) -> ReflectionEpisode | None:
    current_query = ""
    active_episode: ReflectionEpisode | None = None
    latest_episode: ReflectionEpisode | None = None
    awaiting_outcome: ReflectionEpisode | None = None

    for message in messages:
        role = message.get("role")
        if role == "user":
            user_text = _strip_internal_context(_content_text(message.get("content")))
            if not user_text:
                continue
            awaiting_outcome = None
            if _is_user_correction(user_text):
                if active_episode is None:
                    active_episode = ReflectionEpisode(query=current_query or user_text)
                active_episode.events.append(UserCorrection(content=user_text))
                active_episode.trigger_reasons.add("user_correction")
            else:
                # A new user task is a hard episode boundary. An unrecovered
                # failure from the prior task must not absorb tools from this one.
                current_query = user_text[:500]
                active_episode = None
            continue
        if role != "assistant":
            continue

        assistant_text = _text_blocks(message.get("content"))
        completed_in_message = False
        for attempt in _tool_attempts(message.get("content")):
            if active_episode is None:
                if not attempt.failed or not current_query:
                    continue
                active_episode = ReflectionEpisode(query=current_query)

            _add_episode_attempt(active_episode, attempt)
            if attempt.failed:
                active_episode.trigger_reasons.add("tool_failure")
                awaiting_outcome = None
                continue

            latest_episode = active_episode
            active_episode = None
            awaiting_outcome = latest_episode
            completed_in_message = True

        if assistant_text and awaiting_outcome is not None and (completed_in_message or active_episode is None):
            awaiting_outcome.outcome = assistant_text[:1000]

    return latest_episode


def _add_episode_attempt(episode: ReflectionEpisode, attempt: ToolAttempt) -> None:
    fingerprint = _attempt_fingerprint(attempt)
    for index in range(len(episode.events) - 1, -1, -1):
        existing = episode.events[index]
        if isinstance(existing, UserCorrection):
            break
        if _attempt_fingerprint(existing) != fingerprint:
            continue
        # Keep the latest evidence while representing retries as one graph node.
        episode.events.pop(index)
        episode.events.append(
            ToolAttempt(
                name=attempt.name,
                input_summary=attempt.input_summary,
                result=attempt.result or existing.result,
                failed=attempt.failed,
                repeat_count=existing.repeat_count + 1,
            )
        )
        return
    episode.events.append(attempt)


def _attempt_fingerprint(attempt: ToolAttempt) -> str:
    normalized_input = re.sub(r"\s+", " ", attempt.input_summary).strip().casefold()
    result_class = "failed" if attempt.failed else "success"
    return f"{attempt.name.casefold()}:{normalized_input}:{result_class}"


def _build_reflection_candidate(episode: ReflectionEpisode) -> ReflectionCandidate:
    steps = [
        ReflectionTrajectoryStep(
            id="state-0",
            sequence=0,
            kind="state",
            status="neutral",
            content=episode.query,
        )
    ]
    sequence = 1
    main_parent = "state-0"
    pending_failure: str | None = None
    last_observation = ""

    for event in episode.events:
        if isinstance(event, UserCorrection):
            correction_id = f"user-correction-{sequence}"
            steps.append(
                ReflectionTrajectoryStep(
                    id=correction_id,
                    parent_id=main_parent,
                    sequence=sequence,
                    kind="observation",
                    status="failed",
                    content=event.content,
                )
            )
            pending_failure = correction_id
            last_observation = event.content
            sequence += 1
            continue

        attempt = event
        action_id = f"tool-{sequence}"
        steps.append(
            ReflectionTrajectoryStep(
                id=action_id,
                parent_id=main_parent,
                sequence=sequence,
                kind="tool",
                status="failed" if attempt.failed else "success",
                content=attempt.input_summary,
                tool_name=attempt.name,
                correction_of=pending_failure,
                repeat_count=attempt.repeat_count,
            )
        )
        sequence += 1

        if attempt.result or attempt.failed:
            result_id = f"observation-{sequence}"
            steps.append(
                ReflectionTrajectoryStep(
                    id=result_id,
                    parent_id=action_id,
                    sequence=sequence,
                    kind="observation",
                    status="failed" if attempt.failed else "success",
                    content=attempt.result or f"{attempt.name} failed.",
                    repeat_count=attempt.repeat_count,
                )
            )
            sequence += 1
            if attempt.failed:
                pending_failure = result_id
            else:
                pending_failure = None
                main_parent = result_id
            last_observation = attempt.result
        elif not attempt.failed:
            pending_failure = None
            main_parent = action_id

    outcome = episode.outcome or "The session continued after correcting a failed or rejected attempt."
    steps.append(
        ReflectionTrajectoryStep(
            id=f"outcome-{sequence}",
            parent_id=main_parent,
            sequence=sequence,
            kind="outcome",
            status="success",
            content=outcome,
        )
    )
    reason = "+".join(sorted(episode.trigger_reasons))
    return ReflectionCandidate(
        query=episode.query,
        trigger_reason=reason,
        trajectory=ReflectionTrajectory(
            state=episode.query,
            action="The agent revised its approach after a failed or rejected attempt.",
            observation=last_observation or "The corrective action completed successfully.",
            outcome=outcome,
            lesson="Review this corrected trajectory before promoting a reusable lesson.",
            steps=steps,
        ),
    )


def _tool_attempts(content: object) -> list[ToolAttempt]:
    if not isinstance(content, list):
        return []

    attempts: list[ToolAttempt] = []
    pending_tool: Mapping[str, object] | None = None
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "tool_use":
            pending_tool = block
        elif block_type == "tool_result" and pending_tool is not None:
            attempts.append(_tool_attempt(pending_tool, _content_text(block.get("content"))))
            pending_tool = None
    return attempts


def _tool_attempt(tool: Mapping[str, object], result: str) -> ToolAttempt:
    name = str(tool.get("name") or "tool")
    raw_input = tool.get("input")
    if isinstance(raw_input, Mapping):
        input_summary = _summarize_tool_input(name, raw_input)
    else:
        input_summary = str(raw_input or name)
    summarized_result = _summarize_tool_result(result)
    return ToolAttempt(
        name=name,
        input_summary=input_summary[:240],
        result=summarized_result,
        failed=_is_failure(result),
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def _text_blocks(content: object) -> str:
    return _content_text(content)


def _is_failure(text: str) -> bool:
    return bool(text) and any(pattern.search(text) for pattern in _FAILURE_PATTERNS)


def _is_user_correction(text: str) -> bool:
    stripped = _strip_internal_context(text)
    return bool(stripped) and any(pattern.search(stripped) for pattern in _CORRECTION_PATTERNS)


def _strip_internal_context(text: str) -> str:
    return _ENVIRONMENT_CONTEXT_PATTERN.sub("", text).strip()


def _summarize_tool_input(name: str, raw_input: Mapping[str, object]) -> str:
    command = raw_input.get("cmd")
    if isinstance(command, str) and command.strip():
        return command.strip()
    file_path = raw_input.get("file") or raw_input.get("path")
    if isinstance(file_path, str) and file_path.strip():
        return f"{name}: {file_path.strip()}"
    return json.dumps(dict(raw_input), ensure_ascii=False, sort_keys=True)


def _summarize_tool_result(result: str) -> str:
    summary = result
    for pattern in _RESULT_HEADER_PATTERNS:
        summary = pattern.sub("", summary)
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if not lines:
        return ""
    compact = "\n".join(lines)
    if any(pattern.fullmatch(compact) for pattern in _LOW_INFORMATION_RESULT_PATTERNS):
        return ""
    if len(compact) <= 320:
        return compact
    return f"{compact[:317]}..."
