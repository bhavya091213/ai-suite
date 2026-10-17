"""Push configuration changes into tool files that already exist on the machine.

``~/.claude/settings.json`` and ``~/.codex/config.toml`` are installed from the rendered
examples only when absent, so a later change to ``guardrails.hook_profile``,
``guardrails.disabled_hooks`` or ``subagents.codex.*`` never reached a machine that already
had those files. Two functions close the gap:

* ``plan`` compares the configuration with the existing files and returns what would change,
  as ``(path, old_text, new_text)`` triples plus a tuple of ``("skip", reason)`` problems for
  files it chose not to touch and ``("warn", note)`` caveats about files it will change. It
  reads files but writes nothing, and it never raises.
* ``apply`` copies each current file under a backup root first, then replaces it atomically.
  TOML is parsed (when ``tomllib`` exists, Python 3.11+) before the replace and an invalid
  result is refused. Without ``tomllib`` the one conflict ``patch_agents`` can cause in a
  valid file (``agents`` defined by dotted keys or an inline table, then an ``[agents]`` table
  appended) is still caught by a text check, and the plan carries a ``warn`` that the rest
  of the syntax was not verified.

``plan(..., skip_defaults=True)`` pushes only the values that differ from ``config.DEFAULTS``.
It is for the sync that follows ``install.sh``, where ``config.json`` may be the untouched example
that script just copied into place: a default in that file is not a choice, and pushing it would
replace a value set by hand in the tool file. Without the flag every managed key is pushed, which
is what the explicit ``settings-sync`` command wants (the file is the source of truth and the
diff is shown and confirmed first). Settings are judged one by one, so changing ``max_depth``
leaves a hand-edited ``max_threads`` alone.

Edits go through ``claude_settings.patch_env`` (the ``env`` block of settings.json only) and
``codex_config.patch_agents`` / ``patch_model`` (the ``[agents]`` table and the top-level
``model`` line only), so everything else in both files is left as it was. Nothing here deletes
a file: a temp file left by a failed write is moved under the backup root instead.

``diff_lines`` hides the value of anything that looks like a secret (env entries other than the
two this module manages, and keys named like a token, key, secret or password), because the
diff context and a reformatted file can show neighbours of the line that really changed.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import stat
import tempfile
from functools import partial
from typing import Any, Callable, Mapping, NamedTuple, Optional, Tuple

from installer.core import claude_settings, codex_config
from installer.core import config as config_module
from installer.core.paths import Paths

CLAUDE_FILE = "settings.json"
CODEX_FILE = "config.toml"
HOOK_PROFILE_KEY = claude_settings.HOOK_PROFILE_KEY
DISABLED_HOOKS_KEY = "ECC_DISABLED_HOOKS"
MANAGED_ENV_KEYS = frozenset((HOOK_PROFILE_KEY, DISABLED_HOOKS_KEY))
SKIP = "skip"
WARN = "warn"
MASK = "***"
NOT_TOML = "a = ="  # codex_config.check returns None for it only when it cannot parse TOML at all

Change = Tuple[str, str, str]  # (path, old_text, new_text)
Problem = Tuple[str, str]  # (SKIP or WARN, text)


class SettingsPlan(NamedTuple):
    """What ``plan`` found: files to change, and files it left alone (with the reason)."""

    changes: Tuple[Change, ...]
    problems: Tuple[Problem, ...]


class Outcome(NamedTuple):
    """The result of applying one change. ``backup`` is the copy of the old file ('' if none)."""

    path: str
    ok: bool
    message: str
    backup: str = ""


class SettingsError(Exception):
    """A change that was refused; the message says why."""


# ------------------------------------------------------------------ helpers


def _dig(data: Any, dotted: str, default: Any = None) -> Any:
    node = data
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _setting(config_data: Mapping, key: str) -> Any:
    """The configured value for a dotted key; the documented default when the key is absent."""
    return _dig(config_data, key, _dig(config_module.DEFAULTS, key))


def _same(left: Any, right: Any) -> bool:
    """Equality that treats a list and a tuple holding the same items as equal."""
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return list(left) == list(right)
    return left == right


def _wanted(config_data: Mapping, key: str, skip_defaults: bool) -> bool:
    """Whether ``key`` is pushed: always, or (``skip_defaults``) only when it differs from the default."""
    return not (skip_defaults and _same(_setting(config_data, key), _dig(config_module.DEFAULTS, key)))


def _read(path: str) -> str:
    """The file as text with line endings untouched. Raises OSError / UnicodeDecodeError."""
    with open(path, "rb") as handle:
        return handle.read().decode("utf-8")


def _skip(paths: Paths, path: str, reason: str) -> Problem:
    return (SKIP, f"{paths.display(path)}: {reason}")


# ------------------------------------------------------------ settings.json


def _disabled_hooks(value: Any) -> Optional[str]:
    """Comma-joined hook ids, '' when none are disabled, None when the value is not a list."""
    if value is None:
        return ""
    if not isinstance(value, (list, tuple)):
        return None
    return ",".join(item.strip() for item in value if isinstance(item, str) and item.strip())


def _claude_updates(config_data: Mapping,
                    skip_defaults: bool = False) -> Tuple[Mapping[str, Optional[str]], Tuple[str, ...]]:
    """(env updates, reasons a key was left out). ``None`` means 'remove this env key'."""
    updates = {}
    notes = []
    profile = _setting(config_data, "guardrails.hook_profile")
    if profile not in claude_settings.HOOK_PROFILES:
        notes.append("guardrails.hook_profile %r is not one of %s; %s left as it is"
                     % (profile, ", ".join(claude_settings.HOOK_PROFILES), HOOK_PROFILE_KEY))
    elif _wanted(config_data, "guardrails.hook_profile", skip_defaults):
        updates[HOOK_PROFILE_KEY] = profile
    joined = _disabled_hooks(_setting(config_data, "guardrails.disabled_hooks"))
    if joined is None:
        notes.append("guardrails.disabled_hooks is not a list; %s left as it is" % DISABLED_HOOKS_KEY)
    elif _wanted(config_data, "guardrails.disabled_hooks", skip_defaults):
        updates[DISABLED_HOOKS_KEY] = joined or None
    return updates, tuple(notes)


def _env_matches(text: str, updates: Mapping[str, Optional[str]]) -> bool:
    """True when the env block already holds every update (so the file need not be rewritten)."""
    try:
        data = json.loads(text)
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    env = data.get(claude_settings.ENV_KEY)
    if env is None:
        env = {}
    elif not isinstance(env, dict):
        return False
    return all((key not in env) if value is None else env.get(key) == value
               for key, value in updates.items())


def _plan_claude(config_data: Mapping, paths: Paths,
                 skip_defaults: bool = False) -> Tuple[Optional[Change], Tuple[Problem, ...]]:
    path = os.path.join(paths.claude_home, CLAUDE_FILE)
    if not os.path.isfile(path):
        return None, ()
    updates, notes = _claude_updates(config_data, skip_defaults)
    problems = tuple(_skip(paths, path, note) for note in notes)
    try:
        old = _read(path)
        if _env_matches(old, updates):
            return None, problems
        new = claude_settings.patch_env(old, updates)
    except (OSError, ValueError) as exc:
        return None, problems + (_skip(paths, path, str(exc)),)
    return ((path, old, new) if new != old else None), problems


# -------------------------------------------------------------- config.toml


_AGENTS = r"""(?:agents|"agents"|'agents')"""
_AGENTS_TABLE_RE = re.compile(r"^[ \t]*\[[ \t]*%s[ \t]*\]" % _AGENTS, re.MULTILINE)
_AGENTS_KEY_RE = re.compile(r"^[ \t]*%s[ \t]*[.=]" % _AGENTS, re.MULTILINE)
LIMITS = ("max_threads", "max_depth")


def _agents_limit(text: str, name: str) -> Optional[int]:
    """The plain integer ``name`` holds in the ``[agents]`` table now; None when missing or not one."""
    pattern = re.compile(r"^[ \t]*%s[ \t]*=[ \t]*(\d+)[ \t]*(?:#.*)?$" % re.escape(name))
    inside = False
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            inside = bool(_AGENTS_TABLE_RE.match(line))
            continue
        match = pattern.match(line) if inside else None
        if match:
            return int(match.group(1))
    return None


def _limit(config_data: Mapping, old: str, name: str, skip_defaults: bool) -> Any:
    """The value to write for an [agents] limit: the configured one, or the one the file has when
    only the other limit is being pushed (``patch_agents`` always sets both)."""
    key = "subagents.codex." + name
    if _wanted(config_data, key, skip_defaults):
        return _setting(config_data, key)
    current = _agents_limit(old, name)
    return _setting(config_data, key) if current is None else current


def _patched_toml(config_data: Mapping, old: str, skip_defaults: bool = False) -> str:
    text = old
    if any(_wanted(config_data, "subagents.codex." + name, skip_defaults) for name in LIMITS):
        text = codex_config.patch_agents(text, *(_limit(config_data, old, name, skip_defaults) for name in LIMITS))
    if _wanted(config_data, "subagents.codex.model", skip_defaults):
        text = codex_config.patch_model(text, _setting(config_data, "subagents.codex.model"))
    return text


def _agents_twice(text: str) -> bool:
    """True when ``agents`` is set by dotted keys or an inline table *and* has an ``[agents]`` table.

    TOML forbids that, and ``patch_agents`` would create it by appending ``[agents]`` to a file
    that sets ``agents.max_threads = 3``. ``codex_config.check`` sees it only with ``tomllib``
    (Python 3.11+), so this text check runs on every version. It may also fire for an
    ``agents.x`` key inside another table; skipping the file then is the safe side.
    """
    return bool(_AGENTS_TABLE_RE.search(text) and _AGENTS_KEY_RE.search(text))


def _toml_unchecked() -> bool:
    """True on a Python without ``tomllib``, where ``codex_config.check`` cannot parse anything."""
    return codex_config.check(NOT_TOML) is None


def _toml_problem(old: str, new: str) -> Optional[str]:
    """Why the edit should not be made, or None. An unparsable file is left to the user."""
    broken = codex_config.check(old)
    if broken is not None:
        return "is not valid TOML (%s); fix it by hand first" % broken
    if _agents_twice(old):
        return "defines agents twice (dotted keys and an [agents] table); fix it by hand first"
    if _agents_twice(new):
        return ("sets agents with dotted keys or an inline table, so an [agents] table cannot be added; "
                "edit max_threads / max_depth there by hand; left unchanged")
    broken = codex_config.check(new)
    if broken is not None:
        return "would not be valid TOML after the edit (%s); left unchanged" % broken
    return None


def _plan_codex(config_data: Mapping, context: Mapping, paths: Paths,
                skip_defaults: bool = False) -> Tuple[Optional[Change], Tuple[Problem, ...]]:
    path = os.path.join(paths.codex_home, CODEX_FILE)
    if not _dig(context, "profile.codex", False) or not os.path.isfile(path):
        return None, ()
    try:
        old = _read(path)
        new = _patched_toml(config_data, old, skip_defaults)
    except (OSError, ValueError) as exc:
        return None, (_skip(paths, path, str(exc)),)
    if new == old:
        return None, ()
    reason = _toml_problem(old, new)
    if reason is not None:
        return None, (_skip(paths, path, reason),)
    if _toml_unchecked():
        note = "TOML syntax not verified (this Python has no tomllib; 3.11+ checks it); the old file is backed up first"
        return (path, old, new), ((WARN, "%s: %s" % (paths.display(path), note)),)
    return (path, old, new), ()


# --------------------------------------------------------------------- plan


def plan(config_data: Mapping, context: Mapping, paths: Paths, skip_defaults: bool = False) -> SettingsPlan:
    """What would change in the existing settings.json and config.toml, plus what was skipped.

    ``config_data`` is ``Config.data``; ``context`` is the template context
    (``render.build_context``), whose ``profile.codex`` says whether Codex is in use. A file
    that is missing, already up to date, or (config.toml) belongs to an unused tool yields
    nothing. A file that cannot be parsed or edited yields a ``("skip", reason)`` problem; a
    change whose syntax could not be verified carries a ``("warn", note)``. With
    ``skip_defaults`` a setting that equals its documented default is not pushed at all (see
    the module docstring). Never raises and never writes.
    """
    claude_change, claude_problems = _plan_claude(config_data, paths, skip_defaults)
    codex_change, codex_problems = _plan_codex(config_data, context, paths, skip_defaults)
    changes = tuple(change for change in (claude_change, codex_change) if change is not None)
    return SettingsPlan(changes, claude_problems + codex_problems)


_SECRET_KEY_RE = re.compile(r"token|secret|passw|credential|auth|key|bearer|cookie", re.IGNORECASE)
_STRING = r'"(?:[^"\\]|\\.)*"'
_JSON_PAIR_RE = re.compile(r"(?P<key>%s)(?P<sep>\s*:\s*)(?P<value>%s)" % (_STRING, _STRING))
_TOML_PAIR_RE = re.compile(r"""(?P<key>[\w.\-]+|"[^"]*"|'[^']*')(?P<sep>\s*=\s*)(?P<value>%s|'[^']*')""" % _STRING)


