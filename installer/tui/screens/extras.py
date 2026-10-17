"""Tab 9: external integrations the installer knows about (shared/extras.json).

Rows are ``app.extras`` (one ``ExtraStatus`` each) with a set-up mark per tool: a check when
detected, a cross when not, a question mark when it cannot be told. ``Enter`` shows details,
``i`` installs, ``o`` prints the project URL on the message line.

Installing runs a THIRD-PARTY command, so ``i`` never runs anything directly: it opens a
confirmation screen that lists the exact commands and says third-party code will run, and only
``y`` there starts them. Commands are split with ``shlex`` and run as argument lists (never
through a shell), one after another, each in its own output pane. The output pane's ``q`` moves
on to the next command; a command that exits non-zero drops the rest. The queue lives in the
Extras screen: a finished pane pops back onto it, and ``on_enter`` starts the next command.

The commands run from the home directory (the relocated one when the session was started with
``--home``, see ``fullinstall.run_dir`` / ``with_home``), never from the repo checkout: a
third-party installer that defaults to a project-scope install would otherwise write its files
into this published mirror, and the detection paths all live under the tool homes.
"""

from __future__ import annotations

import curses
import json
import os
import shlex
import textwrap
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from installer.core import capabilities
from installer.core import config as cfg
from installer.core import extras as extras_mod
from installer.tui import draw
from installer.tui.base import POP, Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.files import TextPaneScreen
from installer.tui.screens.fullinstall import home_suffix, relocated_home, run_dir, with_home

ESC = 27
ENTER_KEYS = (10, 13, curses.KEY_ENTER)
DETAIL_LINES = 3
WRAP = 76
KEY_WIDTH = 20
CATEGORY_WIDTH = 14
CELLS_WIDTH = 19
WARNING = ("This runs third-party code on your machine. The installer does not review it: read the "
           "project page first, and only continue if you trust the source.")
Styled = Tuple[str, str]  # (text, attr name)
Argv = Tuple[str, ...]


@dataclass(frozen=True)
class InstallPlan:
    """What ``i`` would run: the tools it serves, the de-duplicated commands, and what was skipped."""

    extra: extras_mod.Extra
    tools: Tuple[str, ...]
    commands: Tuple[str, ...]
    skipped: Tuple[Tuple[str, str], ...]  # (tool, reason)


def enabled_tools(app) -> Tuple[str, ...]:
    """Tools whose ``tools.*`` setting resolves to on (the same rule `installer sections` uses)."""
    return tuple(tool for tool in extras_mod.TOOLS
                 if capabilities.resolve_tool(cfg.get(app.config, f"tools.{tool}"), app.caps.get(tool)))


def plan_install(status: extras_mod.ExtraStatus, enabled: Sequence[str]) -> InstallPlan:
    """Commands for every tool of the extra that is on and not yet set up; shared commands run once."""
    tools: List[str] = []
    skipped: List[Tuple[str, str]] = []
    commands: List[str] = []
    for tool in status.extra.tools:
        if tool not in enabled:
            skipped.append((tool, "tool is off or not detected (Settings > Tools)"))
        elif status.installed.get(tool) is True:
            skipped.append((tool, "already set up"))
        elif not extras_mod.commands_for(status.extra, tool):
            skipped.append((tool, "no install command for this tool"))
        else:
            tools.append(tool)
            commands.extend(extras_mod.commands_for(status.extra, tool))
    return InstallPlan(status.extra, tuple(tools), tuple(dict.fromkeys(commands)), tuple(skipped))


def parse_commands(commands: Sequence[str]) -> Tuple[Argv, ...]:
    """shlex-split each command into an argv; ValueError (with the command) when one cannot run."""
    out: List[Argv] = []
    for command in commands:
        try:
            argv = tuple(shlex.split(command))
        except ValueError as exc:
            raise ValueError(f"cannot parse {command!r}: {exc}") from exc
        if not argv:
            raise ValueError("an install command is empty")
        out.append(argv)
    return tuple(out)


def mark_for(value: Optional[bool]) -> str:
    if value is None:
        return draw.glyph("unknown")
    return draw.glyph("yes" if value else "no")


