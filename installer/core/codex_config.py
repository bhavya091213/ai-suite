"""Text-level edits to ``~/.codex/config.toml``.

TOML has no round-tripping writer in the standard library, so these helpers
edit lines in place and keep every other byte (comments, ordering, blank
lines, line endings) exactly as they were. It is the same philosophy as
``shared/bin/sync-agents``.

* ``patch_agents`` edits or inserts ``max_threads`` / ``max_depth`` inside the
  ``[agents]`` table only (``[agents.<role>]`` sub-tables are never touched).
* ``patch_model`` edits the first top-level ``model = "..."`` assignment.
* ``check`` parses the text with ``tomllib`` when the interpreter has it.

A table ends at the next line that starts a statement and whose first
non-blank character is ``[``. "Starts a statement" means the line does not
begin inside a multi-line string (basic or literal), a multi-line array or an
inline table, so ``[link](x)`` lines in ``developer_instructions`` and nested
arrays such as ``[1, 2],`` are never mistaken for table headers. Key lines are
only edited at statement starts for the same reason. When the text ends inside
an unterminated string or bracket the patchers raise ``ValueError`` instead of
guessing, because any edit there could corrupt the file.

Callers back the file up before writing the result back.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")
_AGENTS_HEADER_RE = re.compile(r"^[ \t]*\[[ \t]*agents[ \t]*\][ \t]*(?:#.*)?$")
_MODEL_RE = re.compile(
    r"""^(?P<lead>[ \t]*model[ \t]*=[ \t]*)(?:"(?:[^"\\]|\\.)*"|'[^']*')(?P<tail>[ \t]*(?:#.*)?)$"""
)
_MODEL_KEY_RE = re.compile(r"^[ \t]*model[ \t]*=")
_COMMENT_RE = re.compile(r"^[ \t]*(?:#.*)?$")  # blank or comment-only


def _lines(text: str) -> List[str]:
    """Split into lines that each keep their own terminator (the last may have none)."""
    return _LINE_RE.findall(text)


def _content(line: str) -> str:
    """The line without its terminator (``\\n`` or ``\\r\\n``)."""
    return line.rstrip("\r\n")


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _find_close(text: str, start: int, delimiter: str) -> int:
    """Index just past the closing ``delimiter`` of a multi-line string, or -1 when the line has none."""
    quote = delimiter[0]
    index, size = start, len(text)
    while index < size:
        if quote == '"' and text[index] == "\\":
            index += 2  # escaped character (a trailing backslash continues the string)
        elif text.startswith(delimiter, index):
            end = index + 3
            while end < size and end < index + 5 and text[end] == quote:
                end += 1  # up to two quote characters directly before the closer belong to the string
            return end
        else:
            index += 1
    return -1


def _skip_string(text: str, start: int) -> int:
    """Index just past the single-line string that opens at ``start`` (end of line when unterminated)."""
    quote = text[start]
    index, size = start + 1, len(text)
    while index < size:
        if quote == '"' and text[index] == "\\":
            index += 2
        elif text[index] == quote:
            return index + 1
        else:
            index += 1
    return size


def _advance(text: str, mode: Optional[str], depth: int) -> Tuple[Optional[str], int]:
    """Scan one line (terminator stripped) from state ``(mode, depth)`` and return the state after it.

    ``mode`` is the open multi-line string delimiter or None; ``depth`` counts open
    ``[`` / ``{`` brackets. Strings and comments are skipped, so brackets inside them
    are ignored.
    """
    index, size = 0, len(text)
    while index < size:
        if mode is not None:
            end = _find_close(text, index, mode)
            if end < 0:
                return mode, depth  # the string runs on into the next line
            mode, index = None, end
            continue
        char = text[index]
        if char == "#":
            break
        if text.startswith('"""', index) or text.startswith("'''", index):
            mode, index = text[index:index + 3], index + 3
        elif char in "\"'":
            index = _skip_string(text, index)
        else:
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth = max(0, depth - 1)
            index += 1
    return mode, depth


def _statement_starts(lines: List[str]) -> List[bool]:
    """Per line: True when it begins outside any multi-line string, array or inline table.

    Raises ``ValueError`` when the text ends inside an unterminated string or bracket,
    because a line-based edit of such a file cannot be trusted.
    """
    starts: List[bool] = []
    mode: Optional[str] = None
    depth = 0
    for line in lines:
        starts.append(mode is None and depth == 0)
        mode, depth = _advance(_content(line), mode, depth)
    if mode is not None or depth > 0:
        raise ValueError(
            "config text ends inside an unterminated multi-line string or array; fix it by hand first"
        )
    return starts


def _is_header(line: str, starts: bool) -> bool:
    """A table header: a statement-start line whose first non-blank character is ``[``."""
    return starts and line.lstrip().startswith("[")


