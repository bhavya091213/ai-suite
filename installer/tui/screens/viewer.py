"""Skill viewer: file tree on the left (30 columns), file text on the right.

``ViewerScreen(status)`` is pushed from Skills (repo copy) and Installed (the copy on disk).
``TextScreen`` is the small read-only pager the list screens push for diffs and issue details.
Both are sub-screens (``tab = None``), so they receive Tab themselves and ``q`` pops them.
"""

from __future__ import annotations

import curses
import os
from typing import FrozenSet, Optional, Sequence, Tuple

from installer.core import tree as tree_mod
from installer.tui import draw
from installer.tui.base import POP, Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.viewer_panes import (
    DEFAULT_HEIGHT, ENTER_KEYS, ESC, KEY_TAB, LEFT_WIDTH, PAN_STEP, STATE_ATTR, TextPane,
    diff_pane, find_named, move_model, one_line, parent_position, place, read_text_file,
    row_label, tree_rows,
)

HEADER_ROWS = 3  # skill line, description, pane titles
VIEWER_FOOTER = "j/k move   Enter/l open   h up   Tab switch pane   J/K scroll text   d diff   q back"
TEXT_FOOTER = "j/k PgUp/PgDn scroll   h/l sideways   g/G top/bottom   q back"


def pick_root(status, side: str = "repo") -> Tuple[Optional[str], str]:
    """(directory or file to show, "repo"/"installed") for a row; the preferred side wins."""
    inst = status.installed
    disk = None
    if inst is not None and inst.kind in ("dir", "symlink", "file"):
        disk = inst.resolved or inst.path
    repo = status.source.path if status.source is not None else None
    ordered = ((disk, "installed"), (repo, "repo")) if side == "installed" else ((repo, "repo"), (disk, "installed"))
    for path, label in ordered:
        if path:
            return path, label
    return None, "nothing"


# ---------------------------------------------------------------- text pager


class TextScreen(Screen):
    """Read-only scrollable text (a diff, an issue detail). ``Esc`` or ``q`` closes it."""

    tab = None

    def __init__(self, title: str, lines: Sequence[str], kind: str = "text") -> None:
        self.title = title
        self.pane = TextPane.make(title, lines, kind)
        self._height = DEFAULT_HEIGHT
        self._width = 78

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, TEXT_FOOTER)
        self._height, self._width = height, width
        self.pane = self.pane.scrolled(self.pane.top, height).panned(self.pane.left, width)
        draw.draw_text(stdscr, y0, x0, height, width, self.pane.visible(height), 0, self.pane.left)

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key == ESC:
                return POP
            if key in (ord("h"), curses.KEY_LEFT):
                self.pane = self.pane.panned(self.pane.left - PAN_STEP, self._width)
            elif key in (ord("l"), curses.KEY_RIGHT):
                self.pane = self.pane.panned(self.pane.left + PAN_STEP, self._width)
            else:
                top = draw.scroll_key(key, self.pane.top, len(self.pane.lines), self._height)
                if top is not None:
                    self.pane = self.pane.scrolled(top, self._height)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None


# -------------------------------------------------------------------- viewer


