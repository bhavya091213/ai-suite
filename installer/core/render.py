"""Opt-in template engine, requires markers, context building and tree rendering.

Rendering is opt-in per file: a line containing ``installer:template`` within the
first five lines turns it on (``ALWAYS_TEMPLATE`` paths are rendered regardless).
Nothing in a non-template file is ever interpreted. Syntax (ARCHITECTURE.md Part 2):

    {{ expr }}  {{ expr | tilde }}  {{ expr | k }}  {{ expr | join(" / ") }}  {{ expr | default("x") }}
    {% if expr %} .. {% elif expr %} .. {% else %} .. {% endif %}
    {% for name in expr %} .. {% endfor %}      (loop.index / loop.first / loop.last)

``expr`` is described in ``installer.core.template_expr``. Unknown paths evaluate to ``None``
and are recorded as warnings; malformed or unbalanced tags raise
``RenderError("<source>:<line>: ...")``. Every line containing ``installer:template`` and
every header line carrying ``installer:requires`` is dropped from the output; a block tag
alone on its line consumes the whole line; booleans render as ``true``/``false``; lists are
joined with ", "; ``None`` renders as "".
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from installer.core.paths import Paths
from installer.core.template_expr import (BlockToken, Evaluator, RenderError, parse_blocks,
                                          resolve, short_count)
from installer.core.types import IGNORED_DIR_NAMES, IGNORED_FILE_NAMES

__all__ = [
    "ALWAYS_TEMPLATE", "RenderError", "RenderReport", "build_context", "is_template",
    "parse_requires_file", "render_text", "render_tree", "requirements_met", "requires_of",
    "resolve_tool", "short_count",
]

TEMPLATE_MARKER = "installer:template"
REQUIRES_MARKER = "installer:requires"
REQUIRES_FILE = ".installer-requires"
HEADER_LINES = 5
ALWAYS_TEMPLATE: Tuple[str, ...] = ("codex/AGENTS.md",)

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")
_REQUIRES_RE = re.compile(r"installer:requires(-any)?(?![\w-])(.*)$")
_NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")
_CLOSER_CHARS = "->*/#;"
_TAG_OPEN_RE = re.compile(r"\{\{|\{%")
# A block tag alone on its line (leading blanks .. trailing newline) is consumed whole;
# otherwise block and variable tags are matched where they stand.
_TAG_RE = re.compile(
    r"(?P<alone>^[ \t]*\{%(?P<a>(?:(?!%\}).)*)%\}[ \t]*(?:\r?\n|\Z))"
    r"|\{%(?P<b>(?:(?!%\}).)*)%\}"
    r"|\{\{(?P<v>(?:(?!\}\}).)*)\}\}", re.S | re.M)
_TOOL_KEYS = ("claude", "codex", "gemini")
_PRESENT_KEYS = ("docker", "tmux", "headroom", "obsidian", "git", "node")
_TIERS = ("heavy", "light", "trivial")
_MODEL_DEFAULTS = {"claude": ("opus", "sonnet", "haiku"), "codex": ("xhigh", "medium", "low")}

RewriteFn = Callable[[str, str, Mapping], str]


@dataclass(frozen=True)
class RenderReport:
    rendered: Tuple[str, ...]
    copied: Tuple[str, ...]
    excluded: Tuple[Tuple[str, str], ...]
    warnings: Tuple[str, ...]


# ------------------------------------------------------------------ markers

def _lines(text: str) -> List[str]:
    """Split on ``\\n`` only (``str.splitlines`` also breaks on form feeds), keeping endings."""
    return _LINE_RE.findall(text)


def _header(text: str) -> List[str]:
    return _lines(text)[:HEADER_LINES]


def is_template(text: str) -> bool:
    """True when ``installer:template`` appears within the first five lines."""
    return any(TEMPLATE_MARKER in line for line in _header(text))


def requires_of(text: str) -> Tuple[Tuple[str, ...], str]:
    """``(names, "all"|"any")`` from a header ``installer:requires[-any]`` line; ``((), "all")`` when none.

    A marker that is present but malformed (no names, or a name that is not a bare word such
    as ``codex,``) raises ``RenderError`` instead of silently dropping the requirement.
    """
    return _requires_of(text, "<text>")


def _requires_of(text: str, source: str) -> Tuple[Tuple[str, ...], str]:
    for number, line in enumerate(_header(text), 1):
        found = _REQUIRES_RE.search(line)
        if found:
            names = _marker_names(found.group(2), f"{source}:{number}")
            return names, ("any" if found.group(1) else "all")
    return (), "all"


def _marker_names(rest: str, where: str) -> Tuple[str, ...]:
    """Space-separated names up to a comment closer (``-->``, ``*/``, ``#``); never fail open."""
    names: List[str] = []
    for token in rest.split():
        name = token.rstrip(_CLOSER_CHARS)
        if not name:
            break
        if not _NAME_RE.match(name):
            raise RenderError(f"{where}: malformed {REQUIRES_MARKER} marker: {token!r} is not a name "
                              "(separate names with spaces, no commas)")
        names.append(name)
    if not names:
        raise RenderError(f"{where}: malformed {REQUIRES_MARKER} marker: no names given")
    return tuple(names)


def parse_requires_file(text: str) -> Tuple[Tuple[str, ...], str]:
    """Content of a ``.installer-requires`` file: names, optionally prefixed by ``any:``.

    An empty file means no requirement; any other content that does not parse to at least one
    name raises ``RenderError``.
    """
    return _parse_requires_file(text, REQUIRES_FILE)


def _parse_requires_file(text: str, where: str) -> Tuple[Tuple[str, ...], str]:
    body = text.strip()
    if not body:
        return (), "all"
    mode = "all"
    if body.startswith("any:"):
        body, mode = body[4:], "any"
    return _marker_names(body, where), mode


def requirements_met(names: Sequence[str], mode: str, context: Mapping) -> bool:
    """Every (or, for ``mode == "any"``, at least one) named ``profile`` key is truthy."""
    if not names:
        return True
    profile = context.get("profile", {}) if isinstance(context, Mapping) else {}
    flags = [bool(resolve(profile, name.split("."))[1]) for name in names]
    return any(flags) if mode == "any" else all(flags)


def _strip_markers(text: str, template: bool) -> Tuple[str, Tuple[int, ...]]:
    """Drop marker lines. Returns the text and the original 1-based number of each kept line."""
    kept: List[str] = []
    line_map: List[int] = []
    for number, line in enumerate(_lines(text), 1):
        if number <= HEADER_LINES and REQUIRES_MARKER in line:
            continue
        if template and TEMPLATE_MARKER in line:
            continue
        kept.append(line)
        line_map.append(number)
    return "".join(kept), tuple(line_map)


# ------------------------------------------------------------------ context

def _get(mapping: Any, dotted: str, default: Any = None) -> Any:
    found, value = resolve(mapping, dotted.split("."))
    return value if found and value is not None else default


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def resolve_tool(setting: Any, present: bool) -> bool:
    """``auto`` -> detected, ``on`` -> True, ``off`` -> False (booleans pass through)."""
    if isinstance(setting, bool):
        return setting
    text = str(setting or "auto").strip().lower()
    return True if text == "on" else False if text == "off" else bool(present)


def _nvm_versions(caps: Mapping) -> Tuple[str, ...]:
    for candidate in (caps.get("nvm_versions"), _get(caps, "nvm.versions")):
        if isinstance(candidate, (list, tuple)):
            return tuple(str(v) for v in candidate)
    version = _get(caps, "nvm.version", "")
    return tuple(v for v in re.split(r"[,\s]+", str(version).strip()) if v) if version else ()


def _docker_state(caps: Mapping) -> str:
    if not _get(caps, "docker.present", False):
        return "absent"
    detail = str(_get(caps, "docker.detail", "") or "").lower()
    return "running" if "running" in detail and "not running" not in detail else "installed"


def _caps_mapping(caps: Any) -> Mapping:
    """A caps mapping, or the same shape built from a ``capabilities.Capabilities`` object.

    ``capabilities.to_context`` carries only present/version/path, so ``detail`` (needed for
    ``profile.docker_state``) and ``nvm_versions`` are only available from the object itself.
    """
    if caps is None:
        return {}
    if isinstance(caps, Mapping):
        return caps
    items = getattr(caps, "items", None)
    if not isinstance(items, Mapping):
        raise TypeError("caps_context must be a mapping or a Capabilities object")
    out: Dict[str, Any] = {
        str(name): {"present": bool(getattr(cap, "present", False)), "version": getattr(cap, "version", None),
                    "path": getattr(cap, "path", None), "detail": str(getattr(cap, "detail", "") or "")}
        for name, cap in items.items()}
    nvm_versions = getattr(caps, "nvm_versions", None)
    if nvm_versions:
        out["nvm_versions"] = tuple(str(v) for v in nvm_versions)
    return out


def _normalise_caps(caps: Mapping) -> Dict[str, Any]:
    """Every probe entry gets present/version/path/detail so templates never hit a gap."""
    out: Dict[str, Any] = {}
    for name, entry in caps.items():
        if isinstance(entry, Mapping):
            out[str(name)] = {"present": False, "version": None, "path": None, "detail": "",
                              **{str(k): v for k, v in entry.items()}}
        else:
            out[str(name)] = entry
    return out


def _profile_tools(config: Mapping, caps: Mapping) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    for tool in _TOOL_KEYS:
        profile[tool] = resolve_tool(_get(config, "tools." + tool, "auto"), _get(caps, tool + ".present", False))
    for name in _PRESENT_KEYS:
        profile[name] = bool(_get(caps, name + ".present", False))
    review = str(_get(config, "review.adversarial", "auto") or "auto").lower()
    profile["review_backend"] = review if review in ("codex", "claude") else ("codex" if profile["codex"] else "claude")
    vaults = tuple(str(v) for v in (_get(config, "paths.obsidian_vaults", ()) or ()))
    profile["vaults"] = vaults
    profile["default_vault"] = vaults[0] if vaults else ""
    profile["node_version"] = str(_get(caps, "node.version", "") or "")
    profile["nvm_versions"] = _nvm_versions(caps)
    profile["docker_state"] = _docker_state(caps)
    return profile


def _profile_settings(config: Mapping, paths: Optional[Paths]) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    for tool, defaults in _MODEL_DEFAULTS.items():
        for tier, default in zip(_TIERS, defaults):
            profile[f"{tool}_{tier}"] = str(_get(config, f"subagents.{tool}.{tier}", default))
    profile["codex_model"] = str(_get(config, "subagents.codex.model", "gpt-5.6-sol"))
    try:
        budget = int(_get(config, "guardrails.context_budget_tokens", 100000))
    except (TypeError, ValueError):
        budget = 100000
    profile["context_budget"] = budget
    profile["context_budget_k"] = short_count(budget)
    claude_home = paths.claude_home if paths else "~/.claude"
    agents_home = paths.agents_home if paths else "~/.agents"
    profile["sessions_dir"] = str(_get(config, "paths.sessions_dir", "") or os.path.join(claude_home, "sessions"))
    profile["backups_dir"] = str(_get(config, "paths.backups_dir", "") or os.path.join(agents_home, "backups"))
    profile["hook_profile"] = str(_get(config, "guardrails.hook_profile", "standard") or "standard")
    profile["disabled_hooks"] = tuple(str(h) for h in (_get(config, "guardrails.disabled_hooks", ()) or ()))
    return profile


def build_context(config_data: Mapping, caps_context: Mapping, paths: Optional[Paths],
                  env: Optional[Mapping[str, str]] = None) -> Mapping:
    """Template context from ``Config.data`` and the probe result.

    ``caps_context`` is a plain mapping (``capabilities.to_context()``) or, to get a real
    ``profile.docker_state`` and the full ``profile.nvm_versions``, the ``Capabilities`` object.

    Keys: ``config.*`` (as given), ``caps.<name>.present/version/path/detail``, ``profile.*``
    (every key listed in ARCHITECTURE.md) and ``env.HOME`` / ``env.USER`` only. Missing config
    keys fall back to the documented defaults; the result is deep-frozen (read-only mappings,
    tuples) so templates can never mutate it.
    """
    env = os.environ if env is None else env
    config = config_data or {}
    caps = _caps_mapping(caps_context)
    profile = _profile_tools(config, caps)
    profile.update(_profile_settings(config, paths))
    env_ctx = {"HOME": env.get("HOME") or os.path.expanduser("~"),
               "USER": env.get("USER") or env.get("LOGNAME") or ""}
    return _freeze({"config": config, "caps": _normalise_caps(caps), "profile": profile, "env": env_ctx})


# ------------------------------------------------------------------ tag tokenizer

def _tokenize(text: str, source: str, line_map: Sequence[int]) -> List[BlockToken]:
    """Split into ("text"|"var"|"block", value, original line) tokens."""
    def line_at(offset: int) -> int:
        index = text.count("\n", 0, offset)
        return line_map[index] if index < len(line_map) else (line_map[-1] if line_map else 1)

    def literal(start: int, end: int) -> List[BlockToken]:
        chunk = text[start:end]
        opener = _TAG_OPEN_RE.search(chunk)
        if opener is not None:
            raise RenderError(f"{source}:{line_at(start + opener.start())}: unterminated {opener.group()!r}")
        return [("text", chunk, line_at(start))] if chunk else []

    tokens: List[BlockToken] = []
    pos = 0
    for match in _TAG_RE.finditer(text):
        tokens.extend(literal(pos, match.start()))
        pos = match.end()
        if match.group("alone") is not None:
            tokens.append(("block", match.group("a").strip(), line_at(match.start())))
        elif match.group("b") is not None:
            tokens.append(("block", match.group("b").strip(), line_at(match.start())))
        else:
            tokens.append(("var", match.group("v").strip(), line_at(match.start())))
    tokens.extend(literal(pos, len(text)))
    return tokens


# ------------------------------------------------------------------ renderer

def _iterable(value: Any) -> Sequence:
    if isinstance(value, Mapping):
        return tuple(value.keys())
    if isinstance(value, (list, tuple)):
        return value
    return (value,) if value else ()


class _Renderer:
    def __init__(self, evaluator: Evaluator) -> None:
        self.ev = evaluator

    def render(self, nodes: Sequence[Tuple], out: List[str], scopes: Tuple[Mapping, ...]) -> None:
        for node in nodes:
            kind = node[0]
            if kind == "text":
                out.append(node[1])
            elif kind == "var":
                out.append(self.ev.text(node[1], node[2], scopes))
            elif kind == "if":
                self.render_if(node, out, scopes)
            else:
                self.render_for(node, out, scopes)

    def render_if(self, node: Tuple, out: List[str], scopes: Tuple[Mapping, ...]) -> None:
        for condition, body, line in node[1]:
            if condition is None or self.ev.evaluate(condition, line, scopes):
                self.render(body, out, scopes)
                return

    def render_for(self, node: Tuple, out: List[str], scopes: Tuple[Mapping, ...]) -> None:
        _, name, expression, body, line = node
        items = _iterable(self.ev.evaluate(expression, line, scopes))
        for position, item in enumerate(items):
            loop = {"index": position + 1, "index0": position, "first": position == 0,
                    "last": position == len(items) - 1, "length": len(items)}
            self.render(body, out, scopes + ({name: item, "loop": loop},))


def render_text(text: str, context: Mapping, source: str = "<text>") -> Tuple[str, Tuple[str, ...]]:
    """Render a template. Returns ``(output, warnings)``; raises ``RenderError`` on bad syntax."""
    body, line_map = _strip_markers(text, template=True)
    nodes = parse_blocks(_tokenize(body, source, line_map), source)
    evaluator = Evaluator(context, source)
    out: List[str] = []
    _Renderer(evaluator).render(nodes, out, ())
    return "".join(out), tuple(evaluator.warnings)


# ------------------------------------------------------------------ trees

def _default_rewrite() -> RewriteFn:
    """``installer.core.rewrite.rewrite``, imported lazily; any failure is a ``RenderError``."""
    try:
        module = importlib.import_module("installer.core.rewrite")
    except ImportError as error:
        raise RenderError(f"installer.core.rewrite cannot be imported: {error}") from error
    function = getattr(module, "rewrite", None)
    if not callable(function):
        raise RenderError("installer.core.rewrite has no callable 'rewrite'")
    return function


def _requires_reason(names: Sequence[str], mode: str) -> str:
    return f"requires {'any of ' if mode == 'any' else ''}{' '.join(names)}"


def _join(rel: str, name: str) -> str:
    return f"{rel}/{name}" if rel else name


def _dir_requirement(src: str, rel: str) -> Tuple[Tuple[str, ...], str]:
    """Requirement of directory ``src`` (shown as ``rel`` in errors) from its ``.installer-requires``."""
    marker = os.path.join(src, REQUIRES_FILE)
    if not os.path.isfile(marker):
        return (), "all"
    with open(marker, "r", encoding="utf-8", errors="replace") as handle:
        return _parse_requires_file(handle.read(), _join(rel, REQUIRES_FILE))


def _is_within(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` or lies under it (both already real paths)."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _is_inside_tree(path: str, root: str) -> bool:
    """True when ``path`` (which may not exist yet) is ``root`` or lies beneath it.

    Compares by file identity, not spelling, so a case-insensitive filesystem or a symlinked
    parent cannot hide the nesting.
    """
    current = os.path.realpath(path)
    root_stat = os.stat(root)
    while True:
        if os.path.exists(current) and os.path.samestat(os.stat(current), root_stat):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


class _TreeWalker:
    def __init__(self, context: Mapping, rewrite_fn: RewriteFn, root: str = "") -> None:
        self.context, self.rewrite_fn = context, rewrite_fn
        self.root = os.path.realpath(root) if root else ""
        self.rendered: List[str] = []
        self.copied: List[str] = []
        self.excluded: List[Tuple[str, str]] = []
        self.warnings: List[str] = []

    def walk(self, src: str, dst: str, rel: str) -> None:
        """Mirror the children of ``src`` (already created as ``dst``)."""
        with os.scandir(src) as entries:
            children = sorted(entries, key=lambda e: e.name)
        for entry in children:
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            child_dst = os.path.join(dst, entry.name)
            if entry.name == REQUIRES_FILE:
                continue
            if entry.is_symlink():
                self.symlink(entry.path, child_dst, child_rel)
            elif entry.is_dir():
                self.directory(entry.path, child_dst, child_rel)
            elif entry.name in IGNORED_FILE_NAMES:
                continue
            elif entry.is_file():
                self.file(entry.path, child_dst, child_rel)
            else:
                self.excluded.append((child_rel, "not a regular file"))

    def symlink(self, src: str, dst: str, rel: str) -> None:
        """A symlinked directory is recreated as a link, never followed. A symlinked file is
        processed through its target like a regular file when that target lies inside the
        source tree; a broken link, a non-regular target or an outside target is excluded."""
        if os.path.basename(src) in IGNORED_FILE_NAMES or os.path.basename(src) in IGNORED_DIR_NAMES:
            return
        resolved = os.path.realpath(src)
        inside = bool(self.root) and _is_within(resolved, self.root)
        is_dir = os.path.isdir(resolved)
        if not is_dir and not os.path.isfile(resolved):
            self.excluded.append((rel, "broken or non-regular symlink"))
            return
        if not is_dir and not inside:
            self.excluded.append((rel, "symlink target is outside the source tree"))
            return
        if inside:
            reason = self.unmet_above(resolved if is_dir else os.path.dirname(resolved))
            if reason:
                self.excluded.append((rel, reason))
                return
        if is_dir:
            os.symlink(os.readlink(src), dst)
            self.copied.append(rel)
        else:
            self.file(src, dst, rel)

    def unmet_above(self, directory: str) -> str:
        """Reason string for the first unmet ``.installer-requires`` from ``directory`` up to the root."""
        while _is_within(directory, self.root):
            where = os.path.relpath(directory, self.root).replace(os.sep, "/")
            names, mode = _dir_requirement(directory, "" if where == "." else where)
            if not requirements_met(names, mode, self.context):
                return _requires_reason(names, mode)
            if directory == self.root:
                break
            directory = os.path.dirname(directory)
        return ""

    def directory(self, src: str, dst: str, rel: str) -> None:
        if os.path.basename(src) in IGNORED_DIR_NAMES:
            return
        names, mode = _dir_requirement(src, rel)
        if not requirements_met(names, mode, self.context):
            self.excluded.append((rel, _requires_reason(names, mode)))
            return
        os.makedirs(dst)
        self.walk(src, dst, rel)
        shutil.copymode(src, dst)

    def file(self, src: str, dst: str, rel: str) -> None:
        with open(src, "rb") as handle:
            data = handle.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            self.write(src, dst, data)
            self.copied.append(rel)
            return
        names, mode = _requires_of(text, rel)
        if not requirements_met(names, mode, self.context):
            self.excluded.append((rel, _requires_reason(names, mode)))
            return
        if is_template(text) or rel in ALWAYS_TEMPLATE:
            text, warnings = render_text(text, self.context, rel)
            self.warnings.extend(warnings)
            self.rendered.append(rel)
        else:
            text = _strip_markers(text, template=False)[0]
            self.copied.append(rel)
        self.write(src, dst, self.rewrite_fn(rel, text, self.context).encode("utf-8"))

    @staticmethod
    def write(src: str, dst: str, data: bytes) -> None:
        with open(dst, "wb") as handle:
            handle.write(data)
        shutil.copymode(src, dst)


def render_tree(src_dir: str, out_dir: str, context: Mapping, rel_prefix: str,
                rewrite_fn: Optional[RewriteFn] = None) -> RenderReport:
    """Mirror ``src_dir`` under ``out_dir`` (created here; it must not already exist).

    Each regular file is read as bytes. UTF-8 text goes through (1) the requires check,
    (2) template rendering when ``is_template`` or ``rel_path in ALWAYS_TEMPLATE``, and
    (3) ``rewrite_fn(rel_path, text, context)``; anything else (binary) is copied verbatim.
    ``rel_path`` is ``rel_prefix + "/" + path-within-src`` (POSIX). Mode bits are preserved,
    symlinks (including symlinked directories) are recreated as symlinks and never followed,
    ``IGNORED_FILE_NAMES`` / ``IGNORED_DIR_NAMES`` entries are skipped silently, and
    ``.installer-requires`` files are never copied. A file or directory whose requirement is
    unmet is left out and listed in ``excluded`` as ``(rel_path, reason)``.

    ``rewrite_fn=None`` means: import ``installer.core.rewrite`` lazily and use its
    ``rewrite``; when that import fails ``RenderError`` is raised (the step is never silently
    skipped). Tests pass an explicit identity or a recording stub.

    ``out_dir`` must not lie inside ``src_dir`` (the walk would recurse into its own output);
    that raises ``RenderError`` before anything is created. Entries named in the ignore lists
    are skipped even when they are symlinks. A symlinked file is processed through its target
    (requires check, template, rewrite) when the target is a regular file inside ``src_dir``,
    and otherwise listed in ``excluded``. A malformed ``installer:requires`` marker or
    ``.installer-requires`` file raises ``RenderError`` rather than disabling the gate.
    """
    if not os.path.isdir(src_dir):
        raise RenderError(f"{src_dir}: not a directory")
    if os.path.lexists(out_dir):
        raise RenderError(f"{out_dir}: already exists")
    if _is_inside_tree(out_dir, src_dir):
        raise RenderError(f"{out_dir}: output directory lies inside the source directory {src_dir}")
    walker = _TreeWalker(context, rewrite_fn or _default_rewrite(), src_dir)
    names, mode = _dir_requirement(src_dir, rel_prefix)
    os.makedirs(out_dir)
    if requirements_met(names, mode, context):
        walker.walk(src_dir, out_dir, rel_prefix)
        shutil.copymode(src_dir, out_dir)
    else:
        walker.excluded.append((rel_prefix or ".", _requires_reason(names, mode)))
    return RenderReport(tuple(walker.rendered), tuple(walker.copied),
                        tuple(walker.excluded), tuple(walker.warnings))