def _check_count(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("%s must be a non-negative integer, got %r" % (name, value))


def _value_re(key: str) -> "re.Pattern[str]":
    return re.compile(
        r"^(?P<lead>[ \t]*%s[ \t]*=[ \t]*)(?P<val>[^#]*?)(?P<tail>[ \t]*(?:#.*)?)$" % re.escape(key)
    )


def _replace(lines: List[str], index: int, new_content: str) -> List[str]:
    """New list with line ``index`` swapped for ``new_content``, terminator kept."""
    ending = lines[index][len(_content(lines[index])):]
    return lines[:index] + [new_content + ending] + lines[index + 1:]


def _insert_after(lines: List[str], at: int, new_content: str, eol: str) -> List[str]:
    """New list with ``new_content`` inserted before index ``at`` (a missing final newline is repaired)."""
    before = list(lines[:at])
    if before and not before[-1].endswith("\n"):
        before[-1] += eol
    return before + [new_content + eol] + lines[at:]


def _agents_span(lines: List[str], starts: List[bool]) -> Optional[Tuple[int, int]]:
    """(header index, end index exclusive) of the first ``[agents]`` table, or None."""
    for index, line in enumerate(lines):
        if starts[index] and _AGENTS_HEADER_RE.match(_content(line)):
            end = index + 1
            while end < len(lines) and not _is_header(lines[end], starts[end]):
                end += 1
            return index, end
    return None


def _last_assignment(lines: List[str], start: int, end: int) -> int:
    """Index of the last non-blank, non-comment line in lines[start:end]; ``start - 1`` when none."""
    for index in range(end - 1, start - 1, -1):
        if not _COMMENT_RE.match(_content(lines[index])):
            return index
    return start - 1


def _set_agents_key(
    lines: List[str], span: Tuple[int, int], starts: List[bool], key: str, value: int, eol: str
) -> List[str]:
    header, end = span
    pattern = _value_re(key)
    for index in range(header + 1, end):
        match = pattern.match(_content(lines[index])) if starts[index] else None
        if match:
            return _replace(lines, index, "%s%d%s" % (match.group("lead"), value, match.group("tail")))
    at = _last_assignment(lines, header + 1, end) + 1
    return _insert_after(lines, at, "%s = %d" % (key, value), eol)


def _append_agents_table(text: str, max_threads: int, max_depth: int) -> str:
    eol = _eol(text)
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += eol
    if prefix:
        prefix += eol  # blank separator line
    return "%s[agents]%smax_threads = %d%smax_depth = %d%s" % (prefix, eol, max_threads, eol, max_depth, eol)


def patch_agents(text: str, max_threads: int, max_depth: int) -> str:
    """Set ``max_threads`` / ``max_depth`` in the ``[agents]`` table.

    Existing values are replaced in place (trailing comments kept); missing
    keys are inserted after the table's last assignment; a missing table is
    appended at the end of the file. Only the ``[agents]`` header matches,
    never ``[agents.<role>]``. Raises ``ValueError`` for a non-integer or
    negative count, and when ``text`` ends inside an unterminated multi-line
    string or array.
    """
    _check_count("max_threads", max_threads)
    _check_count("max_depth", max_depth)
    lines = _lines(text)
    starts = _statement_starts(lines)
    if _agents_span(lines, starts) is None:
        return _append_agents_table(text, max_threads, max_depth)
    eol = _eol(text)
    for key, value in (("max_threads", max_threads), ("max_depth", max_depth)):
        starts = _statement_starts(lines)  # line indexes shift after an insert
        lines = _set_agents_key(lines, _agents_span(lines, starts), starts, key, value, eol)  # type: ignore[arg-type]
    return "".join(lines)


def patch_model(text: str, model: str) -> str:
    """Set the first top-level ``model = "..."`` line to ``model``.

    Only lines before the first ``[table]`` header are considered, so a
    ``model`` key inside a table and a commented-out ``# model = ...`` are
    never touched. When there is no top-level ``model`` line one is inserted
    after the last top-level assignment (at the top of the file when there is
    none). Raises ``ValueError`` for an empty model name, when the existing
    top-level ``model`` is not a single-line string, and when ``text`` ends
    inside an unterminated multi-line string or array.
    """
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string")
    literal = json.dumps(model, ensure_ascii=False)
    lines = _lines(text)
    starts = _statement_starts(lines)
    top = next((i for i, line in enumerate(lines) if _is_header(line, starts[i])), len(lines))
    for index in range(top):
        if not starts[index]:
            continue
        content = _content(lines[index])
        match = _MODEL_RE.match(content)
        if match:
            return "".join(_replace(lines, index, "%s%s%s" % (match.group("lead"), literal, match.group("tail"))))
        if _MODEL_KEY_RE.match(content):
            raise ValueError("top-level model is not a single-line string; edit it by hand")
    at = _last_assignment(lines, 0, top) + 1
    new_lines = _insert_after(lines, at, "model = %s" % literal, _eol(text))
    if at == 0 and lines:
        new_lines = new_lines[:1] + [_eol(text)] + new_lines[1:]  # blank line below a leading comment block
    return "".join(new_lines)


def check(text: str) -> Optional[str]:
    """TOML parse error message, or None when it parses or ``tomllib`` is unavailable."""
    try:
        import tomllib  # Python 3.11+; imported lazily so 3.9/3.10 still load this module
    except ImportError:
        return None
    try:
        tomllib.loads(text)
    except ValueError as exc:  # tomllib.TOMLDecodeError subclasses ValueError
        return str(exc)
    return None