def tool_cells(status: extras_mod.ExtraStatus) -> str:
    """``claude + codex x`` style cells; ``-`` for a tool the extra does not support."""
    cells = []
    for tool in extras_mod.TOOLS:
        mark = mark_for(status.installed.get(tool)) if tool in status.extra.tools else "-"
        cells.append(f"{tool} {mark}")
    return "  ".join(cells)


def wrapped(text: str, style: str, indent: str = "") -> Tuple[Styled, ...]:
    pieces = textwrap.wrap(text, WRAP, initial_indent=indent, subsequent_indent=indent) or [indent]
    return tuple((piece, style) for piece in pieces)


def load_notes(paths) -> Dict[str, str]:
    """``key -> note`` from ``<repo>/shared/extras.json``; ``{}`` when the file is absent or unusable.

    The optional per-entry ``note`` is informational (why something is not vendored, licensing),
    and ``core.extras.Extra`` does not carry it, so the details view reads it from the catalog.
    """
    try:
        with open(os.path.join(paths.repo_dir, extras_mod.EXTRAS_RELPATH), encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):
        return {}
    entries = data.get("extras") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    return {str(key): raw["note"].strip() for key, raw in entries.items()
            if isinstance(raw, dict) and isinstance(raw.get("note"), str) and raw["note"].strip()}


def note_for(paths, extra: extras_mod.Extra) -> str:
    """The extra's note: its own ``note`` attribute when core provides one, else the catalog file's."""
    own = getattr(extra, "note", "")
    if isinstance(own, str) and own.strip():
        return own.strip()
    return load_notes(paths).get(extra.key, "")


def detail_lines(status: extras_mod.ExtraStatus, enabled: Sequence[str], note: str = "") -> Tuple[Styled, ...]:
    """Title, url, per-tool state, the note, the commands per tool and the after-install notes."""
    extra = status.extra
    states = {True: "set up", False: "not set up", None: "unknown"}
    lines: List[Styled] = list(wrapped(extra.title, "title"))
    lines += [("", "normal"), (f"Key       {extra.key}", "normal"), (f"Category  {extra.category}", "normal"),
              (f"URL       {extra.url or '(none listed)'}", "normal"), ("", "normal"), ("Status", "title")]
    for tool in extra.tools:
        power = "on" if tool in enabled else "off"
        lines.append((f"  {tool:<8}{states[status.installed.get(tool)]:<12}tool is {power}", "normal"))
    if note:
        lines += [("", "normal"), ("Note", "title")] + list(wrapped(note, "normal", "  "))
    lines += [("", "normal"), ("Install commands (nothing runs until you confirm)", "title")]
    for tool in extra.tools:
        shown = extras_mod.commands_for(extra, tool) or ("(none)",)
        lines += [(f"  {tool}: {command}", "normal") for command in shown]
    if extra.after_install:
        lines += [("", "normal"), ("After install", "title")]
        lines += [(f"  {tool}: {after}", "normal") for tool, after in extra.after_install.items()]
    return tuple(lines + [("", "normal")] + list(wrapped(WARNING, "warn")))


# ------------------------------------------------------------ confirmation


