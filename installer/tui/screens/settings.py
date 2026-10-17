"""Tab 6: the typed settings editor, also the first-run wizard (``SettingsScreen(wizard=True)``).

Edits live in ``self.pending`` (an immutable Config that is replaced, never changed) until
``s`` writes them. The App's global ``R`` (recheck) reloads the config from disk; this screen
cooperates through ``on_rescan``: when the config object was replaced and there are unsaved
edits it asks before discarding them. The question is drawn in the body, because the App's own
"rescanned" message replaces the footer for that frame. ``A`` runs ``python3 -m installer apply
--yes`` after a ``y`` and only when a config file is saved and nothing is unsaved, because the
installer reads the saved file. That command runs install.sh and then copies the hook profile
and Codex subagent settings you changed from the defaults into the existing ``settings.json`` /
``config.toml`` (see ``core.apply_settings``). A setting left at its default is not pushed, so
a value set by hand in those files survives; the ``settings-sync`` command pushes everything.
It runs under the same home the screens show: ``fullinstall.with_home``
sets ``$HOME`` and, for a relocated session, ``--home`` is passed too so exported tool-home
variables cannot send the child to the real directories.
"""

from __future__ import annotations

import curses
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from installer.core import config as cfg
from installer.tui import draw
from installer.tui.base import POP, Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.fullinstall import home_suffix, relocated_home, with_home
from installer.tui.screens.listedit import ListEditScreen

TOOLS_SHOWN = ("claude", "codex", "gemini", "git", "gh", "node", "docker", "obsidian", "tmux", "headroom")
ESC = 27
ENTER_KEYS = (10, 13, curses.KEY_ENTER, ord(" "))
LABEL_WIDTH = 30
HELP_LINES = 2
PROMPTS = {
    "apply": "Install, then push the settings you changed?  y = run, any other key cancels",
    "reload": "Unsaved edits: y = discard them and use the file on disk, any other key keeps them",
}
Styled = Tuple[str, str]  # (text, attr name)


@dataclass(frozen=True)
class Row:
    """A section header (setting is None, not selectable) or one editable setting."""

    section: str
    setting: Optional[cfg.Setting] = None

    @property
    def is_setting(self) -> bool:
        return self.setting is not None


def ordered_sections() -> Tuple[str, ...]:
    """config.SECTIONS first, then any section a future setting introduces."""
    extra = tuple(dict.fromkeys(s.section for s in cfg.SETTINGS if s.section not in cfg.SECTIONS))
    return cfg.SECTIONS + extra


def build_rows(sections: Sequence[str]) -> Tuple[Row, ...]:
    """Header row plus one row per setting, for each of `sections` that has settings."""
    rows: List[Row] = []
    for section in sections:
        members = [s for s in cfg.SETTINGS if s.section == section]
        if members:
            rows.append(Row(section))
            rows.extend(Row(section, s) for s in members)
    return tuple(rows)


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else "(none)"
    return "(empty)" if value == "" else str(value)


def next_choice(setting: cfg.Setting, current: Any) -> str:
    """The enum choice after `current`, wrapping; the first choice when `current` is not one."""
    choices = setting.choices
    if current in choices:
        return choices[(choices.index(current) + 1) % len(choices)]
    return choices[0]


def settle(model: ListModel, direction: int, height: int) -> ListModel:
    """Move the cursor off section headers (they are not selectable), preferring `direction`."""
    step = 1 if direction >= 0 else -1
    current = model
    for _ in range(len(model.items) + 1):
        row = current.current()
        if row is None or row.is_setting:
            return current
        nxt = current.move(step, height)
        if nxt.cursor == current.cursor:
            step = -step
            nxt = current.move(step, height)
        current = nxt
    return current


def setting_hint(setting: cfg.Setting) -> str:
    hints = {"bool": "Enter/space toggles.", "enum": "Enter cycles: " + ", ".join(setting.choices) + ".",
             "int": "Enter edits (whole number).", "str": "Enter edits.", "path": "Enter edits (a path).",
             "pathlist": "Enter opens the list editor.", "strlist": "Enter opens the list editor."}
    return f"{setting.help} {hints.get(setting.kind, '')}".strip()


