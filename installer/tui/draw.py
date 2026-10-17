"""curses drawing helpers shared by every screen.

This is the only module that calls curses drawing primitives; screens and the
App go through the helpers below (ARCHITECTURE.md Part 4). Nothing here raises
for a bad coordinate or a small window: output is clipped and curses errors are
swallowed, so a screen can always draw "as if the window were big enough".

The pure parts (glyph selection, line editing, scroll maths, header fitting) are
separate functions so tests can exercise them without a terminal.
"""

from __future__ import annotations

import curses
import locale
import os
import time
from typing import Mapping, Optional, Sequence, Tuple, Union

from installer.tui.base import TABS

MIN_ROWS = 24
MIN_COLS = 80

# A blocking read that returns nothing means the input is gone (stdin at EOF, terminal
# closed), not "no key yet". Pause briefly per empty read so it never spins the CPU, and
# give up after this many in a row (a stray interrupted read still recovers).
EMPTY_READ_PAUSE = 0.01
EMPTY_READ_LIMIT = 20

# A drawable line is plain text or (text, curses attribute).
Line = Union[str, Tuple[str, int]]
# A coloured fragment: (text, attr name understood by attr()).
Segment = Tuple[str, str]

# ------------------------------------------------------------------- glyphs

_UNICODE_GLYPHS: Mapping[str, str] = {
    "installed": "✓", "missing": "·", "modified": "≠", "foreign": "?",
    "remote": "↑", "problem": "!", "selected": "■", "unselected": "□",
    "yes": "✓", "no": "✗", "unknown": "?", "ellipsis": "…",
    "bullet": "•", "arrow": "→",
}
_ASCII_GLYPHS: Mapping[str, str] = {
    "installed": "+", "missing": "-", "modified": "~", "foreign": "?",
    "remote": "^", "problem": "!", "selected": "x", "unselected": " ",
    "yes": "+", "no": "x", "unknown": "?", "ellipsis": "...",
    "bullet": "*", "arrow": ">",
}


def _locale_encoding() -> str:
    try:
        return locale.getpreferredencoding(False) or ""
    except Exception:  # noqa: BLE001 - a broken locale just means ASCII
        return ""


def use_unicode(env: Optional[Mapping[str, str]] = None, encoding: Optional[str] = None) -> bool:
    """True when the locale encoding is UTF-8 and INSTALLER_ASCII is not 1."""
    env = os.environ if env is None else env
    if str(env.get("INSTALLER_ASCII", "")).strip() == "1":
        return False
    name = _locale_encoding() if encoding is None else encoding
    return name.lower().replace("-", "").replace("_", "") == "utf8"


def glyph(name: str, unicode_ok: Optional[bool] = None) -> str:
    """Symbol for `name` (KeyError when unknown). `unicode_ok` overrides detection."""
    unicode_ok = use_unicode() if unicode_ok is None else unicode_ok
    return (_UNICODE_GLYPHS if unicode_ok else _ASCII_GLYPHS)[name]


# ------------------------------------------------------------------- colours

_COLOR_PAIRS: Mapping[str, int] = {"title": 1, "ok": 2, "warn": 3, "error": 4, "selected": 5, "dim": 6}
_STATE = {"colors": False}  # set once by init_colors()


def _plain_attrs() -> Mapping[str, int]:
    return {
        "title": curses.A_BOLD, "ok": 0, "warn": curses.A_BOLD,
        "error": curses.A_BOLD | curses.A_UNDERLINE, "selected": curses.A_REVERSE,
        "dim": curses.A_DIM, "normal": 0,
    }


def init_colors() -> None:
    """Set up the six colour pairs; without colour support attr() falls back to bold/reverse."""
    _STATE["colors"] = False
    try:
        if not curses.has_colors():
            return
        curses.start_color()
        try:
            curses.use_default_colors()
            fg, bg = -1, -1
        except curses.error:
            fg, bg = curses.COLOR_WHITE, curses.COLOR_BLACK
        pairs = ((1, curses.COLOR_CYAN, bg), (2, curses.COLOR_GREEN, bg),
                 (3, curses.COLOR_YELLOW, bg), (4, curses.COLOR_RED, bg),
                 (5, fg, bg), (6, fg, bg))
        for number, foreground, background in pairs:
            curses.init_pair(number, foreground, background)
    except curses.error:
        return
    _STATE["colors"] = True


