"""Sub-screen that edits one list setting (pathlist / strlist) entry by entry.

Pushed by the Settings screen. Every change is handed to ``on_change`` straight
away (the Settings screen validates it and updates its pending config), so there
is nothing to commit when the user leaves; ``Esc`` or ``Enter`` just closes it.
"""

from __future__ import annotations

import curses
import os
import sys
from typing import Callable, Optional, Sequence, Tuple

from installer.core import capabilities
from installer.core import config as cfg
from installer.tui import draw
from installer.tui.base import POP, Screen
from installer.tui.listmodel import ListModel

ESC = 27
ENTER_KEYS = (10, 13)
VAULT_KEY = "paths.obsidian_vaults"
OnChange = Callable[[Tuple[str, ...]], None]
VaultFinder = Callable[[], Tuple[str, ...]]


def registry_vaults() -> Tuple[str, ...]:
    """Vault directories from the Obsidian registry on this machine (open ones first)."""
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return capabilities.obsidian_vaults(home, sys.platform, os.environ)


def numbered(items: Sequence[str]) -> Tuple[Tuple[int, str], ...]:
    """(1-based position, text) pairs: the model rows know their own number."""
    return tuple((position, text) for position, text in enumerate(items, 1))


def appended(items: Sequence[str], additions: Sequence[str]) -> Tuple[str, ...]:
    """`items` plus every addition not already present, order kept (the default stays first)."""
    out = list(items)
    for entry in additions:
        if entry not in out:
            out.append(entry)
    return tuple(out)


def without_index(items: Sequence[str], index: int) -> Tuple[str, ...]:
    return tuple(entry for position, entry in enumerate(items) if position != index)


def promoted(items: Sequence[str], index: int) -> Tuple[str, ...]:
    """`items` with the entry at `index` moved to the front."""
    if not 0 <= index < len(items):
        return tuple(items)
    return (items[index],) + without_index(items, index)


class ListEditScreen(Screen):
    """``a`` add  ``x`` remove  ``d`` make default  ``o`` import vaults (Obsidian setting only)."""

    tab = None

    def __init__(self, setting: cfg.Setting, items: Sequence[str], on_change: OnChange,
                 vault_finder: VaultFinder = registry_vaults) -> None:
        self.setting = setting
        self.title = f"Edit list: {setting.label}"
        self.on_change = on_change
        self.vault_finder = vault_finder
        self.model: ListModel = ListModel(items=numbered(items))
        self._height = 10

    @property
    def items(self) -> Tuple[str, ...]:
        return tuple(text for _, text in self.model.items)

    @property
    def is_vault_list(self) -> bool:
        return self.setting.key == VAULT_KEY

    # -------------------------------------------------------------- draw

    def _footer(self) -> str:
        keys = "a add   x remove   d make default"
        if self.is_vault_list:
            keys += "   o import from Obsidian"
        return keys + "   Esc done"

    def _row(self, item: Tuple[int, str], selected: bool, width: int) -> Tuple[str, int]:
        position, text = item
        mark = "  (default)" if self.is_vault_list and position == 1 else ""
        return f"{position:>3}. {text}{mark}", draw.attr("normal")

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, self._footer())
        draw.safe_addstr(stdscr, y0, x0, self.setting.help, draw.attr("dim"), width)
        body = max(1, height - 2)
        if body != self._height:
            self._height = body
            self.model = self.model.move(0, body)
        if not self.items:
            draw.safe_addstr(stdscr, y0 + 2, x0 + 2, "(empty - press a to add an entry)", draw.attr("dim"))
            return
        draw.draw_list(stdscr, y0 + 2, x0, body, width, self.model, self._row)

    # -------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            return self._dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - a sub-screen must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
            return None

    def _dispatch(self, key: int, app) -> Optional[str]:
        if key == ESC or key in ENTER_KEYS:
            return POP
        actions = {ord("a"): self._add, ord("x"): self._remove, ord("d"): self._make_default,
                   ord("o"): self._import}
        if key in actions:
            actions[key](app)
            return None
        self._move(key)
        return None

    def _move(self, key: int) -> None:
        h = self._height
        moves = {ord("j"): lambda m: m.move(1, h), ord("k"): lambda m: m.move(-1, h),
                 curses.KEY_DOWN: lambda m: m.move(1, h), curses.KEY_UP: lambda m: m.move(-1, h),
                 curses.KEY_NPAGE: lambda m: m.page(1, h), curses.KEY_PPAGE: lambda m: m.page(-1, h),
                 ord("g"): lambda m: m.home(h), ord("G"): lambda m: m.end(h)}
        if key in moves:
            self.model = moves[key](self.model)

    def _apply(self, app, items: Tuple[str, ...], message: str) -> bool:
        """Hand `items` to the owner; keep the old list and show the reason when it refuses."""
        try:
            self.on_change(items)
        except (ValueError, KeyError) as exc:
            app.set_message(str(exc))
            return False
        self.model = self.model.with_items(numbered(items))
        app.set_message(message)
        return True

    def _add(self, app) -> None:
        text = draw.prompt_line(app.stdscr, f"Add to {self.setting.label} (comma separated): ")
        if text is None or not text.strip():
            app.set_message("nothing added")
            return
        try:
            entries = cfg.parse_value(self.setting, text)
        except ValueError as exc:
            app.set_message(str(exc))
            return
        merged = appended(self.items, entries)
        added = len(merged) - len(self.items)
        noun = "entry" if added == 1 else "entries"
        self._apply(app, merged, f"added {added} {noun}" if added else "already in the list")

    def _remove(self, app) -> None:
        index = self.model.current_index()
        if index is None:
            app.set_message("nothing to remove")
            return
        removed = self.items[index]
        self._apply(app, without_index(self.items, index), f"removed {removed}")

    def _make_default(self, app) -> None:
        index = self.model.current_index()
        if index is None:
            app.set_message("nothing selected")
            return
        if index == 0:
            app.set_message("already the default")
            return
        moved = promoted(self.items, index)
        if self._apply(app, moved, f"{moved[0]} is now the default"):
            self.model = self.model.home(self._height)

    def _import(self, app) -> None:
        if not self.is_vault_list:
            app.set_message("o only imports Obsidian vaults (paths.obsidian_vaults)")
            return
        found = self.vault_finder()
        if not found:
            app.set_message("no Obsidian vaults found in the registry")
            return
        merged = appended(self.items, found)
        added = len(merged) - len(self.items)
        self._apply(app, merged, f"imported {added} vault(s)" if added else "all registry vaults are already listed")