def _env_names(*texts: str) -> frozenset:
    """Names in the ``env`` object of the JSON texts, minus the two keys this module manages."""
    names = set()
    for text in texts:
        try:
            data = json.loads(text)
        except ValueError:
            continue
        env = data.get(claude_settings.ENV_KEY) if isinstance(data, dict) else None
        if isinstance(env, dict):
            names.update(name for name in env if name not in MANAGED_ENV_KEYS)
    return frozenset(names)


def _mask(hidden: frozenset, match: "re.Match[str]") -> str:
    name = match.group("key").strip("\"'")
    if name in MANAGED_ENV_KEYS or not (name in hidden or _SECRET_KEY_RE.search(name)):
        return match.group(0)
    return "%s%s\"%s\"" % (match.group("key"), match.group("sep"), MASK)


def _redactor(path: str, old: str, new: str) -> Callable[[str], str]:
    """A line filter that replaces secret-looking string values with ``"***"``.

    In ``settings.json`` every ``env`` entry except the managed ones counts as secret, and so
    does any key whose name suggests a token, key, secret or password. In TOML only the key
    names count. Free text such as a hook command is not inspected.
    """
    if path.endswith(".json"):
        pattern, hidden = _JSON_PAIR_RE, _env_names(old, new)
    elif path.endswith(".toml"):
        pattern, hidden = _TOML_PAIR_RE, frozenset()
    else:
        return lambda line: line
    return lambda line: pattern.sub(partial(_mask, hidden), line)


