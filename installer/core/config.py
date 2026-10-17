"""Central installer configuration: ~/.agents/config.json.

`DEFAULTS` is the full structure; the file may omit any key (defaults fill in)
and unknown keys survive a load/save round trip. `SETTINGS` is the typed schema
the CLI and the Settings screen drive. Everything handed out is immutable:
nested dicts are `MappingProxyType`, lists are tuples, and `with_value` returns
a new `Config` instead of changing the old one.

Core is terminal-free: nothing here prints or reads stdin. Nothing here deletes
either: `save` copies the previous file under `Paths.backup_root("config")`
before replacing it, and a half-written temp file is moved aside, not removed.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from installer.core.paths import Paths

CONFIG_FILENAME = "config.json"
LIST_KINDS: Tuple[str, ...] = ("pathlist", "strlist")
SECTIONS: Tuple[str, ...] = ("Tools", "Subagents", "Review", "Guardrails", "Paths", "Editor")


def _freeze(value: Any) -> Any:
    """Deep-freeze parsed JSON: dicts -> read-only mappings, lists -> tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    """Inverse of `_freeze`, for JSON output."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


DEFAULTS: Mapping[str, Any] = _freeze(
    {
        "version": 1,
        "tools": {"claude": "auto", "codex": "auto"},
        "subagents": {
            "claude": {"heavy": "opus", "light": "sonnet", "trivial": "haiku"},
            "codex": {
                "model": "gpt-5.6-sol",
                "heavy": "xhigh",
                "light": "medium",
                "trivial": "low",
                "max_threads": 6,
                "max_depth": 1,
            },
        },
        "review": {"adversarial": "auto"},
        "guardrails": {
            "never_delete": True,
            "context_budget_tokens": 100000,
            "preflight_checklist": True,
            "plan_approval_gate": True,
            "fix_approval_gate": True,
            "hook_profile": "standard",
            "disabled_hooks": [],
        },
        "paths": {
            "obsidian_vaults": [],
            "sessions_dir": "~/.claude/sessions",
            "backups_dir": "~/.agents/backups",
        },
        "editor": "",
    }
)


@dataclass(frozen=True)
class Setting:
    """One editable leaf key. `kind`: bool | int | str | enum | pathlist | strlist | path."""

    key: str
    kind: str
    label: str
    help: str
    section: str
    choices: Tuple[str, ...] = ()


_TOOL_MODES = ("auto", "on", "off")
_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_TOOL_HELP = "auto = use it when the CLI is detected; on / off forces it."
_SECTION_OF_ROOT = {"tools": "Tools", "subagents": "Subagents", "review": "Review",
                    "guardrails": "Guardrails", "paths": "Paths", "editor": "Editor"}


def _s(key: str, kind: str, label: str, help_text: str, *choices: str) -> Setting:
    """Build a Setting; the section follows from the key's first segment."""
    return Setting(key, kind, label, help_text, _SECTION_OF_ROOT[key.split(".")[0]], tuple(choices))


