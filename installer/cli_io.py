"""Output, prompting and plan-execution helpers shared by the CLI command modules.

Nothing here knows about a particular command. Text goes to ``sys.stdout`` /
``sys.stderr`` looked up at call time, so tests can redirect them.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from installer.core import actions
from installer.core.paths import Paths
from installer.core.types import Operation, OpResult

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_EXCLUDED = 3

TRUE_ANSWERS = ("y", "yes")
MAX_TEXT_BYTES = 2 * 1024 * 1024


class CliError(Exception):
    """A user-facing failure: the message goes to stderr, `code` becomes the exit status."""

    def __init__(self, message: str, code: int = EXIT_FAIL) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def usage_error(message: str) -> CliError:
    return CliError(message, EXIT_USAGE)


def failure(message: str) -> CliError:
    return CliError(message, EXIT_FAIL)


@dataclass(frozen=True)
class Ctx:
    """What every command receives: parsed arguments, resolved paths and the env in use."""

    args: argparse.Namespace
    paths: Paths
    env: Mapping[str, str]

    def flag(self, name: str, default: Any = False) -> Any:
        return getattr(self.args, name, default)


# ------------------------------------------------------------------ output


def emit(text: str = "") -> None:
    print(text)


def warn(text: str) -> None:
    print(text, file=sys.stderr)


# Each glyph is (unicode, ascii). Escapes keep this source file pure ASCII.
_GLYPHS = {
    "installed": ("✓", "+"),
    "not-installed": ("·", "-"),
    "modified": ("≠", "~"),
    "foreign": ("?", "?"),
    "ignored": ("○", "o"),
    "remote": ("↑", "^"),
    "problem": ("!", "!"),
    "ok": ("✓", "+"),
    "bad": ("✗", "x"),
    "unknown": ("?", "?"),
    "na": ("-", "-"),
}


def use_unicode() -> bool:
    """True when stdout can show the unicode glyphs (UTF-8 encoding, INSTALLER_ASCII unset)."""
    if os.environ.get("INSTALLER_ASCII") == "1":
        return False
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "").replace("_", "")
    return encoding.startswith("utf")


def glyph(name: str) -> str:
    pair = _GLYPHS.get(name, ("?", "?"))
    return pair[0] if use_unicode() else pair[1]


def truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    """Aligned plain-text table lines (header first); trailing spaces are stripped."""
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: Sequence[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()

    return [line(headers)] + [line(row) for row in rows]


def print_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    for line in format_table(headers, rows):
        emit(line)


# -------------------------------------------------------------------- json


def to_jsonable(value: Any) -> Any:
    """Plain JSON data for dataclasses (like dataclasses.asdict), Enums (as their value),
    read-only mappings and tuples. Unlike asdict this copes with ``MappingProxyType`` fields."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def dump_json(value: Any) -> None:
    emit(json.dumps(to_jsonable(value), indent=2, ensure_ascii=False))


# ------------------------------------------------------------------ prompts


def confirm(args: argparse.Namespace, prompt: str = "Proceed?") -> bool:
    """Ask `<prompt> [y/N]`. ``--yes`` answers for the user; no TTY and no --yes is a usage error."""
    if getattr(args, "yes", False):
        return True
    if not sys.stdin.isatty():
        raise usage_error("not running in a terminal; re-run with --yes to confirm, "
                          "or --dry-run to only see the plan")
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        answer = ""
    return answer.strip().lower() in TRUE_ANSWERS


# ------------------------------------------------------------ plan execution


def _uses_backup(ops: Sequence[Operation], backup_root: str) -> bool:
    return any(op.dst.startswith(backup_root) for op in ops)


def _result_line(result: OpResult, paths: Paths, dry_run: bool) -> str:
    label = "dry " if dry_run else ("ok  " if result.ok else "FAIL")
    text = actions.describe(result.op, paths)
    return f"  {label}  {text}" if result.ok else f"  {label}  {text}: {result.message}"


def print_results(results: Sequence[OpResult], ops: Sequence[Operation], paths: Paths,
                  backup_root: str, dry_run: bool) -> int:
    """One line per applied step, the backup root when it is in use; exit status 1 on a failure."""
    for result in results:
        emit(_result_line(result, paths, dry_run))
    failed = [r for r in results if not r.ok]
    if _uses_backup(ops, backup_root):
        verb = "would go" if dry_run else "went"
        emit(f"Backups {verb} under: {paths.display(backup_root)}")
    if failed:
        skipped = len(ops) - len(results)
        emit(f"{len(failed)} step(s) failed; {skipped} step(s) were not run.")
        return EXIT_FAIL
    emit("Done." if not dry_run else "Dry run only; nothing was changed.")
    return EXIT_OK


def show_plan(ops: Sequence[Operation], paths: Paths) -> None:
    emit(f"Plan ({len(ops)} step(s)):")
    for index, op in enumerate(ops, 1):
        emit(f"  {index}. {actions.describe(op, paths)}")


def run_plan(ctx: Ctx, ops: Tuple[Operation, ...], backup_root: str,
             prompt: str = "Proceed?") -> int:
    """Print the plan, confirm (unless --yes / --dry-run), apply, print results."""
    if not ops:
        emit("Nothing to do.")
        return EXIT_OK
    show_plan(ops, ctx.paths)
    dry_run = bool(ctx.flag("dry_run"))
    if not dry_run and not confirm(ctx.args, prompt):
        emit("Aborted.")
        return EXIT_FAIL
    results = actions.apply(ops, dry_run=dry_run)
    return print_results(results, ops, ctx.paths, backup_root, dry_run)


def read_text(path: str, limit: Optional[int] = MAX_TEXT_BYTES) -> str:
    """Decode a file as UTF-8 (errors replaced), at most `limit` bytes."""
    with open(path, "rb") as handle:
        data = handle.read() if limit is None else handle.read(limit)
    return data.decode("utf-8", errors="replace")
