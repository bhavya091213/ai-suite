"""SKILL.md frontmatter parsing.

Pure functions. ``parse_frontmatter`` is total: whatever text it is handed, it
returns a ``SkillMeta`` and never raises. The grammar is the small subset of
YAML that skill frontmatter actually uses (see ARCHITECTURE.md):

* the block sits between a first line ``---`` and the next line ``---``;
* ``key: value`` pairs at column 0; surrounding single/double quotes are
  stripped from values;
* a value of ``>`` / ``|`` (optionally with a chomping indicator) or an empty
  value collects the indented lines that follow, joined with a space (``>``,
  empty) or a newline (``|``), up to the next column-0 line;
* a plain value followed by indented lines folds them in with a space;
* every key is kept verbatim in ``SkillMeta.fields``.
"""

from __future__ import annotations

import os
import re
from types import MappingProxyType
from typing import Dict, List, Optional, Tuple

from installer.core.types import SkillMeta

SKILL_FILE = "SKILL.md"

_DELIMITER = "---"
_KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
_BLOCK_INDICATOR_RE = re.compile(r"^[>|][-+0-9]*$")
_DOUBLE_QUOTE_ESCAPE_RE = re.compile(r'\\(["\\])')


def parse_frontmatter(text: str) -> SkillMeta:
    """Parse the frontmatter block of a SKILL.md text into a ``SkillMeta``.

    Missing, unterminated or otherwise unusable frontmatter yields
    ``SkillMeta(None, None, {})``. Never raises.
    """
    if not isinstance(text, str):
        return _empty_meta()
    block = _frontmatter_lines(text)
    if block is None:
        return _empty_meta()
    fields = _parse_block(block)
    return SkillMeta(
        name=fields.get("name") or None,
        description=fields.get("description") or None,
        fields=MappingProxyType(dict(fields)),
    )


def read_meta(skill_dir: str) -> Optional[SkillMeta]:
    """Parse ``<skill_dir>/SKILL.md``; ``None`` when it is missing or unreadable."""
    path = os.path.join(skill_dir, SKILL_FILE)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except (OSError, ValueError):
        return None
    return parse_frontmatter(text)


# ------------------------------------------------------------------ internals


def _empty_meta() -> SkillMeta:
    return SkillMeta(None, None, MappingProxyType({}))


def _frontmatter_lines(text: str) -> Optional[List[str]]:
    """The lines strictly between the opening and closing ``---``, or None."""
    lines = text.lstrip("﻿").splitlines()
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].rstrip() != _DELIMITER:
        return None
    for end in range(start + 1, len(lines)):
        if lines[end].rstrip() == _DELIMITER:
            return lines[start + 1:end]
    return None


def _parse_block(lines: List[str]) -> Dict[str, str]:
    """Collect ``key: value`` pairs; non-key column-0 lines are skipped."""
    fields: Dict[str, str] = {}
    index = 0
    while index < len(lines):
        match = _KEY_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        key = match.group(1)
        first = (match.group(2) or "").strip()
        value, index = _collect_value(lines, index + 1, first)
        fields[key] = value
    return fields


def _is_continuation(line: str) -> bool:
    return not line.strip() or line[0] in " \t"


def _collect_value(lines: List[str], start: int, first: str) -> Tuple[str, int]:
    """Build one value from its first-line text plus any indented continuation.

    Returns the value and the index of the first line not consumed.
    """
    index = start
    continuation: List[str] = []
    while index < len(lines) and _is_continuation(lines[index]):
        continuation.append(lines[index])
        index += 1
    if _BLOCK_INDICATOR_RE.match(first):
        if first.startswith("|"):
            return "\n".join(_dedent(continuation)), index
        return _fold(continuation), index
    if not first:
        return _unquote(_fold(continuation)), index
    folded = " ".join([first] + [line.strip() for line in continuation if line.strip()])
    return _unquote(folded), index


def _fold(lines: List[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def _dedent(lines: List[str]) -> List[str]:
    """Strip the common indent of a literal block; drop leading/trailing blanks."""
    non_blank = [line for line in lines if line.strip()]
    if not non_blank:
        return []
    indent = min(len(line) - len(line.lstrip(" \t")) for line in non_blank)
    out = [line[indent:].rstrip() if line.strip() else "" for line in lines]
    while out and not out[0]:
        out = out[1:]
    while out and not out[-1]:
        out = out[:-1]
    return out


def _unquote(value: str) -> str:
    """Strip one layer of matching surrounding quotes, undoing simple escapes."""
    if len(value) < 2 or value[0] != value[-1] or value[0] not in "\"'":
        return value
    inner = value[1:-1]
    if value[0] == '"':
        return _DOUBLE_QUOTE_ESCAPE_RE.sub(r"\1", inner)
    return inner.replace("''", "'")