SETTINGS: Tuple[Setting, ...] = (
    _s("tools.claude", "enum", "Claude Code", "Claude Code files. " + _TOOL_HELP, *_TOOL_MODES),
    _s("tools.codex", "enum", "Codex CLI", "Codex CLI files. " + _TOOL_HELP, *_TOOL_MODES),
    _s("subagents.claude.heavy", "str", "Claude heavy model", "Model id or alias for planning, debugging, reviews."),
    _s("subagents.claude.light", "str", "Claude light model", "Model id or alias for small, well-specified tasks."),
    _s("subagents.claude.trivial", "str", "Claude trivial model", "Model id or alias for trivial, frequent tasks."),
    _s("subagents.codex.model", "str", "Codex model", "The one model Codex subagents run on."),
    _s("subagents.codex.heavy", "enum", "Codex heavy effort", "model_reasoning_effort, heavy tier.", *_EFFORTS),
    _s("subagents.codex.light", "enum", "Codex light effort", "model_reasoning_effort, light tier.", *_EFFORTS),
    _s("subagents.codex.trivial", "enum", "Codex trivial effort", "model_reasoning_effort, trivial tier.", *_EFFORTS),
    _s("subagents.codex.max_threads", "int", "Codex max threads", "Parallel Codex subagents (at least 1)."),
    _s("subagents.codex.max_depth", "int", "Codex max depth", "How deep subagents may spawn subagents."),
    _s("review.adversarial", "enum", "Adversarial reviewer", "auto = Codex when Codex is on, else Claude.",
       "auto", "codex", "claude"),
    _s("guardrails.never_delete", "bool", "Never delete", "Hard rule: relocate with mv, never rm."),
    _s("guardrails.context_budget_tokens", "int", "Context budget (tokens)",
       "Cap on a subagent's context before it must stop and ask."),
    _s("guardrails.preflight_checklist", "bool", "Pre-flight checklist",
       "Report machine state (Docker, Node, env files, deps) before coding."),
    _s("guardrails.plan_approval_gate", "bool", "Plan approval gate", "Pause for plan approval before implementing."),
    _s("guardrails.fix_approval_gate", "bool", "Fix approval gate", "Pause for approval of each review fix."),
    _s("guardrails.hook_profile", "enum", "Hook profile", "How many ECC hooks run (ECC_HOOK_PROFILE).",
       "minimal", "standard", "strict"),
    _s("guardrails.disabled_hooks", "strlist", "Disabled hooks",
       "ECC hook ids to switch off, e.g. pre:bash:tmux-reminder."),
    _s("paths.obsidian_vaults", "pathlist", "Obsidian vaults", "Vault directories; the first is the default vault."),
    _s("paths.sessions_dir", "path", "Sessions directory", "Where saved session files live."),
    _s("paths.backups_dir", "path", "Backups directory", "Where retired and replaced files are moved."),
    _s("editor", "str", "Editor command", "Empty = $VISUAL, then $EDITOR, then nano, vim or vi."),
)

_BY_KEY: Mapping[str, Setting] = MappingProxyType({s.key: s for s in SETTINGS})

# int settings default to "zero or more"; these need more.
_INT_MINIMUM: Mapping[str, int] = MappingProxyType(
    {"subagents.codex.max_threads": 1, "guardrails.context_budget_tokens": 1})
# str settings that may be empty; every other str / path must carry a value.
_MAY_BE_EMPTY = frozenset({"editor"})


