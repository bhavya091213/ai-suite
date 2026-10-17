"""Path-specific rewrite rules applied while the installer renders repo files.

``rewrite(rel_path, text, context)`` dispatches on the POSIX repo-relative path to one of six
rules (ARCHITECTURE.md, "core/rewrite.py"); any other path comes back untouched. Every rule is a
pure function of ``(text, context)``.

``context`` is a plain mapping shaped like ``render.build_context`` output, read with a safe
nested lookup: a missing (or ``None``) key means "leave that part alone". Switches such as
``profile.headroom`` only act when the key is present and false.

TOML and frontmatter edits are text-level, so comments, ordering and blank lines survive. JSON
files are parsed (key order kept) and written with ``indent=2`` and a trailing newline; a rule
that changes nothing returns the original text, so an untouched file is never reformatted.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_MISSING = object()


# ---------- context access
def _lookup(context: Any, *path: str) -> Any:
    """Nested ``.get`` over mappings; returns ``_MISSING`` when any step is absent."""
    current = context
    for key in path:
        if not isinstance(current, Mapping):
            return _MISSING
        current = current.get(key, _MISSING)
    return current


def _text(context: Any, *path: str) -> Optional[str]:
    """A non-empty string value, else None."""
    value = _lookup(context, *path)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int(context: Any, *path: str, minimum: int = 0) -> Optional[int]:
    """A whole number >= ``minimum`` (int, or a string of ASCII digits); anything else is None.

    ``str.isdigit`` accepts characters ``int`` rejects (e.g. superscripts), and ``int``/``str``
    refuse absurdly long numbers, so every conversion is guarded: a bad value counts as missing.
    """
    value = _lookup(context, *path)
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        token = value.strip()
        if not (token.isascii() and token.isdigit()):
            return None
        try:
            value = int(token)
        except ValueError:
            return None
    if not isinstance(value, int) or value < minimum:
        return None
    try:
        str(value)
    except ValueError:
        return None
    return value


def _is_off(context: Any, *path: str) -> bool:
    """True only when the key is present, not None, and falsy."""
    value = _lookup(context, *path)
    return value is not _MISSING and value is not None and not value


# ---------- shared line helpers
def _split_cr(line: str) -> Tuple[str, str]:
    """Separate a trailing carriage return so CRLF files keep their endings."""
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _comment_out(line: str) -> str:
    """Prefix a live, non-blank line with ``# ``; blank and comment lines are untouched."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return line
    return "# " + line


# ---------- rule 1: Claude agents
_CLAUDE_TIERS = {"opus": "claude_heavy", "sonnet": "claude_light", "haiku": "claude_trivial"}
_MODEL_LINE = re.compile(
    r"^(?P<pre>model:[ \t]*)(?P<q>[\"']?)(?P<val>opus|sonnet|haiku)(?P=q)"
    r"(?P<post>[ \t]*(?:#.*)?)$"
)
_PLAIN_YAML = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\[\]/-]*$")


def _frontmatter_end(lines: Sequence[str]) -> Optional[int]:
    """Index of the closing ``---`` line, or None when there is no frontmatter block."""
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r") == "---":
            return index
    return None


def _yaml_scalar(value: str, quote: str) -> str:
    if quote == "'" and "'" not in value:
        return "'" + value + "'"
    if quote == '"' or not _PLAIN_YAML.match(value):
        return json.dumps(value)
    return value


def _retier_model_line(line: str, context: Any) -> str:
    body, cr = _split_cr(line)
    match = _MODEL_LINE.match(body)
    if not match:
        return line
    new = _text(context, "profile", _CLAUDE_TIERS[match.group("val")])
    if new is None:
        return line
    value = _yaml_scalar(new, match.group("q"))
    return match.group("pre") + value + match.group("post") + cr


def _rewrite_claude_agent(text: str, context: Any) -> str:
    lines = text.split("\n")
    end = _frontmatter_end(lines)
    if end is None:
        return text
    rewritten = [
        _retier_model_line(line, context) if 0 < index < end else line
        for index, line in enumerate(lines)
    ]
    return "\n".join(rewritten)


