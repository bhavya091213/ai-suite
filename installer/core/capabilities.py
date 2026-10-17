"""Capability probing: which CLIs and tools this machine has, their versions, Obsidian vaults.

Terminal-free - everything here returns data. Every subprocess call is an
argument list (never a shell) with ``capture_output=True``, ``text=True``,
``errors="replace"``, ``check=False`` and a 5 second timeout (``errors="replace"``
so a binary that prints undecodable bytes still counts as present). Nothing
escapes: a missing binary, a timeout or any other failure becomes
``present=False`` with the reason in ``Capability.detail``.

``probe`` accepts ``which``, ``run``, ``env``, ``home`` and ``platform`` so tests
can simulate any machine. ``env`` is a *replacement* environment (like
``Paths.detect``); ``None`` means ``os.environ``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

PROBE_TIMEOUT = 5.0
MAX_VERSION_CHARS = 200

PROBES: Tuple[str, ...] = (
    "claude", "codex", "gemini", "git", "gh", "node", "nvm", "docker", "python",
    "uv", "bun", "deno", "go", "cargo", "obsidian", "tmux", "headroom", "shellcheck",
)

# probe name -> (binaries tried in order, arguments that make it print its version)
_BINARY_SPECS: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = MappingProxyType({
    "claude": (("claude",), ("--version",)),
    "codex": (("codex",), ("--version",)),
    "gemini": (("gemini",), ("--version",)),
    "git": (("git",), ("--version",)),
    "gh": (("gh",), ("--version",)),
    "node": (("node",), ("-v",)),
    "docker": (("docker",), ("--version",)),
    "python": (("python3", "python"), ("--version",)),
    "uv": (("uv",), ("--version",)),
    "bun": (("bun",), ("--version",)),
    "deno": (("deno",), ("--version",)),
    "go": (("go",), ("version",)),
    "cargo": (("cargo",), ("--version",)),
    "tmux": (("tmux",), ("-V",)),
    "shellcheck": (("shellcheck",), ("--version",)),
})

# Where the Obsidian desktop app lives on macOS (module level so tests can redirect it).
DARWIN_APP_DIRS: Tuple[str, ...] = ("/Applications",)
OBSIDIAN_APP = "Obsidian.app"

Which = Callable[[str], Optional[str]]
Runner = Callable[..., Any]


# ------------------------------------------------------------------ value types


@dataclass(frozen=True)
class Capability:
    name: str
    present: bool
    version: Optional[str]
    path: Optional[str]
    detail: str


@dataclass(frozen=True)
class Capabilities:
    items: Mapping[str, Capability]
    vaults: Tuple[str, ...] = ()
    nvm_versions: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", MappingProxyType(dict(self.items)))
        object.__setattr__(self, "vaults", tuple(self.vaults))
        object.__setattr__(self, "nvm_versions", tuple(self.nvm_versions))

    def get(self, name: str) -> Capability:
        """The probe result for `name`; an absent Capability when it was not probed."""
        found = self.items.get(name)
        return found if found is not None else Capability(name, False, None, None, "not probed")

    def present(self, name: str) -> bool:
        return self.get(name).present


@dataclass(frozen=True)
class _Ctx:
    which: Which
    run: Runner
    env: Mapping[str, str]  # effective environment for HOME / XDG / NVM_DIR lookups
    run_env: Optional[Dict[str, str]]  # handed to subprocess only when the caller supplied one
    home: str
    platform: str


@dataclass(frozen=True)
class _Ran:
    started: bool  # False when the command could not be executed at all
    version: Optional[str] = None
    note: str = ""  # why it failed to start, or what looked off when it did


# ---------------------------------------------------------------------- plumbing


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else ""


def _first_line(value: Any) -> Optional[str]:
    for line in _text(value).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:MAX_VERSION_CHARS]
    return None


def _exec(ctx: _Ctx, cmd: Sequence[str]) -> _Ran:
    """Run `cmd` and report what happened. Never raises."""
    label = " ".join([os.path.basename(cmd[0]), *cmd[1:]])
    kwargs: Dict[str, Any] = {
        "capture_output": True, "text": True, "errors": "replace",
        "timeout": PROBE_TIMEOUT, "check": False,
    }
    if ctx.run_env is not None:
        kwargs["env"] = ctx.run_env
    try:
        proc = ctx.run(list(cmd), **kwargs)
    except FileNotFoundError:
        return _Ran(False, note=f"`{label}`: executable not found")
    except subprocess.TimeoutExpired:
        return _Ran(False, note=f"`{label}` timed out after {PROBE_TIMEOUT:g}s")
    except OSError as exc:
        return _Ran(False, note=f"`{label}` could not run: {exc}")
    except Exception as exc:  # noqa: BLE001 - contract: nothing escapes this module
        return _Ran(False, note=f"`{label}` failed: {exc}")
    code = getattr(proc, "returncode", 0)
    if code not in (0, None):
        return _Ran(True, note=f"`{label}` exited with status {code}")
    line = _first_line(getattr(proc, "stdout", None)) or _first_line(getattr(proc, "stderr", None))
    return _Ran(True, version=line)


def _bind_which(which: Which, env: Optional[Mapping[str, str]]) -> Which:
    """The default `shutil.which` searches the *supplied* env's PATH, not the process one."""
    if env is not None and which is shutil.which:
        search_path = env.get("PATH", "")
        return lambda name: shutil.which(name, path=search_path)
    return which