def setting_for(key: str) -> Setting:
    """The schema entry for a dotted leaf key. KeyError when unknown."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(key) from None


def _type_name(value: Any) -> str:
    return type(value).__name__


def _check_bool(setting: Setting, value: Any) -> Optional[str]:
    return None if isinstance(value, bool) else f"expected true or false, got {_type_name(value)}"


def _check_int(setting: Setting, value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, int):
        return f"expected a whole number, got {_type_name(value)}"
    minimum = _INT_MINIMUM.get(setting.key, 0)
    return None if value >= minimum else f"must be at least {minimum}, got {value}"


def _check_str(setting: Setting, value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return f"expected text, got {_type_name(value)}"
    if not value.strip() and setting.key not in _MAY_BE_EMPTY:
        return "must not be empty"
    return None


def _check_enum(setting: Setting, value: Any) -> Optional[str]:
    if isinstance(value, str) and value in setting.choices:
        return None
    return f"{value!r} is not one of: {', '.join(setting.choices)}"


def _check_list(setting: Setting, value: Any) -> Optional[str]:
    if not isinstance(value, (list, tuple)):
        return f"expected a list, got {_type_name(value)}"
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return f"list entries must be non-empty text, got {item!r}"
    return None


_CHECKS: Mapping[str, Callable[[Setting, Any], Optional[str]]] = MappingProxyType({
    "bool": _check_bool, "int": _check_int, "str": _check_str, "path": _check_str,
    "enum": _check_enum, "pathlist": _check_list, "strlist": _check_list,
})


def _problem(setting: Setting, value: Any) -> Optional[str]:
    """Why `value` is not acceptable for `setting`, or None when it is."""
    check = _CHECKS.get(setting.kind)
    if check is None:
        return f"unknown setting kind {setting.kind!r}"
    return check(setting, value)


def _validated(setting: Setting, value: Any) -> Any:
    """Normalise (lists -> tuples) and check `value`; ValueError when unacceptable."""
    if setting.kind in LIST_KINDS and isinstance(value, (list, tuple)):
        value = tuple(value)
    problem = _problem(setting, value)
    if problem:
        raise ValueError(f"{setting.key}: {problem}")
    return value


_TRUE_WORDS = ("true", "yes", "on", "1")
_FALSE_WORDS = ("false", "no", "off", "0")


def _parse_bool(setting: Setting, raw: str) -> bool:
    word = raw.lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise ValueError(f"{setting.key}: expected true or false, got {raw!r}")


def _parse_int(setting: Setting, raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{setting.key}: expected a whole number, got {raw!r}") from None


def _parse_enum(setting: Setting, raw: str) -> str:
    for choice in setting.choices:
        if choice.lower() == raw.lower():
            return choice
    raise ValueError(f"{setting.key}: {raw!r} is not one of: {', '.join(setting.choices)}")


def _parse_list(raw: str) -> Tuple[str, ...]:
    parts = (piece.strip() for piece in raw.split(","))
    return tuple(piece for piece in parts if piece)


def parse_value(setting: Setting, text: str) -> Any:
    """Turn user-typed text into a typed, checked value. ValueError on bad input."""
    if not isinstance(text, str):
        raise ValueError(f"{setting.key}: expected text to parse, got {_type_name(text)}")
    raw = text.strip()
    if setting.kind == "bool":
        value: Any = _parse_bool(setting, raw)
    elif setting.kind == "int":
        value = _parse_int(setting, raw)
    elif setting.kind == "enum":
        value = _parse_enum(setting, raw)
    elif setting.kind in LIST_KINDS:
        value = _parse_list(raw)
    else:
        value = raw
    return _validated(setting, value)


@dataclass(frozen=True)
class Config:
    """A loaded configuration. `data` is deep-frozen; derive changes with `with_value`.

    `exists` is whether the file was on disk; `error` is set when it could not be
    used as-is (bad JSON, unreadable, wrong shape) and defaults stand in.
    """

    data: Mapping[str, Any]
    path: str
    exists: bool
    error: Optional[str] = None


def config_path(paths: Paths) -> str:
    return os.path.join(paths.agents_home, CONFIG_FILENAME)


def get(config: Config, key: str) -> Any:
    """Value at a dotted key (leaf or section). KeyError when unknown."""
    node: Any = config.data
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            raise KeyError(key)
        node = node[part]
    return node


def _set_path(node: Any, parts: List[str], value: Any) -> Mapping[str, Any]:
    """Copy of `node` with `parts` set to `value`; untouched branches are shared."""
    head, rest = parts[0], parts[1:]
    base: Dict[str, Any] = dict(node) if isinstance(node, Mapping) else {}
    base[head] = _set_path(base.get(head), rest, value) if rest else value
    return MappingProxyType(base)


def with_value(config: Config, key: str, value: Any) -> Config:
    """A new Config with `key` set. Checks `value` against SETTINGS; the old one is untouched."""
    setting = setting_for(key)
    checked = _validated(setting, value)
    return dataclasses.replace(config, data=_set_path(config.data, key.split("."), checked))


def to_json(config: Config) -> str:
    """Pretty JSON: indent 2, keys in stored order, unicode kept, trailing newline."""
    return json.dumps(_thaw(config.data), indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def _merge(defaults: Mapping[str, Any], override: Mapping[str, Any], prefix: str,
           ignored: List[str]) -> Dict[str, Any]:
    """DEFAULTS <- file. `_comment`-style keys first, then defaults, then other extras.

    A file value of the wrong shape where a section is expected (e.g. "tools": "x")
    is ignored in favour of the defaults and noted in `ignored`.
    """
    out: Dict[str, Any] = {k: v for k, v in override.items() if k.startswith("_")}
    for key, default in defaults.items():
        if key not in override:
            out[key] = default
        elif isinstance(default, Mapping):
            given = override[key]
            if isinstance(given, dict):
                out[key] = _merge(default, given, prefix + key + ".", ignored)
            else:
                ignored.append(prefix + key)
                out[key] = default
        else:
            out[key] = override[key]
    for key, value in override.items():
        out.setdefault(key, value)
    return out


def _read_json(path: str, display: str) -> Tuple[Optional[Mapping[str, Any]], Optional[str]]:
    """(parsed object, None) or (None, error text)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON in {display}: {exc.msg} (line {exc.lineno}, column {exc.colno})"
    except (OSError, ValueError, RecursionError) as exc:
        return None, f"cannot read {display}: {exc}"
    if not isinstance(raw, dict):
        return None, f"{display} must contain a JSON object, found {_type_name(raw)}"
    return raw, None