def diff_lines(change: Change, label: Optional[str] = None) -> Tuple[str, ...]:
    """A unified diff of one change, as lines without trailing newlines.

    Secret-looking values are shown as ``"***"`` (see ``_redactor``), so printing the diff is
    safe even when a token sits next to the changed line or the whole file is reformatted.
    """
    path, old, new = change
    shown = label or path
    redact = _redactor(path, old, new)
    diff = difflib.unified_diff([redact(line) for line in old.splitlines()],
                                [redact(line) for line in new.splitlines()],
                                fromfile=shown + " (current)", tofile=shown + " (new)", lineterm="", n=1)
    return tuple(diff)


# -------------------------------------------------------------------- apply


def _validate(path: str, new: str) -> None:
    """Refuse text that would leave the file unreadable by its tool."""
    if path.endswith(".toml"):
        broken = codex_config.check(new)
        if broken is None and _agents_twice(new):
            broken = "agents is set by dotted keys or an inline table and also has an [agents] table"
        if broken is not None:
            raise SettingsError("refusing to write invalid TOML: %s" % broken)
    elif path.endswith(".json"):
        try:
            json.loads(new)
        except ValueError as exc:
            raise SettingsError("refusing to write invalid JSON: %s" % exc)


def _home_relative(path: str, home: Optional[str]) -> str:
    """Path below ``home`` when it is under it, else '<parent dir name>/<file name>'."""
    target = os.path.abspath(path)
    if home:
        base = os.path.abspath(home)
        if target.startswith(base + os.sep):
            return os.path.relpath(target, base)
    return os.path.join(os.path.basename(os.path.dirname(target)), os.path.basename(target))