def _absent(name: str, detail: str) -> Capability:
    return Capability(name, False, None, None, detail)


# ------------------------------------------------------------------ binary probes


def _probe_binary(ctx: _Ctx, name: str, binaries: Sequence[str], args: Sequence[str]) -> Capability:
    for binary in binaries:
        path = ctx.which(binary)
        if not path:
            continue
        ran = _exec(ctx, [binary, *args])
        if not ran.started:
            return Capability(name, False, None, path, ran.note)
        return Capability(name, True, ran.version, path, ran.note)
    return _absent(name, "not found on PATH")


def _probe_docker(ctx: _Ctx) -> Capability:
    cap = _probe_binary(ctx, "docker", ("docker",), ("--version",))
    if not cap.present:
        return cap
    info = _exec(ctx, ["docker", "info"])
    if info.started and not info.note:
        return replace(cap, detail="daemon running")
    reason = f" ({info.note})" if not info.started else ""
    return replace(cap, detail="installed, daemon not running" + reason)


def _probe_headroom(ctx: _Ctx) -> Capability:
    on_path = ctx.which("headroom")
    local = os.path.join(ctx.home, ".local", "bin", "headroom")
    if on_path:
        target, where, detail = "headroom", on_path, "on PATH"
    elif os.path.isfile(local):
        target, where, detail = local, local, "found at ~/.local/bin/headroom (not on PATH)"
    else:
        return _absent("headroom", "not on PATH and ~/.local/bin/headroom does not exist")
    ran = _exec(ctx, [target, "--version"])
    if not ran.started:
        return Capability("headroom", False, None, where, ran.note)
    return Capability("headroom", True, ran.version, where, "; ".join(p for p in (detail, ran.note) if p))


# -------------------------------------------------------------------------- nvm


def _nvm_root(ctx: _Ctx) -> Optional[str]:
    candidates = []
    if ctx.env.get("NVM_DIR"):
        candidates.append(os.path.join(ctx.env["NVM_DIR"], "versions", "node"))
    candidates.append(os.path.join(ctx.home, ".nvm", "versions", "node"))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return None


def _version_key(name: str) -> Tuple[int, int, int, int, str]:
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", name)
    if not match:
        return (0, 0, 0, 0, name)
    return (1, int(match.group(1)), int(match.group(2)), int(match.group(3)), name)


def _nvm_versions(ctx: _Ctx) -> Tuple[str, ...]:
    root = _nvm_root(ctx)
    if root is None:
        return ()
    try:
        names = os.listdir(root)
    except OSError:
        return ()
    dirs = [n for n in names if not n.startswith(".") and os.path.isdir(os.path.join(root, n))]
    return tuple(sorted(dirs, key=_version_key, reverse=True))


def _probe_nvm(ctx: _Ctx) -> Capability:
    root = _nvm_root(ctx)
    if root is None:
        return _absent("nvm", "~/.nvm/versions/node not found")
    versions = _nvm_versions(ctx)
    count = len(versions)
    detail = f"{count} node version{'' if count == 1 else 's'} installed"
    return Capability("nvm", True, versions[0] if versions else None, root, detail)


# ---------------------------------------------------------------------- obsidian


def obsidian_registry_path(home: str, platform: str = sys.platform,
                           env: Optional[Mapping[str, str]] = None) -> str:
    """Where Obsidian keeps its vault registry (obsidian.json) on `platform`."""
    env = os.environ if env is None else env
    if platform.startswith("darwin"):
        return os.path.join(home, "Library", "Application Support", "obsidian", "obsidian.json")
    if platform.startswith("win") or platform == "cygwin":
        base = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(base, "obsidian", "obsidian.json")
    base = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(base, "obsidian", "obsidian.json")