class ViewerScreen(Screen):
    """Header, a tree pane and a text pane. Tab moves the focus between the panes."""

    tab = None

    def __init__(self, status, side: str = "repo", show_diff: bool = False) -> None:
        self.status = status
        self.title = f"{status.scope}/{status.name}"
        self.root_path, self.copy_label = pick_root(status, side)
        self.focus = "tree"
        self.tree: Optional[tree_mod.TreeNode] = None
        self.expanded: FrozenSet[str] = frozenset()
        self.tree_model: ListModel = ListModel()
        self.pane = TextPane.make("", ())
        self.showing_diff = False
        self._open_diff = show_diff
        self._loaded = False
        self._tree_h = self._text_h = DEFAULT_HEIGHT
        self._text_w = 48

    # --------------------------------------------------------------- loading

    def on_enter(self, app) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self.root_path is None:
            self.pane = TextPane.make("", ("[nothing on disk to show for this row]",))
            return
        self.tree = tree_mod.build_tree(self.root_path)
        self.expanded = frozenset((self.tree.path,))
        self._refresh_rows()
        self._open_skill_md()
        if self._open_diff:
            self._toggle_diff(app)

    def _refresh_rows(self) -> None:
        rows = tree_rows(self.tree, self.expanded)
        self.tree_model = self.tree_model.with_items(rows).move(0, self._tree_h)

    def _open_skill_md(self) -> None:
        rows = self.tree_model.items
        position = find_named(rows, "SKILL.md")
        if position is not None:
            self.tree_model = place(self.tree_model, position, self._tree_h)
            self._show_file(rows[position].node)
        elif self.tree is not None and not self.tree.is_dir:
            self._show_file(self.tree)

    def _show_file(self, node: tree_mod.TreeNode) -> None:
        root = self.tree.path if self.tree is not None and self.tree.is_dir else os.path.dirname(node.path)
        self.pane = TextPane.make(os.path.relpath(node.path, root), read_text_file(node.path))
        self.showing_diff = False

    def _toggle_diff(self, app) -> None:
        if self.showing_diff:
            self._open_skill_md()
            return
        pane, why = diff_pane(self.status)
        if pane is None:
            app.set_message(why)
            return
        self.pane, self.showing_diff = pane, True

    # ----------------------------------------------------------------- tree

    def _set_expanded(self, expanded: FrozenSet[str]) -> None:
        self.expanded = expanded
        self._refresh_rows()

    def _open(self, app, toggle: bool) -> None:
        row = self.tree_model.current()
        if row is None:
            return
        node = row.node
        if not node.is_dir:
            self._show_file(node)
        elif not node.children:
            app.set_message("symlinked directory (not followed)" if node.is_link else "empty directory")
        elif node.path not in self.expanded:
            self._set_expanded(self.expanded | frozenset((node.path,)))
        elif toggle and row.depth > 0:
            self._set_expanded(self.expanded - frozenset((node.path,)))
        elif not toggle:
            self.tree_model = self.tree_model.move(1, self._tree_h)

    def _collapse(self) -> None:
        row = self.tree_model.current()
        if row is None:
            return
        if row.node.is_dir and row.node.path in self.expanded and row.depth > 0:
            self._set_expanded(self.expanded - frozenset((row.node.path,)))
            return
        parent = parent_position(self.tree_model.items, self.tree_model.cursor)
        if parent is not None:
            self.tree_model = place(self.tree_model, parent, self._tree_h)

    def _tree_key(self, key: int, app) -> None:
        moved = move_model(self.tree_model, key, self._tree_h)
        if moved is not None:
            self.tree_model = moved
        elif key in ENTER_KEYS:
            self._open(app, toggle=True)
        elif key in (ord("l"), curses.KEY_RIGHT):
            self._open(app, toggle=False)
        elif key in (ord("h"), curses.KEY_LEFT):
            self._collapse()

    # ------------------------------------------------------------------ text

    def _scroll_by(self, delta: int) -> None:
        self.pane = self.pane.scrolled(self.pane.top + delta, self._text_h)

    def _text_key(self, key: int) -> None:
        if key in (ord("h"), curses.KEY_LEFT):
            self.pane = self.pane.panned(self.pane.left - PAN_STEP, self._text_w)
        elif key in (ord("l"), curses.KEY_RIGHT):
            self.pane = self.pane.panned(self.pane.left + PAN_STEP, self._text_w)
        else:
            top = draw.scroll_key(key, self.pane.top, len(self.pane.lines), self._text_h)
            if top is not None:
                self.pane = self.pane.scrolled(top, self._text_h)

    # ------------------------------------------------------------------ keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key == ESC:
                return POP
            if key in (KEY_TAB, curses.KEY_BTAB):
                self.focus = "text" if self.focus == "tree" else "tree"
            elif key == ord("d"):
                self._toggle_diff(app)
            elif key in (ord("J"), ord("K")):
                self._scroll_by(1 if key == ord("J") else -1)
            elif self.focus == "tree":
                self._tree_key(key, app)
            else:
                self._text_key(key)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    # ------------------------------------------------------------------ draw

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, VIEWER_FOOTER)
        self._draw_header(stdscr, y0, x0, width)
        left_w = min(LEFT_WIDTH, max(10, width // 2))
        right_w = max(1, width - left_w - 1)
        body_y, body_h = y0 + HEADER_ROWS, max(1, height - HEADER_ROWS)
        self._tree_h = self._text_h = body_h
        self._text_w = right_w
        self.tree_model = self.tree_model.move(0, body_h)
        self.pane = self.pane.scrolled(self.pane.top, body_h).panned(self.pane.left, right_w)
        self._draw_titles(stdscr, y0 + 2, x0, left_w, right_w)
        draw.draw_list(stdscr, body_y, x0, body_h, left_w, self.tree_model, self._tree_row,
                       focused=self.focus == "tree")
        for line in range(body_h):
            draw.safe_addstr(stdscr, body_y + line, x0 + left_w, "|", draw.attr("dim"))
        visible = self.pane.visible(body_h)
        draw.draw_text(stdscr, body_y, x0 + left_w + 1, body_h, right_w, visible, 0, self.pane.left)

    def _draw_header(self, stdscr, y0: int, x0: int, width: int) -> None:
        status = self.status
        segments = [(self.title, "title"), (f"  {status.state.value}", STATE_ATTR[status.state]),
                    (f"  {self.copy_label} copy", "dim")]
        if status.has_remote_update:
            segments.append((f"  {draw.glyph('remote')} changed upstream", "warn"))
        draw.draw_segments(stdscr, y0, x0, segments, width)
        draw.safe_addstr(stdscr, y0 + 1, x0, one_line(status.description), draw.attr("dim"), width)

    def _draw_titles(self, stdscr, y: int, x0: int, left_w: int, right_w: int) -> None:
        tree_on = self.focus == "tree"
        files = sum(1 for row in self.tree_model.items if not row.node.is_dir)
        draw.safe_addstr(stdscr, y, x0, draw.truncate(f"Files ({files} shown)", left_w),
                         draw.attr("title" if tree_on else "dim"), left_w)
        title = f"{self.pane.title}  {self.pane.position(self._text_h)}"
        draw.safe_addstr(stdscr, y, x0 + left_w + 1, draw.truncate(title, right_w),
                         draw.attr("dim" if tree_on else "title"), right_w)

    @staticmethod
    def _tree_row(row, selected: bool, width: int) -> Tuple[str, int]:
        return row_label(row, width), draw.attr("title") if row.node.is_dir else 0
