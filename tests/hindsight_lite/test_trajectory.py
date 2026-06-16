from hindsight_lite.trajectory import extract_reflection_candidate


def test_extract_reflection_candidate_builds_failed_branch_and_correction() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": [{"type": "text", "text": "Fix the failing authentication test."}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "1 failed\nexit_code: 1"},
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "auth.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "3 passed, 0 failed"},
                    {"type": "text", "text": "Fixed the redirect condition and the tests now pass."},
                ],
            },
        ]
    )

    assert candidate is not None
    assert candidate.trigger_reason == "tool_failure"
    steps = candidate.trajectory.steps
    failed_observation = next(step for step in steps if step.status == "failed" and step.kind == "observation")
    corrected_action = next(step for step in steps if step.correction_of == failed_observation.id)
    assert corrected_action.tool_name == "apply_patch"
    assert corrected_action.parent_id == "state-0"
    assert steps[-1].kind == "outcome"
    assert steps[-1].status == "success"


def test_extract_reflection_candidate_uses_explicit_user_correction() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": [{"type": "text", "text": "Update the memory UI."}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Updated the page title."}]},
            {"role": "user", "content": [{"type": "text", "text": "不对，我说的是 reflection 的枝干图。"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "memory_ui.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                    {"type": "text", "text": "Updated the reflection branch graph."},
                ],
            },
        ]
    )

    assert candidate is not None
    assert candidate.trigger_reason == "user_correction"
    correction = next(step for step in candidate.trajectory.steps if step.id.startswith("user-correction"))
    corrected_action = next(step for step in candidate.trajectory.steps if step.correction_of == correction.id)
    assert corrected_action.tool_name == "apply_patch"


def test_extract_reflection_candidate_preserves_correction_order_after_tool_failure() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": "Update the memory UI."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "memory_ui.py"}},
                    {"type": "tool_result", "content": "status: failed"},
                ],
            },
            {"role": "user", "content": "不对，先修复 graph 切换。"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "memory_ui.py"}},
                    {"type": "tool_result", "content": "status: failed"},
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_memory_ui.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                ],
            },
        ]
    )

    assert candidate is not None
    failed_tools = [step for step in candidate.trajectory.steps if step.kind == "tool" and step.status == "failed"]
    correction = next(step for step in candidate.trajectory.steps if step.id.startswith("user-correction"))
    corrected_tool = next(
        step for step in candidate.trajectory.steps if step.status == "success" and step.kind == "tool"
    )
    assert len(failed_tools) == 2
    assert failed_tools[0].sequence < correction.sequence < failed_tools[1].sequence < corrected_tool.sequence
    assert failed_tools[1].correction_of == correction.id
    assert corrected_tool.correction_of is not None


def test_extract_reflection_candidate_skips_ordinary_successful_session() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": [{"type": "text", "text": "List the files."}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "shell", "input": {"command": ["ls"]}},
                    {"type": "tool_result", "content": "README.md\npyproject.toml"},
                ],
            },
        ]
    )

    assert candidate is None


def test_extract_reflection_candidate_skips_unrecovered_failure() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": [{"type": "text", "text": "Run the test."}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "1 failed\nexit_code: 1"},
                ],
            },
        ]
    )

    assert candidate is None


def test_extract_reflection_candidate_keeps_only_the_corrected_failure_window() -> None:
    candidate = extract_reflection_candidate(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": ("<environment_context>\n <cwd>/tmp/project</cwd>\n</environment_context>"),
                    }
                ],
            },
            {"role": "user", "content": [{"type": "text", "text": "Sync the repository."}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "exec_command", "input": {"cmd": "git status --short"}},
                    {"type": "tool_result", "content": "Chunk ID: ok\nProcess exited with code 0\nOutput:\nclean"},
                    {"type": "tool_use", "name": "exec_command", "input": {"cmd": "git fetch origin"}},
                    {
                        "type": "tool_result",
                        "content": (
                            "Chunk ID: failed\n"
                            "Wall time: 0.1 seconds\n"
                            "Process exited with code 128\n"
                            "Output:\n"
                            "fatal: unable to access remote"
                        ),
                    },
                    {"type": "tool_use", "name": "exec_command", "input": {"cmd": "git fetch origin --retry"}},
                    {
                        "type": "tool_result",
                        "content": "Chunk ID: fixed\nProcess exited with code 0\nOutput:\nFetched origin/main",
                    },
                    {"type": "text", "text": "The repository is synced."},
                ],
            },
        ]
    )

    assert candidate is not None
    assert candidate.query == "Sync the repository."
    assert len(candidate.trajectory.steps) == 6
    rendered_steps = "\n".join(step.content for step in candidate.trajectory.steps)
    assert "git status --short" not in rendered_steps
    assert "Chunk ID" not in rendered_steps
    assert "fatal: unable to access remote" in rendered_steps
    assert "Fetched origin/main" in rendered_steps