def _read_json(path: str) -> Any:
    """Parsed JSON, or None for anything unreadable (missing, binary, malformed, absurdly nested)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - OSError, ValueError, RecursionError, MemoryError, ...
        return None


def obsidian_vaults(home: str, platform: str = sys.platform,
                    env: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """Vault directories from the registry that exist: the open ones first, then registry order."""
    data = _read_json(obsidian_registry_path(home, platform, env))
    vaults = data.get("vaults") if isinstance(data, dict) else None
    if not isinstance(vaults, dict):
        return ()
    opened, others, seen = [], [], set()
    for entry in vaults.values():
        path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not path or path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        (opened if entry.get("open") is True else others).append(path)
    return tuple(opened + others)


def _obsidian_app(ctx: _Ctx) -> Optional[str]:
    if not ctx.platform.startswith("darwin"):
        return None
    for base in (*DARWIN_APP_DIRS, os.path.join(ctx.home, "Applications")):
        candidate = os.path.join(base, OBSIDIAN_APP)
        if os.path.isdir(candidate):
            return candidate
    return None


def _probe_obsidian(ctx: _Ctx) -> Capability:
    # The CLI talks to (and may launch) the desktop app, so it is never executed here.
    cli = ctx.which("obsidian")
    app = _obsidian_app(ctx)
    registry = obsidian_registry_path(ctx.home, ctx.platform, ctx.env)
    has_registry = os.path.isfile(registry)
    found = [label for label, ok in (("CLI on PATH", cli), ("app installed", app),
                                     ("vault registry found", has_registry)) if ok]
    if not found:
        return _absent("obsidian", "no CLI, app or vault registry found")
    return Capability("obsidian", True, None, cli or app or registry, ", ".join(found))


# ------------------------------------------------------------------------- probe


def _probe_one(name: str, ctx: _Ctx) -> Capability:
    custom = {"nvm": _probe_nvm, "docker": _probe_docker,
              "headroom": _probe_headroom, "obsidian": _probe_obsidian}
    try:
        if name in custom:
            return custom[name](ctx)
        binaries, args = _BINARY_SPECS[name]
        return _probe_binary(ctx, name, binaries, args)
    except Exception as exc:  # noqa: BLE001 - contract: a failing probe is data
        return _absent(name, f"probe failed: {exc}")


def _collect(step: Callable[[], Iterable[str]]) -> Tuple[str, ...]:
    """Run a side-collection step (vaults, nvm versions); any failure yields no entries."""
    try:
        return tuple(step())
    except Exception:  # noqa: BLE001 - contract: no exception escapes probe()
        return ()


def probe(env: Optional[Mapping[str, str]] = None, which: Which = shutil.which,
          run: Runner = subprocess.run, home: Optional[str] = None,
          platform: str = sys.platform, only: Optional[Iterable[str]] = None) -> Capabilities:
    """Probe the machine. `only` restricts the run to the named probes (unknown names are ignored)."""
    effective = dict(os.environ if env is None else env)
    ctx = _Ctx(
        which=_bind_which(which, env),
        run=run,
        env=MappingProxyType(effective),
        run_env=None if env is None else dict(env),
        home=home or effective.get("HOME") or os.path.expanduser("~"),
        platform=platform,
    )
    if isinstance(only, str):
        only = (only,)
    selected = PROBES if only is None else tuple(n for n in PROBES if n in set(only))
    items = {name: _probe_one(name, ctx) for name in selected}
    vaults: Tuple[str, ...] = ()
    nvm_versions: Tuple[str, ...] = ()
    if "obsidian" in items:
        vaults = _collect(lambda: obsidian_vaults(ctx.home, ctx.platform, ctx.env))
    if "nvm" in items:
        nvm_versions = _collect(lambda: _nvm_versions(ctx))
    return Capabilities(items=items, vaults=vaults, nvm_versions=nvm_versions)


# ---------------------------------------------------------------------- consumers


def resolve_tool(setting: str, cap: Capability) -> bool:
    """Apply a `tools.*` config value: auto -> detected, on -> True, off -> False.

    Anything unrecognised behaves like ``auto`` (config validation reports it).
    """
    value = str(setting).strip().lower()
    if value == "on":
        return True
    if value == "off":
        return False
    return cap.present


def to_context(caps: Capabilities) -> Mapping[str, Any]:
    """Template context: ``{"claude": {"present": ..., "version": ..., "path": ...}, ...}``."""
    return {
        name: {"present": cap.present, "version": cap.version, "path": cap.path}
        for name, cap in caps.items.items()
    }