def wizard_intro(caps: Any, width: int) -> Tuple[str, ...]:
    """Two or three lines: what was detected, and that nothing is written until `s`."""
    found = [name for name in TOOLS_SHOWN if caps.present(name)]
    missing = [name for name in TOOLS_SHOWN if name not in found]
    text = "Detected: " + (", ".join(found) or "none of the usual tools") + "."
    if missing:
        text += " Not found: " + ", ".join(missing) + "."
    text += " Nothing is written until you press s."
    return tuple(textwrap.wrap(text, max(20, width - 2))[:3])


class SettingsScreen(Screen):
    title = "Settings"
    tab = 6

    def __init__(self, wizard: bool = False) -> None:
        self.wizard = wizard
        if wizard:
            self.tab = None
            self.title = "Setup wizard"
        self.step = 0
        self.pending: Optional[cfg.Config] = None
        self._synced: Optional[cfg.Config] = None
        self._confirm: Optional[str] = None
        self._height = 10
        self._top = 0
        self.model: ListModel = ListModel()
        self._reset_model()

    # ------------------------------------------------------------ state

    def _ensure(self, app) -> None:
        if self.pending is None:
            self.pending = self._synced = app.config

    def dirty(self) -> bool:
        if self.pending is None or self._synced is None:
            return False
        return cfg.to_json(self.pending) != cfg.to_json(self._synced)

    @property
    def on_summary(self) -> bool:
        return self.wizard and self.step >= len(ordered_sections())

    @property
    def section_name(self) -> str:
        sections = ordered_sections()
        return sections[min(self.step, len(sections) - 1)]

    def _rows_for_step(self) -> Tuple[Row, ...]:
        sections = ordered_sections()
        if not self.wizard:
            return build_rows(sections)
        return () if self.on_summary else build_rows((sections[self.step],))

    def _reset_model(self) -> None:
        self.model = settle(ListModel(items=self._rows_for_step()), 1, self._height)

    def editing(self) -> bool:
        return self._confirm is not None

    def on_enter(self, app) -> None:
        self._sync(app)

    def on_rescan(self, app) -> None:
        self._sync(app)

    def _sync(self, app) -> None:
        """Adopt a freshly loaded app.config; with unsaved edits, ask before discarding them."""
        self._ensure(app)
        if app.config is self._synced:
            return
        if self.dirty():
            self._confirm = "reload"
            return
        self.pending = self._synced = app.config

    # ------------------------------------------------------------- draw

    def _footer(self) -> str:
        if self._confirm in PROMPTS:
            return PROMPTS[self._confirm]
        if self.on_summary:
            return "s save   A apply   p previous   j/k scroll   q cancel"
        if self.wizard:
            return "Enter/space change   n next   p previous   s save   A apply   q cancel"
        return "j/k move   Enter/space change   s save   A apply   R reload   ? help   q back"

    def _label(self) -> str:
        suffix = "  [unsaved]" if self.dirty() else ""
        if self.on_summary:
            return f"{self.title}: summary{suffix}"
        if self.wizard:
            return f"{self.title}: {self.step + 1} of {len(ordered_sections())} - {self.section_name}{suffix}"
        return self.title + suffix

    def draw(self, stdscr, app) -> None:
        self._ensure(app)
        y0, x0, height, width = draw.draw_frame(stdscr, app, self._label(), self._footer())
        if self.on_summary:
            # while a question is open the bottom lines belong to it (the footer may be hidden by a message)
            body = height - HELP_LINES if self._confirm and height > HELP_LINES else height
            self._draw_summary(stdscr, y0, x0, body, width)
            self._draw_help(stdscr, y0 + body, x0, width)
            return
        top = y0
        if self.wizard:
            for line in wizard_intro(app.caps, width):
                draw.safe_addstr(stdscr, top, x0, line, draw.attr("dim"), width)
                top += 1
        list_height = max(1, y0 + height - top - HELP_LINES)
        if list_height != self._height:
            self._height = list_height
            self.model = self.model.move(0, list_height)
        draw.draw_list(stdscr, top, x0, list_height, width, self.model, self._row_text)
        self._draw_help(stdscr, y0 + height - HELP_LINES, x0, width)

    def _row_text(self, row: Row, selected: bool, width: int) -> Tuple[str, int]:
        if row.setting is None:
            return f" {row.section}", draw.attr("title")
        setting = row.setting
        value = cfg.get(self.pending, setting.key)
        changed = value != cfg.get(self._synced, setting.key)
        label = ("* " if changed else "  ") + setting.label
        text = f"  {label:<{LABEL_WIDTH}}{format_value(value)}"
        return draw.truncate(text, width), draw.attr("warn" if changed else "normal")

    def _draw_help(self, stdscr, y: int, x: int, width: int) -> None:
        """The open question (warn style) or, failing that, the hint for the current setting."""
        row = self.model.current()
        if self._confirm in PROMPTS:
            text, style = PROMPTS[self._confirm], "warn"
        elif self.on_summary or row is None or row.setting is None:
            return
        else:
            text, style = setting_hint(row.setting), "dim"
        for offset, piece in enumerate(textwrap.wrap(text, max(20, width - 2))[:HELP_LINES]):
            draw.safe_addstr(stdscr, y + offset, x, piece, draw.attr(style), width)

    def summary_lines(self) -> Tuple[Styled, ...]:
        lines: List[Styled] = [("Review your choices. Nothing is written until you press s.", "title"), ("", "normal")]
        for section in ordered_sections():
            members = [s for s in cfg.SETTINGS if s.section == section]
            if not members:
                continue
            lines.append((section, "title"))
            for setting in members:
                value = cfg.get(self.pending, setting.key)
                changed = value != cfg.get(self._synced, setting.key)
                text = f"  {setting.label:<{LABEL_WIDTH}}{format_value(value)}"
                lines.append((text, "warn" if changed else "normal"))
        lines += [("", "normal"), (f"s writes {self.pending.path}", "dim"),
                  ("A then installs and pushes the settings you changed from the defaults", "dim"),
                  ("into settings.json / config.toml. A value left at its default is not", "dim"),
                  ("pushed, so edits you made there by hand stay.", "dim")]
        return tuple(lines)

    def _draw_summary(self, stdscr, y0: int, x0: int, height: int, width: int) -> None:
        lines = self.summary_lines()
        self._height = height
        self._top = draw.clamp_top(self._top, len(lines), height)
        draw.draw_text(stdscr, y0, x0, height, width, [(t, draw.attr(n)) for t, n in lines], self._top)

    # ------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            self._ensure(app)
            if self._confirm is not None:
                self._answer(key, app)
                return None
            return self._dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - a bad key must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
            return None

    def _dispatch(self, key: int, app) -> Optional[str]:
        if key == ESC and self.wizard:
            return POP
        commands = {ord("s"): self._save, ord("A"): self._ask_apply}
        if key in commands:
            commands[key](app)
        elif self.wizard and key in (ord("n"), ord("p")):
            self._go(1 if key == ord("n") else -1, app)
        elif self.on_summary:
            moved = draw.scroll_key(key, self._top, len(self.summary_lines()), self._height)
            self._top = self._top if moved is None else moved
        elif key in ENTER_KEYS:
            self._edit_current(app)
        else:
            self._move(key)
        return None

    def _move(self, key: int) -> None:
        h = self._height
        moves = {ord("j"): (1, lambda m: m.move(1, h)), curses.KEY_DOWN: (1, lambda m: m.move(1, h)),
                 ord("k"): (-1, lambda m: m.move(-1, h)), curses.KEY_UP: (-1, lambda m: m.move(-1, h)),
                 curses.KEY_NPAGE: (1, lambda m: m.page(1, h)), curses.KEY_PPAGE: (-1, lambda m: m.page(-1, h)),
                 ord("g"): (1, lambda m: m.home(h)), curses.KEY_HOME: (1, lambda m: m.home(h)),
                 ord("G"): (-1, lambda m: m.end(h)), curses.KEY_END: (-1, lambda m: m.end(h))}
        if key in moves:
            direction, move = moves[key]
            self.model = settle(move(self.model), direction, h)

    def _go(self, delta: int, app) -> None:
        last = len(ordered_sections())
        target = max(0, min(last, self.step + delta))
        if target == self.step:
            app.set_message("last page: s saves, A applies" if delta > 0 else "first section")
            return
        self.step, self._top = target, 0
        self._reset_model()

    # ------------------------------------------------------------ edits

    def _set(self, app, key: str, value: Any) -> bool:
        try:
            self.pending = cfg.with_value(self.pending, key, value)
        except (KeyError, ValueError) as exc:
            app.set_message(str(exc))
            return False
        return True

    def _edit_current(self, app) -> None:
        row = self.model.current()
        if row is None or row.setting is None:
            return
        setting = row.setting
        value = cfg.get(self.pending, setting.key)
        if setting.kind == "bool":
            self._set(app, setting.key, not value)
        elif setting.kind == "enum":
            self._set(app, setting.key, next_choice(setting, value))
        elif setting.kind in cfg.LIST_KINDS:
            self._open_list(app, setting, value)
        else:
            self._prompt(app, setting, value)

    def _prompt(self, app, setting: cfg.Setting, value: Any) -> None:
        text = draw.prompt_line(app.stdscr, f"{setting.label}: ", initial=str(value))
        if text is None:
            app.set_message("unchanged")
            return
        try:
            parsed = cfg.parse_value(setting, text)
        except ValueError as exc:
            app.set_message(str(exc))
            return
        self._set(app, setting.key, parsed)

    def _open_list(self, app, setting: cfg.Setting, value: Any) -> None:
        def commit(items: Tuple[str, ...]) -> None:
            self.pending = cfg.with_value(self.pending, setting.key, items)  # ValueError reaches the list screen

        app.push(ListEditScreen(setting, tuple(value), commit))

    # --------------------------------------------------- save/apply/reload

    def _save(self, app) -> None:
        warnings = cfg.validate(self.pending)
        path = cfg.save(self.pending, app.paths)
        app.reload_config()
        self.pending = self._synced = app.config
        note = f" (warning: {warnings[0]})" if warnings else ""
        app.set_message(f"saved {app.paths.display(path)}{note}")

    def _ask_apply(self, app) -> None:
        if self.dirty():
            app.set_message("unsaved edits: press s to save first (apply installs from the saved config)")
            return
        if not app.config.exists:
            app.set_message("no saved config yet: press s to save first (apply syncs from the saved config)")
            return
        self._confirm = "apply"

    def _adopt_disk(self, app) -> None:
        app.reload_config()
        self.pending = self._synced = app.config
        app.set_message("reloaded from disk")

    def _answer(self, key: int, app) -> None:
        action, self._confirm = self._confirm, None
        agreed = key in (ord("y"), ord("Y"))
        if action == "apply":
            if agreed:
                self._run_apply(app)
            else:
                app.set_message("apply cancelled")
        elif agreed:  # "reload": the file on disk replaces the unsaved edits
            self._adopt_disk(app)
        else:
            self._synced = app.config
            app.set_message("kept your unsaved edits")

    def _run_apply(self, app) -> None:
        argv = [sys.executable, "-m", "installer", "apply", "--yes", "--repo", app.paths.repo_dir]
        home = relocated_home(app.paths)
        if home is not None:  # a sandbox: the child must not honour exported CLAUDE_CONFIG_DIR / CODEX_HOME / AGENTS_HOME
            argv += ["--home", home]
        title = "Apply settings: installer apply (install.sh, then settings sync)" + home_suffix(app.paths)
        app.run_command(list(with_home(app.paths, argv)), title, cwd=app.paths.repo_dir)
