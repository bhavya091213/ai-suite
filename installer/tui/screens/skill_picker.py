"""Skill picker: tick the skills a workflow phase should load, plus what the workflow editors share.

Rows are the union of every skill that is installed (shared, Claude or Codex) or in the repo
catalog: one row per name, with its description and the scopes it exists in. A name the phase
already lists but that is neither installed nor in the catalog still gets a row, so it can be
unticked. ``space`` toggles, ``/`` filters (name and description), ``Enter`` accepts and ``q`` or
``Esc`` cancels.

``OwnedScreen`` is the base of the picker and of the two editors in ``workflow_edit``: a pushed
screen that owns the keyboard (``editing()`` is True), so a stray tab number cannot drop the
workflow being edited. The small tuple helpers below are the editors' only list operations.
"""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

from installer.core.types import State
from installer.tui import draw
from installer.tui.base import POP, Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.viewer_panes import ENTER_KEYS, ESC, move_model

T = TypeVar("T")
OnAccept = Callable[[Tuple[str, ...]], None]
BACK_FIRST = "q goes back first (Enter accepts in the skill picker)"
UNKNOWN_NOTE = "(not installed and not in the repo catalog)"
NAME_WIDTH = 28
SCOPES_WIDTH = 14
ON_DISK_KINDS = ("dir", "symlink")
FOOTER = "space tick   / filter   a all shown   n none   Enter accept   q cancel"


@dataclass(frozen=True)
class SkillChoice:
    name: str
    description: str
    scopes: Tuple[str, ...]


def choice_text(choice: SkillChoice) -> str:
    """What the "/" filter matches against."""
    return f"{choice.name} {choice.description}"


def _usable(status) -> bool:
    """Installed (a directory or a working link) or in the catalog; tool-managed rows are not."""
    if status.state == State.IGNORED:
        return False
    installed = status.installed
    return status.source is not None or (installed is not None and installed.kind in ON_DISK_KINDS)


def skill_choices(statuses: Sequence, current: Sequence[str] = ()) -> Tuple[SkillChoice, ...]:
    """One choice per skill name over the installed and catalog rows, sorted by name.

    Names in `current` that no row knows are added with ``UNKNOWN_NOTE``.
    """
    described: Dict[str, str] = {}
    scopes: Dict[str, List[str]] = {}
    for status in statuses:
        if not _usable(status):
            continue
        text = " ".join(status.description.split())
        described[status.name] = described.get(status.name) or text
        found = scopes.setdefault(status.name, [])
        if status.scope not in found:
            found.append(status.scope)
    for name in current:
        if name.strip() and name not in described:
            described[name], scopes[name] = UNKNOWN_NOTE, []
    return tuple(SkillChoice(name, described[name], tuple(scopes[name]))
                 for name in sorted(described, key=str.casefold))


def accepted_order(chosen: Sequence[str], previous: Sequence[str]) -> Tuple[str, ...]:
    """The phase's own order for skills still ticked, then the newly ticked ones in list order."""
    wanted = frozenset(chosen)
    kept = tuple(dict.fromkeys(name for name in previous if name in wanted))
    return kept + tuple(name for name in chosen if name not in kept)


class OwnedScreen(Screen):
    """A pushed screen that owns the keyboard; ``?`` opens help, errors in a key go to the message line."""

    tab = None

    def editing(self) -> bool:
        return True

    def typing(self) -> bool:
        """True while keys are text (a filter), so ``?`` is a character rather than help."""
        return False

    def dispatch(self, key: int, app) -> Optional[str]:
        raise NotImplementedError

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key == ord("?") and not self.typing():
                app.open_help()
                return None
            return self.dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - report on the message line, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
            return None


def moved(items: Sequence[T], index: int, delta: int) -> Tuple[T, ...]:
    """`items` with the entry at `index` shifted by `delta`; unchanged when that falls off an end."""
    target = index + delta
    if not (0 <= index < len(items) and 0 <= target < len(items)):
        return tuple(items)
    out = list(items)
    out[index], out[target] = out[target], out[index]
    return tuple(out)