def _free_name(dest: str) -> str:
    """``dest``, or ``stem.N.ext`` when it exists already, so a backup never overwrites one."""
    if not os.path.lexists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    attempt = 1
    while os.path.lexists("%s.%d%s" % (stem, attempt, ext)):
        attempt += 1
    return "%s.%d%s" % (stem, attempt, ext)


def _backup(path: str, backup_root: str, home: Optional[str]) -> str:
    dest = _free_name(os.path.join(backup_root, _home_relative(path, home)))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def _quarantine(tmp: str, backup_root: str) -> None:
    """Best effort: move a leftover temp file under the backup root instead of removing it."""
    try:
        if os.path.lexists(tmp):
            os.makedirs(backup_root, exist_ok=True)
            os.replace(tmp, _free_name(os.path.join(backup_root, os.path.basename(tmp))))
    except OSError:
        pass


def _file_mode(path: str) -> int:
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return 0o644


def _atomic_write(real: str, text: str, backup_root: str) -> None:
    """Temp file next to ``real``, flushed, then ``os.replace``; the old mode is kept."""
    directory = os.path.dirname(real)
    mode = _file_mode(real)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(real) + ".", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        _quarantine(tmp, backup_root)
        raise


def _apply_one(change: Change, backup_root: str, home: Optional[str]) -> Outcome:
    path, old, new = change
    try:
        if not backup_root:
            raise SettingsError("no backup location given; refusing to overwrite without a backup")
        _validate(path, new)
        real = os.path.realpath(path)  # a symlinked file is written through, not replaced
        if _read(real) != old:
            raise SettingsError("changed since the plan was made; run the command again")
        backup = _backup(path, backup_root, home)
        _atomic_write(real, new, backup_root)
    except SettingsError as exc:
        return Outcome(path, False, str(exc))
    except (OSError, ValueError) as exc:
        return Outcome(path, False, "%s: %s" % (type(exc).__name__, exc))
    return Outcome(path, True, "updated", backup)


def apply(changes: Tuple[Change, ...], backup_root: str, home: Optional[str] = None) -> Tuple[Outcome, ...]:
    """Back up and rewrite each file; one ``Outcome`` per change, in order.

    The current file is copied to ``<backup_root>/<path relative to home>`` first (``home``
    defaults to the parent directory's name, so ``.claude/settings.json``). A file that
    changed since the plan, text that does not parse, or a failed backup or write is
    reported as ``ok=False`` and that file is left exactly as it was; the others still run.
    """
    return tuple(_apply_one(change, backup_root, home) for change in changes)