def attr(name: str) -> int:
    """Curses attribute for "title"|"ok"|"warn"|"error"|"selected"|"dim"|"normal" (0 if unknown)."""
    if not _STATE["colors"]:
        return _plain_attrs().get(name, 0)
    pair = _COLOR_PAIRS.get(name)
    if pair is None:
        return 0
    extra = {"title": curses.A_BOLD, "error": curses.A_BOLD, "selected": curses.A_REVERSE,
             "dim": curses.A_DIM}.get(name, 0)
    return curses.color_pair(pair) | extra


# ------------------------------------------------------------------ clipping

_CONTROL = {code: " " for code in list(range(32)) + [127]}


def _clean(text: str) -> str:
    return str(text).expandtabs(4).translate(_CONTROL)


def safe_addstr(win, y: int, x: int, text: str, attr: int = 0, width: Optional[int] = None) -> None:
    """addstr that clips to the window (and to `width`) and swallows curses.error."""
    try:
        rows, cols = win.getmaxyx()
    except curses.error:
        return
    if y < 0 or y >= rows or x >= cols:
        return
    text = _clean(text)
    if x < 0:
        text, x = text[-x:], 0
    limit = cols - x if width is None else min(cols - x, width)
    if limit <= 0 or not text:
        return
    try:
        win.addstr(y, x, text[:limit], attr)
    except curses.error:
        pass


