"""Extras catalog: external integrations the installer knows about but does not ship.

``shared/extras.json`` lists tools that are not skills (a plugin, an MCP server, a
third-party installer). This module loads and validates that catalog, detects
whether each extra is already set up for Claude Code and/or Codex, and picks the
install commands for a tool. It never runs an install command - that needs an
explicit confirmation owned by the CLI/TUI layer.

Terminal-free. Detection runs at most one subprocess (``claude mcp list``, argument
list, 5 second timeout, undecodable output replaced) and nothing escapes: any failure
becomes "unknown" (None).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from installer.core.paths import Paths

EXTRAS_RELPATH = os.path.join("shared", "extras.json")
RUN_TIMEOUT = 5.0
TOOLS: Tuple[str, ...] = ("claude", "codex")
DEFAULT_CATEGORY = "other"

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_EMPTY: Mapping[str, Any] = MappingProxyType({})
_HOME_DOTDIRS = ((".claude", "claude_home"), (".codex", "codex_home"), (".agents", "agents_home"))

Runner = Callable[..., Any]
Which = Callable[[str], Optional[str]]


@dataclass(frozen=True)
class Extra:
    key: str
    title: str
    category: str
    url: str
    tools: Tuple[str, ...]
    install: Tuple[str, ...] = ()
    install_by_tool: Mapping[str, Tuple[str, ...]] = field(default_factory=lambda: _EMPTY)
    after_install: Mapping[str, str] = field(default_factory=lambda: _EMPTY)
    detect: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)


@dataclass(frozen=True)
class ExtraStatus:
    extra: Extra
    installed: Mapping[str, Optional[bool]]  # per tool: True / False / None (unknown or n/a)


# ----------------------------------------------------------------------- loading


class _Invalid(ValueError):
    """One catalog entry does not match the schema."""


def _string(raw: Any, name: str, default: Optional[str] = None) -> str:
    if default is not None and raw in (None, ""):
        return default
    if not isinstance(raw, str) or not raw.strip():
        raise _Invalid(f"{name} must be a non-empty string")
    return raw.strip()


def _strings(raw: Any, name: str) -> Tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(c, str) and c.strip() for c in raw):
        raise _Invalid(f"{name} must be a list of non-empty strings")
    return tuple(c.strip() for c in raw)


def _tools(raw: Any) -> Tuple[str, ...]:
    if raw is None:
        return TOOLS
    if not isinstance(raw, list) or not raw or not all(t in TOOLS for t in raw):
        raise _Invalid(f"tools must be a non-empty list drawn from {list(TOOLS)}")
    return tuple(dict.fromkeys(raw))


def _per_tool(raw: Any, name: str, convert: Callable[[Any, str], Any]) -> Mapping[str, Any]:
    if raw is None:
        return _EMPTY
    if not isinstance(raw, dict) or not all(k in TOOLS for k in raw):
        raise _Invalid(f"{name} must be an object keyed by {list(TOOLS)}")
    return MappingProxyType({tool: convert(value, f"{name}.{tool}") for tool, value in raw.items()})


def _detect(raw: Any) -> Mapping[str, Any]:
    if raw is None:
        return _EMPTY
    if not isinstance(raw, dict):
        raise _Invalid("detect must be an object")
    out: Dict[str, Any] = {}
    if "any_paths" in raw:
        out["any_paths"] = _strings(raw["any_paths"], "detect.any_paths")
    for method in ("claude_mcp", "codex_mcp", "claude_plugin"):
        if method in raw:
            out[method] = _string(raw[method], f"detect.{method}")
    return MappingProxyType(out)


def _parse_extra(key: str, raw: Any) -> Extra:
    if not _KEY_RE.match(key):
        raise _Invalid("key may only contain letters, digits, '.', '_' and '-'")
    if not isinstance(raw, dict):
        raise _Invalid("entry must be an object")
    return Extra(
        key=key,
        title=_string(raw.get("title"), "title"),
        category=_string(raw.get("category"), "category", DEFAULT_CATEGORY),
        url=_string(raw.get("url"), "url", ""),
        tools=_tools(raw.get("tools")),
        install=_strings(raw.get("install"), "install"),
        install_by_tool=_per_tool(raw.get("install_by_tool"), "install_by_tool", _strings),
        after_install=_per_tool(raw.get("after_install"), "after_install", _string),
        detect=_detect(raw.get("detect")),
    )


def load_checked(paths: Paths) -> Tuple[Tuple[Extra, ...], Tuple[str, ...]]:
    """Load the catalog plus human-readable problems. A missing file is not a problem."""
    rel = EXTRAS_RELPATH.replace(os.sep, "/")
    try:
        with open(os.path.join(paths.repo_dir, EXTRAS_RELPATH), encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return (), ()
    except (OSError, ValueError, RecursionError) as exc:  # RecursionError: absurdly nested JSON
        return (), (f"{rel}: cannot read ({exc})",)
    entries = data.get("extras") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return (), (f"{rel}: expected an object with an \"extras\" object",)
    extras, problems = [], []
    for key, raw in entries.items():
        try:
            extras.append(_parse_extra(str(key), raw))
        except _Invalid as exc:
            problems.append(f"{rel}: extra {key!r} skipped: {exc}")
    return tuple(extras), tuple(problems)


def load(paths: Paths) -> Tuple[Extra, ...]:
    """The validated catalog from ``<repo>/shared/extras.json``; ``()`` when absent or unusable."""
    return load_checked(paths)[0]


# --------------------------------------------------------------------- detection


@dataclass(frozen=True)
class _Ctx:
    paths: Paths
    env: Mapping[str, str]
    run_env: Optional[Dict[str, str]]
    run: Runner
    which: Which


def _expand(raw: str, ctx: _Ctx) -> str:
    """Expand `~`; ``~/.claude`` / ``~/.codex`` / ``~/.agents`` follow the relocated Paths homes."""
    if raw.startswith("~/"):
        rel = raw[2:]
        for dotdir, attr in _HOME_DOTDIRS:
            if rel == dotdir or rel.startswith(dotdir + "/"):
                tail = rel[len(dotdir):].lstrip("/")
                return os.path.normpath(os.path.join(getattr(ctx.paths, attr), tail))
    if raw == "~" or raw.startswith("~/"):
        home = ctx.env.get("HOME") or os.path.expanduser("~")
        return os.path.normpath(home + raw[1:])
    return os.path.expanduser(raw)


def _within(path: str, root: str) -> bool:
    root = os.path.abspath(root)
    path = os.path.abspath(path)
    return path == root or path.startswith(root + os.sep)


def _owner(path: str, paths: Paths) -> Optional[str]:
    if _within(path, paths.claude_home):
        return "claude"
    if _within(path, paths.codex_home):
        return "codex"
    return None


def _paths_for(tool: str, ctx: _Ctx, raw_paths: Tuple[str, ...]) -> Tuple[str, ...]:
    """Paths that speak for `tool`: those under its home, plus ones under neither tool's home."""
    resolved = (_expand(raw, ctx) for raw in raw_paths)
    return tuple(p for p in resolved if _owner(p, ctx.paths) in (tool, None))