# ---------- TOML line scanner
_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")


_TRIPLE_QUOTE = re.compile(r"(?<!\\)\"\"\"|'''")


def _string_state(body: str, delim: Optional[str]) -> Optional[str]:
    """Multi-line string delimiter still open at the end of ``body`` (None = closed)."""
    for match in _TRIPLE_QUOTE.finditer(body):
        token = match.group()
        if delim is None:
            delim = token
        elif token == delim:
            delim = None
    return delim


def _scan_toml(lines: Sequence[str]) -> List[Tuple[bool, Optional[str]]]:
    """Per line: (is live code, current table name; None before the first header).

    Comment lines, blank lines and the insides of multi-line strings are not live code, so a
    ``model = ...`` sentence inside ``developer_instructions`` is never mistaken for a key.
    """
    result: List[Tuple[bool, Optional[str]]] = []
    table: Optional[str] = None
    delim: Optional[str] = None
    for line in lines:
        body = line.rstrip("\r")
        if delim is not None:
            result.append((False, table))
            delim = _string_state(body, delim)
            continue
        stripped = body.strip()
        live = bool(stripped) and not stripped.startswith("#")
        header = _HEADER_RE.match(body) if live else None
        if header:
            table = header.group(1)
        result.append((live, table))
        if live and not header:
            delim = _string_state(body, None)
    return result


def _key_pattern(key: str) -> "re.Pattern[str]":
    return re.compile(
        r"^(?P<pre>\s*" + re.escape(key) + r"\s*=\s*)"
        r"(?P<val>\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^\s#]+)(?P<post>.*)$"
    )


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _replace_key(lines: Sequence[str], key: str, make: Callable[[str], Optional[str]],
                 table: Optional[str] = None, first_only: bool = False) -> List[str]:
    """Rewrite ``key = <value>`` lines of live TOML code inside ``table`` (None = top level).

    ``make`` receives the raw value token and returns the replacement token, or None to leave
    the line alone. With ``first_only`` only the first matching line is considered.
    """
    pattern = _key_pattern(key)
    result: List[str] = []
    seen = False
    for line, (live, current) in zip(lines, _scan_toml(lines)):
        match = pattern.match(line) if live and current == table and not seen else None
        if match is not None and first_only:
            seen = True
        replacement = make(match.group("val")) if match is not None else None
        if match is not None and replacement is not None:
            line = match.group("pre") + replacement + match.group("post")
        result.append(line)
    return result


# ---------- rule 2: Codex roles
_EFFORT_TIERS = {
    "xhigh": "codex_heavy", "max": "codex_heavy", "high": "codex_heavy",
    "medium": "codex_light",
    "low": "codex_trivial", "minimal": "codex_trivial",
}


def _effort_token(context: Any) -> Callable[[str], Optional[str]]:
    def make(token: str) -> Optional[str]:
        field = _EFFORT_TIERS.get(_unquote(token).strip().lower())
        new = _text(context, "profile", field) if field else None
        return json.dumps(new) if new else None
    return make


def _model_token(context: Any) -> Optional[Callable[[str], Optional[str]]]:
    model = _text(context, "profile", "codex_model")
    if model is None:
        return None
    return lambda _token: json.dumps(model)


def _rewrite_codex_agent(text: str, context: Any) -> str:
    lines = text.split("\n")
    make_model = _model_token(context)
    if make_model is not None:
        lines = _replace_key(lines, "model", make_model, first_only=True)
    lines = _replace_key(lines, "model_reasoning_effort", _effort_token(context))
    return "\n".join(lines)


# ---------- rule 3: Codex config
_HEADROOM_MARK = re.compile(
    r"^\s*#\s*---\s+(?P<end>end\s+)?Headroom\b(?P<name>.*?)\s+---\s*$", re.IGNORECASE
)
_HEADROOM_TOP_LEVEL = re.compile(
    r"^\s*(?:model_provider\s*=\s*[\"']headroom[\"']|openai_base_url\s*=)"
)