def test_extract_reflection_candidate_keeps_only_latest_completed_episode() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": "Fix authentication."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "1 failed\nexit_code: 1"},
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "auth.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                    {"type": "text", "text": "Authentication fixed."},
                ],
            },
            {"role": "user", "content": "Fix the memory tree."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_memory_ui.py"}},
                    {"type": "tool_result", "content": "2 failed\nexit_code: 1"},
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "memory_ui.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                    {"type": "text", "text": "Memory tree fixed."},
                ],
            },
        ]
    )

    assert candidate is not None
    assert candidate.query == "Fix the memory tree."
    rendered_steps = "\n".join(step.content for step in candidate.trajectory.steps)
    assert "test_memory_ui.py" in rendered_steps
    assert "test_auth.py" not in rendered_steps
    assert "Memory tree fixed." in rendered_steps


def test_extract_reflection_candidate_collapses_repeated_attempts() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": "Run the tests."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "first failure\nexit_code: 1"},
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "latest failure\nexit_code: 1"},
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "auth.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                ],
            },
        ]
    )

    assert candidate is not None
    pytest_steps = [step for step in candidate.trajectory.steps if step.tool_name == "pytest"]
    assert len(pytest_steps) == 1
    assert pytest_steps[0].repeat_count == 2
    rendered_steps = "\n".join(step.content for step in candidate.trajectory.steps)
    assert "latest failure" in rendered_steps
    assert "first failure" not in rendered_steps


def test_extract_reflection_candidate_omits_low_information_success_result() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": "Fix the test."},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "pytest", "input": {"target": "test_auth.py"}},
                    {"type": "tool_result", "content": "1 failed\nexit_code: 1"},
                    {"type": "tool_use", "name": "apply_patch", "input": {"file": "auth.py"}},
                    {"type": "tool_result", "content": "status: completed"},
                ],
            },
        ]
    )

    assert candidate is not None
    rendered_steps = "\n".join(step.content for step in candidate.trajectory.steps)
    assert "Tool completed." not in rendered_steps
    assert "status: completed" not in rendered_steps
    assert len(candidate.trajectory.steps) == 5


def test_extract_reflection_candidate_skips_environment_permission_noise() -> None:
    candidate = extract_reflection_candidate(
        [
            {"role": "user", "content": "$hindsight-lite:memorytree"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "exec_command",
                        "input": {
                            "cmd": ("mkdir -p /Users/gongping/.codex/plugins/cache/personal-local/hindsight-lite/0.3.0")
                        },
                    },
                    {
                        "type": "tool_result",
                        "content": (
                            "Process exited with code 1\n"
                            "mkdir: /Users/gongping/.codex/plugins/cache/personal-local/"
                            "hindsight-lite/0.3.0: Operation not permitted"
                        ),
                    },
                    {
                        "type": "tool_use",
                        "name": "exec_command",
                        "input": {
                            "cmd": ("mkdir -p /Users/gongping/.codex/plugins/cache/personal-local/hindsight-lite/0.3.0")
                        },
                    },
                    {"type": "tool_result", "content": "Process exited with code 0\nOutput:\ncreated"},
                    {"type": "text", "text": "The memory tree plugin cache was refreshed."},
                ],
            },
        ]
    )

    assert candidate is None