class InstallConfirmScreen(Screen):
    """States the exact commands and that third-party code will run; ``y`` starts them."""

    tab = None

    def __init__(self, plan: InstallPlan, argvs: Sequence[Argv], run_dir_display: str,
                 on_confirm: Callable[[Any], None], home_display: str = "") -> None:
        self.plan = plan
        self.argvs: Tuple[Argv, ...] = tuple(argvs)
        self.run_dir_display = run_dir_display
        self.home_display = home_display  # non-empty when HOME is relocated for the commands
        self.on_confirm = on_confirm
        self.title = f"Install {plan.extra.key}?"
        self._top = 0
        self._height = 1

    def editing(self) -> bool:
        return True

    def lines(self) -> Tuple[Styled, ...]:
        plan = self.plan
        out: List[Styled] = list(wrapped(plan.extra.title, "title"))
        out += [(f"For: {', '.join(plan.tools)}", "normal"), (f"Project page: {plan.extra.url or '(none)'}", "normal"),
                ("", "normal"), ("WARNING", "error")]
        out += list(wrapped(WARNING, "warn"))
        out += [("", "normal"), (f"These exact commands will run, in order, from {self.run_dir_display}:", "title")]
        out += [(f"  {number}. {shlex.join(argv)}", "normal") for number, argv in enumerate(self.argvs, 1)]
        if self.home_display:
            out += list(wrapped(f"HOME is set to {self.home_display} for them (this session was started with --home).",
                                "warn"))
        out += [("", "normal")]
        out += list(wrapped("Each command opens an output pane; press q there when it finishes to continue with "
                            "the next one. A command that fails stops the rest.", "dim"))
        out += [(f"Skipped {tool}: {reason}", "dim") for tool, reason in plan.skipped]
        return tuple(out + [("", "normal"), ("y = run these commands    n / Esc = cancel", "title")])

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, "y run   n/Esc cancel   j/k scroll")
        lines = self.lines()
        self._height = height
        self._top = draw.clamp_top(self._top, len(lines), height)
        draw.draw_text(stdscr, y0, x0, height, width, [(t, draw.attr(n)) for t, n in lines], self._top)

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key in (ord("y"), ord("Y")):
                app.pop()  # back onto the Extras screen, then start: a pushed output pane must stay on top
                self.on_confirm(app)
                return None
            if key in (ord("n"), ord("N"), ord("q"), ESC):
                app.set_message("install cancelled")
                return POP
            moved = draw.scroll_key(key, self._top, len(self.lines()), self._height, letters=False)
            self._top = self._top if moved is None else moved
        except Exception as exc:  # noqa: BLE001 - a dialog must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None


# ------------------------------------------------------------------ screen