def _marker(line: str) -> Optional[Tuple[bool, str]]:
    match = _HEADROOM_MARK.match(line)
    if match is None:
        return None
    return bool(match.group("end")), match.group("name").strip().lower()


def _headroom_spans(lines: Sequence[str]) -> List[Tuple[int, int]]:
    """(first, last-exclusive) line ranges strictly between matched start/end markers."""
    marks = [_marker(line) for line in lines]
    spans: List[Tuple[int, int]] = []
    index = 0
    while index < len(lines):
        mark = marks[index]
        if mark is not None and not mark[0]:
            end = next((j for j in range(index + 1, len(lines))
                        if marks[j] == (True, mark[1])), None)
            if end is not None:
                spans.append((index + 1, end))
                index = end
        index += 1
    return spans


def _comment_headroom(lines: Sequence[str]) -> List[str]:
    inside = set()
    for first, last in _headroom_spans(lines):
        inside.update(range(first, last))
    result = [_comment_out(line) if index in inside else line
              for index, line in enumerate(lines)]
    return [
        _comment_out(line) if live and table is None and _HEADROOM_TOP_LEVEL.match(line)
        else line
        for line, (live, table) in zip(result, _scan_toml(result))
    ]


def _rewrite_codex_config(text: str, context: Any) -> str:
    lines = text.split("\n")
    make_model = _model_token(context)
    if make_model is not None:
        lines = _replace_key(lines, "model", make_model, first_only=True)
    for key, minimum in (("max_threads", 1), ("max_depth", 0)):
        number = _int(context, "config", "subagents", "codex", key, minimum=minimum)
        if number is not None:
            lines = _replace_key(lines, key, lambda _t, n=number: str(n), table="agents")
    if _is_off(context, "profile", "headroom"):
        lines = _comment_headroom(lines)
    return "\n".join(lines)


