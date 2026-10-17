"""Where things live. One object, passed explicitly, so tests can relocate HOME.

Environment overrides (all optional):
  AGENTS_HOME        default ~/.agents
  CLAUDE_CONFIG_DIR  default ~/.claude   (Claude Code's own variable)
  CODEX_HOME         default ~/.codex    (Codex CLI's own variable)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Mapping, Optional

from installer.core.types import CONSUMERS, SCOPES

# repo-relative source directory per scope
REPO_SOURCE: Mapping[str, str] = {
    "shared": os.path.join("shared", "skills"),
    "claude": os.path.join("claude-code", "skills"),
    "codex": os.path.join("codex", "skills"),
}

BACKUP_DIRNAME = "backups"


def _expand(value: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(value)))


@dataclass(frozen=True)
class Paths:
    repo_dir: str
    agents_home: str
    claude_home: str
    codex_home: str

    # ------------------------------------------------------------------ build

    @classmethod
    def detect(cls, repo_dir: Optional[str] = None, env: Optional[Mapping[str, str]] = None,
               home: Optional[str] = None) -> "Paths":
        """Resolve from the environment. `repo_dir` defaults to the package's parent."""
        env = dict(os.environ if env is None else env)
        home = home or env.get("HOME") or os.path.expanduser("~")
        if repo_dir is None:
            here = os.path.dirname(os.path.abspath(__file__))
            repo_dir = os.path.abspath(os.path.join(here, os.pardir, os.pardir))
        return cls(
            repo_dir=_expand(repo_dir),
            agents_home=_expand(env.get("AGENTS_HOME") or os.path.join(home, ".agents")),
            claude_home=_expand(env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")),
            codex_home=_expand(env.get("CODEX_HOME") or os.path.join(home, ".codex")),
        )

    # ---------------------------------------------------------------- lookups

    def source_dir(self, scope: str) -> str:
        """Repo directory holding the installable skills for `scope`."""
        _check_scope(scope)
        return os.path.join(self.repo_dir, REPO_SOURCE[scope])

    def install_dir(self, scope: str) -> str:
        """Where skills of `scope` are installed on this machine."""
        _check_scope(scope)
        if scope == "shared":
            return os.path.join(self.agents_home, "skills")
        return self.consumer_dir(scope)

    def consumer_dir(self, consumer: str) -> str:
        """<tool home>/skills for claude or codex."""
        if consumer not in CONSUMERS:
            raise ValueError(f"unknown consumer: {consumer!r}")
        home = self.claude_home if consumer == "claude" else self.codex_home
        return os.path.join(home, "skills")

    def expected_link_target(self, consumer: str, name: str) -> str:
        """Relative symlink target install.sh creates, e.g. ../../.agents/skills/<name>."""
        rel = os.path.relpath(self.install_dir("shared"), self.consumer_dir(consumer))
        return os.path.join(rel, name)

    def backup_root(self, label: str, ts: Optional[float] = None) -> str:
        """~/.agents/backups/<label>-<YYYYmmdd-HHMMSS>. Created lazily by callers."""
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts if ts is not None else time.time()))
        return os.path.join(self.agents_home, BACKUP_DIRNAME, f"{label}-{stamp}")

    def repo_relative(self, path: str) -> str:
        return os.path.relpath(os.path.abspath(path), self.repo_dir)

    def display(self, path: str) -> str:
        """Shorten a path for display: replace $HOME prefix with ~."""
        home = os.path.expanduser("~")
        path = os.path.abspath(path)
        if path == home or path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path


def _check_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope: {scope!r}")
