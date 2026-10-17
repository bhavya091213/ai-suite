"""Shared fixtures for the settings-sync test modules (a helper, not a test module)."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Optional

from installer.core import config

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
EXAMPLE_TOML = os.path.join(REPO_ROOT, "codex", "config.example.toml")
SAMPLE_SETTINGS = {
    "_comment": "sample settings",
    "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787", "ENABLE_TOOL_SEARCH": "true"},
    "permissions": {"allow": ["Bash(git add:*)", "Read(//tmp/**)"]},
    "model": "opus",
    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]},
}


def dump(obj: Mapping[str, Any], indent: int = 2) -> str:
    return json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"


def make_config(values: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
    """Config.data with the documented defaults and `values` (dotted keys) applied."""
    cfg = config.Config(data=config.DEFAULTS, path="", exists=True)
    for key, value in (values or {}).items():
        cfg = config.with_value(cfg, key, value)
    return cfg.data


def read(path: str) -> str:
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