# ---------- JSON helpers
def _load_object(text: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _finish_json(text: str, original: Dict[str, Any], data: Dict[str, Any]) -> str:
    """Dump ``data`` (indent=2, trailing newline), or return ``text`` when nothing changed."""
    if data == original:
        return text
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _without(section: Any, key: str) -> Any:
    """Copy of a mapping minus ``key`` (the input is returned when there is nothing to drop)."""
    if not isinstance(section, dict) or key not in section:
        return section
    return {k: v for k, v in section.items() if k != key}


def _drop_nested(data: Dict[str, Any], outer: str, inner: str) -> Dict[str, Any]:
    if outer not in data:
        return data
    return {**data, outer: _without(data[outer], inner)}


def _is_headroom_hook(hook: Any) -> bool:
    command = hook.get("command") if isinstance(hook, dict) else None
    return isinstance(command, str) and "headroom" in command.lower()


def _strip_group(group: Any) -> Any:
    """Group minus headroom hooks; None when that empties a non-empty group."""
    inner = group.get("hooks") if isinstance(group, dict) else None
    if not isinstance(inner, list):
        return group
    kept = [hook for hook in inner if not _is_headroom_hook(hook)]
    if len(kept) == len(inner):
        return group
    return {**group, "hooks": kept} if kept else None


def _strip_headroom_hooks(hooks: Any) -> Any:
    """``{event: [group, ...]}`` without headroom commands, empty groups and empty events."""
    if not isinstance(hooks, dict):
        return hooks
    result: Dict[str, Any] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            result[event] = groups
            continue
        kept = [g for g in (_strip_group(group) for group in groups) if g is not None]
        if kept or not groups:
            result[event] = kept
    return result


def _drop_headroom_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    if "hooks" not in data:
        return data
    return {**data, "hooks": _strip_headroom_hooks(data["hooks"])}


# ---------- rule 4: Claude settings
def _join_hooks(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value if str(item).strip())
    return ""


def _env_updates(context: Any) -> Dict[str, Optional[str]]:
    """Wanted ``env`` changes; a None value means "remove this key"."""
    updates: Dict[str, Optional[str]] = {}
    profile = _text(context, "profile", "hook_profile")
    if profile is not None:
        updates["ECC_HOOK_PROFILE"] = profile
    disabled = _lookup(context, "profile", "disabled_hooks")
    if disabled is not _MISSING and disabled is not None:
        updates["ECC_DISABLED_HOOKS"] = _join_hooks(disabled) or None
    if _is_off(context, "profile", "headroom"):
        updates["ANTHROPIC_BASE_URL"] = None
    return updates


def _apply_env(data: Dict[str, Any], context: Any) -> Dict[str, Any]:
    updates = _env_updates(context)
    current = data.get("env", {})
    if not updates or not isinstance(current, dict):
        return data
    env = dict(current)
    for key, value in updates.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    if not env and "env" not in data:
        return data
    return {**data, "env": env}


def _rewrite_claude_settings(text: str, context: Any) -> str:
    original = _load_object(text)
    if original is None:
        return text
    data = _apply_env(original, context)
    if _is_off(context, "profile", "headroom"):
        data = _drop_headroom_hooks(data)
        data = _drop_nested(data, "enabledPlugins", "headroom@headroom-marketplace")
        data = _drop_nested(data, "extraKnownMarketplaces", "headroom-marketplace")
    if _is_off(context, "profile", "codex"):
        data = _drop_nested(data, "enabledPlugins", "codex@openai-codex")
        data = _drop_nested(data, "extraKnownMarketplaces", "openai-codex")
    return _finish_json(text, original, data)


# ---------- rules 5 and 6
def _rewrite_codex_hooks(text: str, context: Any) -> str:
    original = _load_object(text)
    if original is None or not _is_off(context, "profile", "headroom"):
        return text
    return _finish_json(text, original, _drop_headroom_hooks(original))


def _prune_targets(spec: Any, off: Sequence[str]) -> Any:
    """Server spec minus disabled tools in ``targets``; None when that leaves it empty."""
    targets = spec.get("targets") if isinstance(spec, dict) else None
    if not off or not isinstance(targets, list):
        return spec
    kept = [target for target in targets if target not in off]
    if len(kept) == len(targets):
        return spec
    return {**spec, "targets": kept} if kept else None


def _rewrite_mcp_servers(text: str, context: Any) -> str:
    original = _load_object(text)
    servers = original.get("servers") if original is not None else None
    if original is None or not isinstance(servers, dict):
        return text
    off = [tool for tool in ("codex", "claude") if _is_off(context, "profile", tool)]
    headroom_off = _is_off(context, "profile", "headroom")
    kept: Dict[str, Any] = {}
    for name, spec in servers.items():
        if name == "headroom" and headroom_off:
            continue
        pruned = _prune_targets(spec, off)
        if pruned is not None:
            kept[name] = pruned
    return _finish_json(text, original, {**original, "servers": kept})


# ---------- dispatch
_RULES: Tuple[Tuple[str, Callable[[str, Any], str]], ...] = (
    ("claude-code/agents/*.md", _rewrite_claude_agent),
    ("codex/agents/*.toml", _rewrite_codex_agent),
    ("codex/config.example.toml", _rewrite_codex_config),
    ("claude-code/settings.example.json", _rewrite_claude_settings),
    ("codex/hooks.json", _rewrite_codex_hooks),
    ("shared/mcp-servers.json", _rewrite_mcp_servers),
)


def _normalize(rel_path: str) -> str:
    rel = rel_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _matches(rel: str, pattern: str) -> bool:
    # fnmatch's "*" also matches "/", so require the same directory depth as the pattern
    return rel.count("/") == pattern.count("/") and fnmatch.fnmatchcase(rel, pattern)


def rewrite(rel_path: str, text: str, context: Mapping) -> str:
    """Apply the path-specific rule for ``rel_path`` to ``text``; identity for other paths."""
    if not isinstance(text, str) or not isinstance(rel_path, str):
        return text
    rel = _normalize(rel_path)
    for pattern, rule in _RULES:
        if _matches(rel, pattern):
            return rule(text, context if isinstance(context, Mapping) else {})
    return text