def _read_text(path: str) -> Optional[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _claude_mcp(name: str, ctx: _Ctx) -> Optional[bool]:
    if not ctx.which("claude"):
        return None
    kwargs: Dict[str, Any] = {
        "capture_output": True, "text": True, "errors": "replace",
        "timeout": RUN_TIMEOUT, "check": False,
    }
    if ctx.run_env is not None:
        kwargs["env"] = ctx.run_env
    proc = ctx.run(["claude", "mcp", "list"], **kwargs)
    if getattr(proc, "returncode", 0) not in (0, None):
        return None
    out = "\n".join(str(getattr(proc, s, "") or "") for s in ("stdout", "stderr"))
    pattern = re.compile(r"^\s*" + re.escape(name) + r"(?=$|[\s:])", re.MULTILINE)
    return pattern.search(out) is not None


def _codex_mcp(name: str, ctx: _Ctx) -> Optional[bool]:
    try:
        text = _read_text(os.path.join(ctx.paths.codex_home, "config.toml"))
    except FileNotFoundError:
        return False
    escaped = re.escape(name)
    header = r"^[ \t]*\[[ \t]*mcp_servers[ \t]*\.[ \t]*(?:\"%s\"|'%s'|%s)[ \t]*[\].]" % (
        escaped, escaped, escaped)
    return re.search(header, text or "", re.MULTILINE) is not None


def _claude_plugin(key: str, ctx: _Ctx) -> Optional[bool]:
    try:
        data = json.loads(_read_text(os.path.join(ctx.paths.claude_home, "settings.json")) or "")
    except FileNotFoundError:
        return False
    enabled = data.get("enabledPlugins") if isinstance(data, dict) else None
    # Contract: the key being listed under enabledPlugins is what counts. A plugin that is
    # installed but switched off (value false) is still installed, so no install is offered.
    return isinstance(enabled, dict) and key in enabled


def _guarded(check: Callable[[str, _Ctx], Optional[bool]], arg: str, ctx: _Ctx) -> Optional[bool]:
    """Run one detection method; any failure (timeout, bad file, ...) means "unknown"."""
    try:
        return check(arg, ctx)
    except Exception:  # noqa: BLE001 - contract: nothing escapes this module
        return None


def _combine(results: Tuple[Optional[bool], ...]) -> Optional[bool]:
    if not results:
        return None  # no detection method applies to this tool
    if any(r is True for r in results):
        return True
    if any(r is None for r in results):
        return None  # something we could not check might still say yes
    return False


def _detect_tool(extra: Extra, tool: str, ctx: _Ctx) -> Optional[bool]:
    spec = extra.detect
    results = []
    own = _paths_for(tool, ctx, tuple(spec.get("any_paths", ())))
    if own:
        results.append(any(os.path.exists(p) for p in own))
    if tool == "claude":
        for method, check in (("claude_mcp", _claude_mcp), ("claude_plugin", _claude_plugin)):
            if method in spec:
                results.append(_guarded(check, spec[method], ctx))
    if tool == "codex" and "codex_mcp" in spec:
        results.append(_guarded(_codex_mcp, spec["codex_mcp"], ctx))
    return _combine(tuple(results))


def detect(extra: Extra, paths: Paths, env: Optional[Mapping[str, str]] = None,
           run: Runner = subprocess.run, which: Which = shutil.which) -> ExtraStatus:
    """Is `extra` set up, per tool? True/False, or None when it cannot be told or n/a."""
    ctx = _Ctx(
        paths=paths,
        env=dict(os.environ if env is None else env),
        run_env=None if env is None else dict(env),
        run=run,
        which=which,
    )
    installed = {tool: _detect_tool(extra, tool, ctx) for tool in extra.tools}
    return ExtraStatus(extra=extra, installed=MappingProxyType(installed))


def commands_for(extra: Extra, tool: str) -> Tuple[str, ...]:
    """Install commands for `tool`: its own list, else the shared one; ``()`` if it is unsupported."""
    if tool not in extra.tools:
        return ()
    return tuple(extra.install_by_tool.get(tool) or extra.install)