def truncate(text: str, width: int) -> str:
    """Cut `text` to `width` columns, ending in an ellipsis when something was removed."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    mark = glyph("ellipsis")
    if width <= len(mark):
        return text[:width]
    return text[:width - len(mark)] + mark


def draw_segments(win, y: int, x: int, segments: Sequence[Segment], width: Optional[int] = None) -> int:
    """Draw (text, attr name) fragments left to right; returns the column after the last one."""
    start = x
    for text, name in segments:
        remaining = None if width is None else width - (x - start)
        if remaining is not None and remaining <= 0:
            break
        safe_addstr(win, y, x, text, attr(name), remaining)
        x += len(_clean(text))
    return x


def wrap_segments(segments: Sequence[Segment], width: int, gap: str = "  ") -> Tuple[Tuple[Segment, ...], ...]:
    """Greedy-wrap fragments into rows no wider than `width` (never splits a fragment)."""
    rows: list = []
    current: list = []
    used = 0
    for text, name in segments:
        needed = len(text) + (len(gap) if current else 0)
        if current and used + needed > width:
            rows.append(tuple(current))
            current, used, needed = [], 0, len(text)
        if current:
            current.append((gap, "normal"))
        current.append((text, name))
        used += needed
    if current:
        rows.append(tuple(current))
    return tuple(rows)


# --------------------------------------------------------------------- frame


def tab_segments(tabs: Sequence[Tuple[int, str]], active: int, width: int) -> Tuple[Tuple[str, bool], ...]:
    """(text, is_active) pieces of the tab bar; falls back to numbers when labels do not fit.

    The number drawn is the key that opens the tab, so the tenth tab (Workflows) shows ``0``.
    """
    full = tuple((f" {number % 10} {label} ", number == active) for number, label in tabs)
    if sum(len(text) for text, _ in full) <= width:
        return full
    return tuple((f" {number % 10} {label} " if number == active else f" {number % 10} ", number == active)
                 for number, label in tabs)


def git_attr(info) -> str:
    if not info.available or info.error:
        return "error"
    if info.behind or info.hint or info.upstream is None:
        return "warn"
    return "ok"


def fit_header(title: str, repo: str, message: str, width: int) -> Tuple[str, str, str]:
    """Shorten repo path (keeping its tail) and git message so title+repo+message fit `width`."""
    left = f" {title} "
    room = width - len(left) - 4
    if room <= 0:
        return truncate(left, width), "", ""
    if len(repo) + len(message) > room:
        repo_room = max(8, room - len(message))
        if len(repo) > repo_room:
            repo = glyph("ellipsis") + repo[len(repo) - repo_room + len(glyph("ellipsis")):]
        message = truncate(message, max(0, room - len(repo)))
    return left, repo, message


def draw_frame(stdscr, app, title: str, footer: str) -> Tuple[int, int, int, int]:
    """Draw title line (repo + git), tab bar and footer; return the body (y0, x0, height, width)."""
    rows, cols = stdscr.getmaxyx()
    left, repo, message = fit_header(title, app.paths.display(app.paths.repo_dir), app.git.message, cols)
    safe_addstr(stdscr, 0, 0, left, attr("title"))
    safe_addstr(stdscr, 0, len(left), repo, attr("dim"))
    if message:
        safe_addstr(stdscr, 0, max(len(left) + len(repo) + 2, cols - len(message) - 1), message,
                    attr(git_attr(app.git)))
    x = 0
    for text, active in tab_segments(getattr(app, "tabs", TABS), app.active_tab, cols):
        safe_addstr(stdscr, 1, x, text, attr("selected") if active else attr("normal"))
        x += len(text)
    shown = app.message or footer
    safe_addstr(stdscr, rows - 1, 0, shown, attr("warn") if app.message else attr("dim"), max(0, cols - 1))
    return 2, 0, max(1, rows - 3), cols


def too_small(stdscr) -> bool:
    """Draw the size notice and return True when the terminal is below 80x24."""
    rows, cols = stdscr.getmaxyx()
    if rows >= MIN_ROWS and cols >= MIN_COLS:
        return False
    stdscr.erase()
    safe_addstr(stdscr, 0, 0, f"terminal too small (need {MIN_COLS}x{MIN_ROWS})")
    return True


# ------------------------------------------------------------- lists and text


def draw_list(win, y0: int, x0: int, height: int, width: int, model, row_fn, focused: bool = True) -> None:
    """Draw the visible rows of a ListModel; the cursor row is highlighted.

    row_fn(item, selected, width) -> (text, attr); `selected` is the multi-selection flag.
    """
    for line, (index, item) in enumerate(model.visible(height)):
        text, row_attr = row_fn(item, model.is_selected(index), width)
        is_cursor = model.offset + line == model.cursor
        if is_cursor:
            row_attr = attr("selected") if focused else row_attr | curses.A_UNDERLINE
        padded = _clean(text)[:width].ljust(width) if is_cursor else text
        safe_addstr(win, y0 + line, x0, padded, row_attr, width)


def draw_text(win, y0: int, x0: int, height: int, width: int, lines: Sequence[Line], top: int,
              left: int = 0) -> None:
    """Draw `lines[top:top+height]`, each cut to columns [left, left+width)."""
    for row in range(max(0, height)):
        index = top + row
        if index < 0 or index >= len(lines):
            continue
        entry = lines[index]
        text, line_attr = (entry, 0) if isinstance(entry, str) else entry
        safe_addstr(win, y0 + row, x0, str(text).expandtabs(4)[left:left + width], line_attr, width)


def clamp_top(top: int, total: int, height: int) -> int:
    """Keep a scroll offset inside [0, total - height]."""
    return max(0, min(top, total - max(1, height)))


def scroll_key(key: int, top: int, total: int, height: int, letters: bool = True) -> Optional[int]:
    """New scroll offset for a scrolling key, None when `key` is not one. `letters` enables j/k/g/G."""
    page = max(1, height - 1)
    moves = {curses.KEY_DOWN: top + 1, curses.KEY_UP: top - 1, curses.KEY_NPAGE: top + page,
             curses.KEY_PPAGE: top - page, curses.KEY_HOME: 0, curses.KEY_END: total, ord(" "): top + page}
    if letters:
        moves.update({ord("j"): top + 1, ord("k"): top - 1, ord("g"): 0, ord("G"): total})
    if key not in moves:
        return None
    return clamp_top(moves[key], total, height)


# --------------------------------------------------------------- line editing


def edit_key(buf: str, pos: int, key: Union[int, str]) -> Tuple[str, int, Optional[str]]:
    """Apply one key to a single-line buffer; returns (buffer, cursor, "enter"|"cancel"|None)."""
    if isinstance(key, int):
        special = {curses.KEY_ENTER: "\n", curses.KEY_BACKSPACE: "\x7f", curses.KEY_DC: "delete",
                   curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right", curses.KEY_HOME: "\x01",
                   curses.KEY_END: "\x05"}
        key = special.get(key, chr(key) if 0 <= key < 128 else "")
    if key in ("\n", "\r"):
        return buf, pos, "enter"
    if key == "\x1b":
        return buf, pos, "cancel"
    if key in ("\x7f", "\b"):
        return (buf[:pos - 1] + buf[pos:], pos - 1, None) if pos > 0 else (buf, pos, None)
    if key == "delete":
        return buf[:pos] + buf[pos + 1:], pos, None
    moves = {"left": max(0, pos - 1), "right": min(len(buf), pos + 1), "\x01": 0, "\x05": len(buf)}
    if key in moves:
        return buf, moves[key], None
    if key == "\x15":
        return buf[pos:], 0, None
    if key == "\x0b":
        return buf[:pos], pos, None
    if isinstance(key, str) and len(key) == 1 and key.isprintable():
        return buf[:pos] + key + buf[pos:], pos + 1, None
    return buf, pos, None


def visible_window(buf: str, pos: int, room: int) -> Tuple[str, int]:
    """Part of `buf` that fits in `room` columns with the cursor visible, and its column."""
    room = max(1, room)
    start = 0 if len(buf) < room else max(0, pos - room + 1)
    return buf[start:start + room], pos - start


def _set_cursor(visibility: int) -> None:
    try:
        curses.curs_set(visibility)
    except curses.error:
        pass


def _next_key(stdscr) -> Union[int, str]:
    try:
        return stdscr.get_wch()
    except AttributeError:
        return stdscr.getch()
    except curses.error:
        return -1


def note_empty_read(count: int) -> Tuple[int, bool]:
    """Account for one empty blocking read: (new consecutive count, True once the input looks gone).

    Sleeps ``EMPTY_READ_PAUSE`` first, so a closed stdin costs ~0 CPU while it is detected.
    """
    time.sleep(EMPTY_READ_PAUSE)
    count += 1
    return count, count >= EMPTY_READ_LIMIT


def read_key(stdscr, poll_ms: int, empty: int) -> Tuple[int, int, bool]:
    """One ``getch()`` with a ``poll_ms`` timeout (-1 blocks): (key, consecutive empty reads, input_gone).

    -1 after the full poll interval is an ordinary timeout. -1 any sooner (or ever, when blocking)
    is a read that failed at once: stdin at EOF or the terminal gone. Those are counted, paused
    and reported as ``input_gone`` after ``EMPTY_READ_LIMIT`` in a row instead of spinning.
    """
    stdscr.timeout(poll_ms)
    started = time.monotonic()
    key = stdscr.getch()
    if key != -1:
        return key, 0, False
    if poll_ms > 0 and time.monotonic() - started >= poll_ms / 2000:
        return -1, 0, False
    empty, gone = note_empty_read(empty)
    return -1, empty, gone


def prompt_line(stdscr, label: str, initial: str = "") -> Optional[str]:
    """Inline single-line editor on the bottom row. Enter returns the text, Esc returns None.

    Also returns None when the input closes under it (stdin at EOF), like Esc.
    """
    buf, pos = initial, len(initial)
    empty = 0
    _set_cursor(1)
    try:
        stdscr.timeout(-1)
        while True:
            rows, cols = stdscr.getmaxyx()
            text, column = visible_window(buf, pos, cols - len(label) - 2)
            safe_addstr(stdscr, rows - 1, 0, " " * max(0, cols - 1))
            safe_addstr(stdscr, rows - 1, 0, label, attr("title"), cols - 1)
            safe_addstr(stdscr, rows - 1, len(label), text, 0, max(0, cols - len(label) - 1))
            try:
                stdscr.move(rows - 1, min(cols - 1, len(label) + column))
            except curses.error:
                pass
            stdscr.refresh()
            key = _next_key(stdscr)
            if key == curses.KEY_RESIZE:
                continue
            if key == -1:
                empty, gone = note_empty_read(empty)
                if gone:
                    return None
                continue
            empty = 0
            buf, pos, outcome = edit_key(buf, pos, key)
            if outcome is not None:
                return buf if outcome == "enter" else None
    finally:
        _set_cursor(0)