def load(paths: Paths) -> Config:
    """Read ~/.agents/config.json over DEFAULTS. A bad file yields defaults plus `error`."""
    path = config_path(paths)
    if not os.path.exists(path):
        return Config(data=DEFAULTS, path=path, exists=False)
    raw, error = _read_json(path, paths.display(path))
    if raw is None:
        return Config(data=DEFAULTS, path=path, exists=True, error=error)
    ignored: List[str] = []
    merged = _merge(DEFAULTS, raw, "", ignored)
    if ignored:
        error = "ignored non-object values (defaults used) for: " + ", ".join(ignored)
    return Config(data=_freeze(merged), path=path, exists=True, error=error)


def _backup_existing(target: str, backup_dir: str) -> str:
    """Copy (never move) `target` to <backup_dir>/config.json, or config.N.json on a clash."""
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, CONFIG_FILENAME)
    attempt = 0
    while os.path.lexists(dest):
        attempt += 1
        dest = os.path.join(backup_dir, f"config.{attempt}.json")
    shutil.copy2(target, dest)
    return dest


def _quarantine(tmp: str, backup_dir: str) -> None:
    """Best effort: move a leftover temp file under the backup dir instead of removing it."""
    try:
        if os.path.lexists(tmp):
            os.makedirs(backup_dir, exist_ok=True)
            os.replace(tmp, os.path.join(backup_dir, os.path.basename(tmp)))
    except OSError:
        pass


def _file_mode(real: str) -> int:
    try:
        return stat.S_IMODE(os.stat(real).st_mode)
    except OSError:
        return 0o644


def _atomic_write(real: str, text: str, backup_dir: str) -> None:
    """Temp file in the same directory, flushed, then os.replace over `real`."""
    directory = os.path.dirname(real)
    os.makedirs(directory, exist_ok=True)
    mode = _file_mode(real)
    fd, tmp = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        _quarantine(tmp, backup_dir)
        raise


def save(config: Config, paths: Paths) -> str:
    """Write `config`, backing the previous file up first. Returns the path written.

    The existing file is copied to `paths.backup_root("config")/config.json`
    (shutil.copy2). A symlinked config.json is written through, not replaced.
    """
    target = config.path or config_path(paths)
    text = to_json(config)  # serialise first: a TypeError must not leave a temp file
    backup_dir = paths.backup_root("config")
    if os.path.isfile(target):
        _backup_existing(target, backup_dir)
    _atomic_write(os.path.realpath(target), text, backup_dir)
    return target


def _vault_warnings(vaults: Any) -> List[str]:
    if not isinstance(vaults, (list, tuple)):
        return []
    out: List[str] = []
    for vault in vaults:
        if not isinstance(vault, str) or not vault.strip():
            continue
        expanded = os.path.expanduser(vault)
        if not os.path.exists(expanded):
            out.append(f"paths.obsidian_vaults: vault does not exist: {vault}")
        elif not os.path.isdir(expanded):
            out.append(f"paths.obsidian_vaults: vault is not a directory: {vault}")
    return out


def validate(config: Config) -> Tuple[str, ...]:
    """Warning texts: wrong types, bad enum values, missing vault paths. Empty when clean."""
    warnings: List[str] = []
    for setting in SETTINGS:
        try:
            value = get(config, setting.key)
        except KeyError:
            warnings.append(f"{setting.key}: missing")
            continue
        problem = _problem(setting, value)
        if problem:
            warnings.append(f"{setting.key}: {problem}")
    try:
        warnings.extend(_vault_warnings(get(config, "paths.obsidian_vaults")))
    except KeyError:
        pass
    return tuple(warnings)
