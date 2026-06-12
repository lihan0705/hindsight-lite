"""Bank ID derivation and mission management for Codex.

Codex context dimensions:
  - agent   → configured name or "codex" (HINDSIGHT_AGENT_NAME)
  - project → derived from cwd (working directory basename)
  - session → session_id from hook input
  - user    → from env var HINDSIGHT_USER_ID

The channel dimension is omitted — Codex is a CLI tool without multi-channel
routing like Telegram/Discord agents.
"""

import os
import sys

DEFAULT_BANK_NAME = "codex"

# Valid granularity fields for Codex
VALID_FIELDS = {"agent", "project", "session", "user"}


def derive_bank_id(hook_input: dict, config: dict) -> str:
    """Derive a bank ID from hook context and config.

    When dynamicBankId is false, returns the static bank.
    When true, composes from granularity fields joined by '::'.
    """
    prefix = config.get("bankIdPrefix", "")

    if not config.get("dynamicBankId", False):
        base = config.get("bankId") or DEFAULT_BANK_NAME
        return f"{prefix}-{base}" if prefix else base

    # Dynamic mode — compose from granularity fields
    fields = config.get("dynamicBankGranularity")
    if not fields or not isinstance(fields, list):
        fields = ["agent", "project"]

    for f in fields:
        if f not in VALID_FIELDS:
            print(
                f'[Hindsight] Unknown dynamicBankGranularity field "{f}" — '
                f"valid for Codex: {', '.join(sorted(VALID_FIELDS))}",
                file=sys.stderr,
            )

    cwd = hook_input.get("cwd", "")
    session_id = hook_input.get("session_id", "")
    agent_name = config.get("agentName", "codex")
    user_id = os.environ.get("HINDSIGHT_USER_ID", "")

    field_map = {
        "agent": agent_name,
        "project": os.path.basename(cwd) if cwd else "unknown",
        "session": session_id or "unknown",
        "user": user_id or "anonymous",
    }

    # bank_id is stored as-is server-side; HTTP path encoding is the client layer's job.
    segments = [field_map.get(f, "unknown") for f in fields]
    base_bank_id = "::".join(segments)

    return f"{prefix}-{base_bank_id}" if prefix else base_bank_id
