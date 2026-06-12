"""Configuration management for Hindsight Codex plugin.

Loads settings from settings.json (plugin defaults) merged with environment
variable overrides. Full config schema matching Openclaw's 30+ options.
"""

import json
import os
import sys

DEFAULTS = {
    # Recall
    "autoRecall": True,
    "recallMaxResults": 5,
    "recallMaxExcerptChars": 160,
    "recallContextTurns": 1,
    "recallMaxQueryChars": 800,
    "recallRoles": ["user", "assistant"],
    "recallPromptPreamble": (
        "Relevant memories from past conversations (prioritize recent when "
        "conflicting). Only use memories that are directly useful to continue "
        "this conversation; ignore the rest:"
    ),
    # File context
    "autoFileContext": True,
    "fileContextMaxResults": 3,
    "fileContextMaxExcerptChars": 140,
    "fileContextPromptPreamble": (
        "Relevant hindsight-lite memory for the file about to be read. Use only if it changes the next action:"
    ),
    # Retain
    "autoRetain": True,
    "retainMode": "full-session",
    "retainRoles": ["user", "assistant"],
    "retainEveryNTurns": 1,
    "retainOverlapTurns": 2,
    "retainContext": "codex",
    "retainTags": [],
    "retainMetadata": {},
    "autoMemoryUi": True,
    # Bank
    "bankId": None,
    "bankIdPrefix": "",
    "dynamicBankId": False,
    "dynamicBankGranularity": ["agent", "project"],
    "agentName": "codex",
    # Misc
    "debug": False,
}

# Map env var names to config keys and their types
ENV_OVERRIDES = {
    "HINDSIGHT_BANK_ID": ("bankId", str),
    "HINDSIGHT_AGENT_NAME": ("agentName", str),
    "HINDSIGHT_AUTO_RECALL": ("autoRecall", bool),
    "HINDSIGHT_AUTO_RETAIN": ("autoRetain", bool),
    "HINDSIGHT_AUTO_MEMORY_UI": ("autoMemoryUi", bool),
    "HINDSIGHT_RETAIN_MODE": ("retainMode", str),
    "HINDSIGHT_RECALL_MAX_RESULTS": ("recallMaxResults", int),
    "HINDSIGHT_RECALL_MAX_EXCERPT_CHARS": ("recallMaxExcerptChars", int),
    "HINDSIGHT_RECALL_MAX_QUERY_CHARS": ("recallMaxQueryChars", int),
    "HINDSIGHT_RECALL_CONTEXT_TURNS": ("recallContextTurns", int),
    "HINDSIGHT_AUTO_FILE_CONTEXT": ("autoFileContext", bool),
    "HINDSIGHT_FILE_CONTEXT_MAX_RESULTS": ("fileContextMaxResults", int),
    "HINDSIGHT_FILE_CONTEXT_MAX_EXCERPT_CHARS": ("fileContextMaxExcerptChars", int),
    "HINDSIGHT_DYNAMIC_BANK_ID": ("dynamicBankId", bool),
    "HINDSIGHT_DEBUG": ("debug", bool),
}


def _cast_env(value: str, typ):
    """Cast environment variable string to target type. Returns None on failure."""
    try:
        if typ is bool:
            return value.lower() in ("true", "1", "yes")
        if typ is int:
            return int(value)
        return value
    except (ValueError, AttributeError):
        return None


def _load_settings_file(path: str, config: dict) -> None:
    """Merge a settings.json file into config in-place. Silently skips if missing."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            file_config = json.load(f)
        config.update({k: v for k, v in file_config.items() if v is not None})
    except (json.JSONDecodeError, OSError) as e:
        debug_log(config, f"Failed to load {path}: {e}")


def load_config() -> dict:
    """Load plugin configuration from settings.json + env overrides.

    Loading order (later entries win):
      1. Built-in defaults
      2. Plugin install settings.json  (~/.hindsight/codex/settings.json)
      3. User config                   (~/.hindsight/codex.json)
      4. Environment variable overrides

    ~/.hindsight/codex.json is the recommended place to configure the
    plugin — stable across updates.
    """
    config = dict(DEFAULTS)

    # 1. Plugin install settings.json (written by get-codex installer)
    install_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _load_settings_file(os.path.join(install_root, "settings.json"), config)

    # 2. User config — stable, version-independent
    user_config_path = os.path.join(os.path.expanduser("~"), ".hindsight", "codex.json")
    _load_settings_file(user_config_path, config)

    # Apply environment variable overrides
    for env_name, (key, typ) in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if val is not None:
            cast_val = _cast_env(val, typ)
            if cast_val is not None:
                config[key] = cast_val

    return config


def debug_log(config: dict, *args):
    """Log to stderr if debug mode is enabled."""
    if config.get("debug"):
        print("[Hindsight]", *args, file=sys.stderr)
