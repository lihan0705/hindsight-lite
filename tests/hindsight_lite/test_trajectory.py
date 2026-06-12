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
