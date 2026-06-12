from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

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


def extract_reflection_candidate(messages: list[Mapping[str, object]]) -> ReflectionCandidate | None:
    query = _first_user_text(messages)
    if not query:
        return None

    steps = [
        ReflectionTrajectoryStep(
            id="state-0",
            sequence=0,
            kind="state",
            status="neutral",
            content=query,
        )
    ]
    sequence = 1
    main_parent = "state-0"
    pending_failure: str | None = None
    recovered_failures = 0
    trigger_reasons: set[str] = set()
    last_observation = ""

    for message in messages:
        role = message.get("role")
        if role == "user":
            user_text = _content_text(message.get("content"))
            if user_text != query and _is_user_correction(user_text):
                correction_id = f"user-correction-{sequence}"
                steps.append(
                    ReflectionTrajectoryStep(
                        id=correction_id,
                        parent_id=main_parent,
                        sequence=sequence,
                        kind="observation",
                        status="failed",
                        content=user_text,
                    )
                )
                pending_failure = correction_id
                trigger_reasons.add("user_correction")
                last_observation = user_text
                sequence += 1
            continue
        if role != "assistant":
            continue

        attempts = _tool_attempts(message.get("content"))
        for attempt in attempts:
            if not attempt.failed and pending_failure is None:
                continue
            action_id = f"tool-{sequence}"
            action_parent = main_parent
            steps.append(
                ReflectionTrajectoryStep(
                    id=action_id,
                    parent_id=action_parent,
                    sequence=sequence,
                    kind="tool",
                    status="failed" if attempt.failed else "success",
                    content=attempt.input_summary,
                    tool_name=attempt.name,
                    correction_of=pending_failure,
                )
            )
            if pending_failure is not None and not attempt.failed:
                recovered_failures += 1
            sequence += 1

            result_id = f"observation-{sequence}"
            steps.append(
                ReflectionTrajectoryStep(
                    id=result_id,
                    parent_id=action_id,
                    sequence=sequence,
                    kind="observation",
                    status="failed" if attempt.failed else "success",
                    content=attempt.result or f"{attempt.name} completed.",
                )
            )
            last_observation = attempt.result
            sequence += 1
            if attempt.failed:
                pending_failure = result_id
                trigger_reasons.add("tool_failure")
            else:
                pending_failure = None
                main_parent = result_id

    if recovered_failures == 0:
        return None

    final_answer = _last_assistant_text(messages)
    outcome = final_answer or "The session continued after correcting a failed or rejected attempt."
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
    reason = "+".join(sorted(trigger_reasons))
    return ReflectionCandidate(
        query=query,
        trigger_reason=reason,
        trajectory=ReflectionTrajectory(
            state=query,
            action="The agent revised its approach after a failed or rejected attempt.",
            observation=last_observation or "A prior attempt required correction.",
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


def _first_user_text(messages: list[Mapping[str, object]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            text = _strip_internal_context(_content_text(message.get("content")))
            if text:
                return text[:500]
    return ""


def _last_assistant_text(messages: list[Mapping[str, object]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        text = _text_blocks(message.get("content"))
        if text:
            return text[:1000]
    return ""


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
        return "Tool completed."
    compact = "\n".join(lines)
    if len(compact) <= 320:
        return compact
    return f"{compact[:317]}..."