def without(items: Sequence[T], index: int) -> Tuple[T, ...]:
    return tuple(item for position, item in enumerate(items) if position != index)


def inserted(items: Sequence[T], index: int, item: T) -> Tuple[T, ...]:
    return tuple(items[:index]) + (item,) + tuple(items[index:])


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def at_position(model: ListModel, position: int, height: int) -> ListModel:
    """`model` with the cursor on the absolute row `position`."""
    return model.home(height).move(position, height)


class SkillPickerScreen(OwnedScreen):
    """``on_accept(names)`` receives the ticked skills (see ``accepted_order``) on Enter."""

    def __init__(self, choices: Sequence[SkillChoice], chosen: Sequence[str], on_accept: OnAccept,
                 title: str = "Pick skills") -> None:
        self.title = title
        self.on_accept = on_accept
        self.previous: Tuple[str, ...] = tuple(chosen)
        ticked = frozenset(i for i, choice in enumerate(choices) if choice.name in self.previous)
        self.model: ListModel = ListModel(items=tuple(choices), selected=ticked, key_fn=choice_text)
        self._filtering = False
        self._pos = 0
        self._height = 10

    def typing(self) -> bool:
        return self._filtering

    # -------------------------------------------------------------- draw

    def _footer(self) -> str:
        if self._filtering:
            return f"/{self.model.query}_   Enter keep the filter   Esc clear it"
        return FOOTER

    def _row(self, choice: SkillChoice, selected: bool, width: int) -> Tuple[str, int]:
        box = draw.glyph("selected" if selected else "unselected")
        scopes = ",".join(choice.scopes) or "-"
        head = f"{box} {choice.name:<{NAME_WIDTH}.{NAME_WIDTH}} {scopes:<{SCOPES_WIDTH}.{SCOPES_WIDTH}} "
        return draw.truncate(head + choice.description, width), draw.attr("normal")

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, self._footer())
        body = max(1, height - 1)
        self._height = body
        self.model = self.model.move(0, body)
        if not self.model.filtered_count:
            text = "no skills are installed or in the catalog" if not self.model.query else "no skill matches"
            draw.safe_addstr(stdscr, y0, x0, text, draw.attr("dim"), width)
        draw.draw_list(stdscr, y0, x0, body, width, self.model, self._row)
        shown = f"{self.model.filtered_count}/{self.model.count} shown   {self.model.selected_count} ticked"
        shown += f"   filter: {self.model.query}" if self.model.query else ""
        draw.safe_addstr(stdscr, y0 + height - 1, x0, shown, draw.attr("dim"), width)

    # -------------------------------------------------------------- keys

    def dispatch(self, key: int, app) -> Optional[str]:
        if self._filtering:
            self._filter_key(key)
        elif key == ESC and self.model.query:
            self.model = self.model.set_query("")
        elif key in (ord("q"), ESC):
            return POP
        elif key in ENTER_KEYS:
            return self._accept()
        elif key == ord("Q"):
            app.set_message(BACK_FIRST)
        else:
            self._list_key(key)
        return None

    def _list_key(self, key: int) -> None:
        moved = move_model(self.model, key, self._height)
        if moved is not None:
            self.model = moved
        elif key == ord(" "):
            self.model = self.model.toggle()
        elif key == ord("a"):
            self.model = self.model.select_all_visible()
        elif key == ord("n"):
            self.model = self.model.select_none()
        elif key == ord("/"):
            self._filtering, self._pos = True, len(self.model.query)

    def _filter_key(self, key: int) -> None:
        if key in (curses.KEY_UP, curses.KEY_DOWN):
            self.model = move_model(self.model, key, self._height) or self.model
            return
        text, pos, outcome = draw.edit_key(self.model.query, self._pos, key)
        if outcome == "cancel":
            text, pos = "", 0
        if text != self.model.query:
            self.model = self.model.set_query(text)
        self._pos = pos
        self._filtering = outcome is None

    def _accept(self) -> Optional[str]:
        names = tuple(choice.name for choice in self.model.selected_items())
        self.on_accept(accepted_order(names, self.previous))
        return POP