class ExtrasScreen(Screen):
    title = "Extras"
    tab = 9

    def __init__(self) -> None:
        self.model: ListModel = ListModel()
        self._height = 8
        self._queue: Tuple[Argv, ...] = ()
        self._resume = False
        self._after = ""

    @property
    def statuses(self) -> Tuple[extras_mod.ExtraStatus, ...]:
        return self.model.items

    def sync(self, app) -> None:
        self.model = self.model.with_items(app.extras)

    def on_enter(self, app) -> None:
        self.sync(app)
        if self._resume:
            self._resume = False
            self._advance(app)

    def on_rescan(self, app) -> None:
        self.sync(app)

    # ------------------------------------------------------------- draw

    def _row_text(self, status: extras_mod.ExtraStatus, selected: bool, width: int) -> Tuple[str, int]:
        extra = status.extra
        cells = tool_cells(status)
        text = f" {extra.key:<{KEY_WIDTH}}{extra.category:<{CATEGORY_WIDTH}}{cells:<{CELLS_WIDTH}}{extra.title}"
        done = all(status.installed.get(tool) is True for tool in extra.tools)
        return draw.truncate(text, width), draw.attr("ok" if done else "normal")

    def draw(self, stdscr, app) -> None:
        if not self.model.items and app.extras:
            self.sync(app)
        footer = "Enter details   i install (asks first)   o show URL   j/k move   q back"
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, footer)
        head = f" {'Extra':<{KEY_WIDTH}}{'Category':<{CATEGORY_WIDTH}}{'Set up for':<{CELLS_WIDTH}}Title"
        draw.safe_addstr(stdscr, y0, x0, head, draw.attr("title"), width)
        if not self.model.items:
            empty = "(no extras listed: shared/extras.json is missing, empty or invalid)"
            draw.safe_addstr(stdscr, y0 + 2, x0 + 2, empty, draw.attr("dim"), width)
            return
        self._height = max(1, height - 1 - DETAIL_LINES)
        draw.draw_list(stdscr, y0 + 1, x0, self._height, width, self.model, self._row_text)
        self._draw_detail(stdscr, y0 + height - DETAIL_LINES, x0, width, app)

    def _draw_detail(self, stdscr, y: int, x: int, width: int, app) -> None:
        status = self.model.current()
        if status is None:
            return
        yes, no, unknown = (draw.glyph(name) for name in ("yes", "no", "unknown"))
        legend = f"{yes} set up   {no} not set up   {unknown} cannot tell   - not supported"
        draw.safe_addstr(stdscr, y, x, status.extra.title, draw.attr("dim"), width)
        draw.safe_addstr(stdscr, y + 1, x, f"url: {status.extra.url or '(none)'}", draw.attr("dim"), width)
        draw.safe_addstr(stdscr, y + 2, x, legend, draw.attr("dim"), width)

    # ------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            self._dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - a bad key must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _dispatch(self, key: int, app) -> None:
        h = self._height
        moves = {ord("j"): lambda m: m.move(1, h), curses.KEY_DOWN: lambda m: m.move(1, h),
                 ord("k"): lambda m: m.move(-1, h), curses.KEY_UP: lambda m: m.move(-1, h),
                 curses.KEY_NPAGE: lambda m: m.page(1, h), curses.KEY_PPAGE: lambda m: m.page(-1, h),
                 ord("g"): lambda m: m.home(h), ord("G"): lambda m: m.end(h)}
        if key in ENTER_KEYS:
            self._details(app)
        elif key == ord("i"):
            self._install(app)
        elif key == ord("o"):
            self._show_url(app)
        elif key in moves:
            self.model = moves[key](self.model)

    def _current(self, app) -> Optional[extras_mod.ExtraStatus]:
        status = self.model.current()
        if status is None:
            app.set_message("no extra selected (shared/extras.json lists none)")
        return status

    def _details(self, app) -> None:
        status = self._current(app)
        if status is not None:
            lines = detail_lines(status, enabled_tools(app), note_for(app.paths, status.extra))
            app.push(TextPaneScreen(f"Extra: {status.extra.key}", lines))

    def _show_url(self, app) -> None:
        status = self._current(app)
        if status is not None:
            app.set_message(status.extra.url or f"{status.extra.key} lists no URL")

    # ---------------------------------------------------------- install

    def _install(self, app) -> None:
        status = self._current(app)
        if status is None:
            return
        plan = plan_install(status, enabled_tools(app))
        if not plan.commands:
            reasons = "; ".join(f"{tool}: {reason}" for tool, reason in plan.skipped)
            app.set_message(f"nothing to install for {status.extra.key} ({reasons or 'no tools listed'})")
            return
        try:
            argvs = parse_commands(plan.commands)
            for argv in argvs:
                with_home(app.paths, argv)  # a command that cannot take HOME fails now, not after the confirmation
        except ValueError as exc:
            app.set_message(str(exc))
            return
        home = relocated_home(app.paths)
        app.push(InstallConfirmScreen(plan, argvs, app.paths.display(run_dir(app.paths)),
                                      lambda a: self._begin(a, plan, argvs),
                                      app.paths.display(home) if home is not None else ""))

    def _begin(self, app, plan: InstallPlan, argvs: Sequence[Argv]) -> None:
        self._queue = tuple(argvs)
        self._resume = False
        notes = [f"{tool}: {note}" for tool, note in plan.extra.after_install.items() if tool in plan.tools]
        self._after = "; ".join(notes)
        self._advance(app)

    def _advance(self, app) -> None:
        """Start the next queued command in an output pane (the previous one has been closed)."""
        if not self._queue:
            return
        argv, self._queue = self._queue[0], self._queue[1:]

        def done(code) -> None:
            self._finished(app, code)

        title = f"Extras: {shlex.join(argv)}{home_suffix(app.paths)}"
        app.run_command(list(with_home(app.paths, argv)), title, cwd=run_dir(app.paths), on_done=done)

    def _finished(self, app, code: Optional[int]) -> None:
        """Called when the user closes a command's output pane."""
        if code != 0:
            dropped, self._queue = len(self._queue), ()
            tail = f"; {dropped} remaining command(s) skipped" if dropped else ""
            app.set_message(f"command exited with {code}{tail}")
        elif self._queue:
            self._resume = True
        else:
            app.set_message("install finished" + (f". After install - {self._after}" if self._after else ""))
