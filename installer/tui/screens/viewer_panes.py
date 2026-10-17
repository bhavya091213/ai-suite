"""Shared building blocks of the skill screens: Skills, Installed, Issues, Updates and the viewer.

It started as the viewer's helpers (file reading, the scrolling text pane, tree rows) and also
holds what the list screens have in common: ``SkillListScreen`` (cursor, multi-select, the "/"
filter), row formatting and ``run_action``, which turns a key press into plans for ``App.confirm``.
Screens may import only base, draw and listmodel from the tui package (tui/base.py), so the shared
code lives here, inside this unit, instead of in one of the screens.

Nothing here draws with curses directly. The text pane is an immutable value: every scroll
returns a new `TextPane`, so a screen only ever swaps references.
"""

from __future__ import annotations

import curses
import os
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Callable, FrozenSet, Mapping, Optional, Sequence, Tuple

from installer.core import actions
from installer.core import status as status_mod
from installer.core import tree as tree_mod
from installer.core.tree import Row
from installer.core.types import LinkState, Operation, State
from installer.tui import draw
from installer.tui.base import Screen
from installer.tui.listmodel import ListModel

MAX_BYTES = 2 * 1024 * 1024
BINARY_PROBE = 8192
LEFT_WIDTH = 30
PAN_STEP = 8
TRUNCATED_NOTICE = "[truncated: only the first 2 MB are shown]"
ESC = 27
KEY_TAB = 9
ENTER_KEYS = (10, 13, curses.KEY_ENTER)
DEFAULT_HEIGHT = 20  # list height assumed until the first draw reports the real one


# ------------------------------------------------------------------ files


def read_text_file(path: str, cap: int = MAX_BYTES) -> Tuple[str, ...]:
    """Lines of `path` decoded as UTF-8 (bad bytes replaced), reading at most `cap` bytes.

    Unreadable and binary files come back as a single bracketed notice line, so
    the pane always has something truthful to show.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read(cap + 1)
    except OSError as exc:
        return (f"[cannot read {os.path.basename(path)}: {exc.strerror or exc}]",)
    truncated = len(data) > cap
    data = data[:cap]
    if b"\0" in data[:BINARY_PROBE]:
        return ("[binary file - not shown]",)
    lines = tuple(data.decode("utf-8", errors="replace").splitlines())
    return lines + ((TRUNCATED_NOTICE,) if truncated else ())


def diff_attr(line: str) -> str:
    """Colour name (draw.attr) for one line of core.status.diff_text output."""
    if line.startswith(("+++", "---")):
        return "title"
    if line.startswith("@@") or line.startswith(("only in repo:", "only installed:", "changed:")):
        return "warn"
    if line.startswith("+"):
        return "ok"
    if line.startswith("-"):
        return "error"
    return "normal"


# -------------------------------------------------------------- text pane


@dataclass(frozen=True)
class TextPane:
    """Lines plus a scroll position. `kind` is "text" or "diff" (diff lines are coloured)."""

    title: str = ""
    lines: Tuple[str, ...] = ()
    top: int = 0
    left: int = 0
    kind: str = "text"
    widest: int = 0

    @classmethod
    def make(cls, title: str, lines, kind: str = "text") -> "TextPane":
        lines = tuple(lines)
        widest = max((len(line.expandtabs(4)) for line in lines), default=0)
        return cls(title=title, lines=lines, kind=kind, widest=widest)

    def scrolled(self, top: int, height: int) -> "TextPane":
        return replace(self, top=draw.clamp_top(top, len(self.lines), height))

    def panned(self, left: int, width: int) -> "TextPane":
        return replace(self, left=max(0, min(left, self.widest - max(1, width))))

    def visible(self, height: int) -> Tuple[draw.Line, ...]:
        """The `height` lines from `top`, as (text, attr) pairs when they are coloured."""
        chunk = self.lines[self.top:self.top + max(0, height)]
        if self.kind != "diff":
            return chunk
        return tuple((line, draw.attr(diff_attr(line))) for line in chunk)

    def position(self, height: int) -> str:
        """"first-last/total" for the pane title ("empty" when there are no lines)."""
        total = len(self.lines)
        if not total:
            return "empty"
        return f"{self.top + 1}-{min(total, self.top + max(1, height))}/{total}"


# ------------------------------------------------------------- list moves


def move_model(model: ListModel, key: int, height: int) -> Optional[ListModel]:
    """Cursor-only keys (j/k, arrows, paging, g/G); None when `key` is not one of them."""
    if key in (ord("j"), curses.KEY_DOWN):
        return model.move(1, height)
    if key in (ord("k"), curses.KEY_UP):
        return model.move(-1, height)
    if key == curses.KEY_NPAGE:
        return model.page(1, height)
    if key == curses.KEY_PPAGE:
        return model.page(-1, height)
    if key in (ord("g"), curses.KEY_HOME):
        return model.home(height)
    if key in (ord("G"), curses.KEY_END):
        return model.end(height)
    return None


# ------------------------------------------------------------------- tree


def tree_rows(root, expanded) -> Tuple[Row, ...]:
    """Visible rows of `root` with box-drawing guides (ASCII ones on a non-UTF-8 terminal)."""
    return tree_mod.flatten(root, expanded, ascii_only=not draw.use_unicode())


def row_label(row: Row, width: int) -> str:
    return draw.truncate(row.prefix + tree_mod.label(row.node), width)


def parent_position(rows: Tuple[Row, ...], index: int) -> Optional[int]:
    """Index of the closest row above `index` that is one level shallower, if any."""
    if not 0 <= index < len(rows):
        return None
    depth = rows[index].depth
    for position in range(index - 1, -1, -1):
        if rows[position].depth == depth - 1:
            return position
    return None


def find_named(rows: Tuple[Row, ...], name: str, depth: int = 1) -> Optional[int]:
    """Index of the first row called `name` at `depth` (1 = directly inside the root)."""
    for position, row in enumerate(rows):
        if row.depth == depth and row.node.name == name:
            return position
    return None


def place(model: ListModel, position: int, height: int) -> ListModel:
    """Move the cursor of `model` to row `position` (clamped), scrolling only if needed."""
    return model.move(position - model.cursor, height)


# --------------------------------------------------------------- diff pane


def diff_pane(status) -> Tuple[Optional[TextPane], str]:
    """(pane, "") with the repo -> installed diff of a MODIFIED row, else (None, why not)."""
    if status.state != State.MODIFIED or status.source is None or status.installed is None:
        return None, f"nothing to diff: {status.name} is {status.state.value} (diff needs a modified skill)"
    text = status_mod.diff_text(status.source, status.installed)
    if not text.strip():
        return None, f"no differences found for {status.name}"
    title = f"diff {status.scope}/{status.name} (repo -> installed)"
    return TextPane.make(title, text.splitlines(), kind="diff"), ""


# ---------------------------------------------------------- row formatting

_STATE_GLYPH: Mapping[State, str] = MappingProxyType({
    State.INSTALLED: "installed", State.NOT_INSTALLED: "missing", State.MODIFIED: "modified",
    State.FOREIGN: "foreign", State.IGNORED: "bullet",
})
STATE_ATTR: Mapping[State, str] = MappingProxyType({
    State.INSTALLED: "ok", State.NOT_INSTALLED: "normal", State.MODIFIED: "warn",
    State.FOREIGN: "warn", State.IGNORED: "dim",
})
_LINK_GLYPH: Mapping[LinkState, str] = MappingProxyType({LinkState.OK: "yes", LinkState.MISSING: "missing"})


def state_glyph(status) -> str:
    return draw.glyph(_STATE_GLYPH[status.state])


def link_summary(status) -> str:
    """"claude ✓ codex !" for a shared row; empty for the platform scopes."""
    return " ".join(f"{link.consumer} {draw.glyph(_LINK_GLYPH.get(link.state, 'problem'))}"
                    for link in status.links)


def select_box(selected: bool) -> str:
    return f"[{draw.glyph('selected') if selected else ' '}]"


def one_line(text: str) -> str:
    return " ".join(str(text).split())


def status_search(status) -> str:
    """Text the "/" filter matches a skill row against."""
    return f"{status.scope} {status.name} {status.state.value} {one_line(status.description)}"


# ------------------------------------------------------------------ actions


def _why_install(s) -> str:
    if s.source is None:
        return "not in the repo"
    return f"already {s.state.value}" + (", press u to update" if s.state == State.MODIFIED else "")


def _why_update(s) -> str:
    if s.source is None:
        return "not in the repo, nothing to update from"
    return "not installed, press i" if s.state == State.NOT_INSTALLED else "already up to date"


def _why_unlink(s) -> str:
    return "only shared skills have tool links, use r" if s.scope != "shared" else "no tool links point at it"


def _why_relink(s) -> str:
    if s.scope != "shared":
        return "only shared skills have links"
    if s.installed is None:
        return "not installed, press i first"
    own = [link for link in s.links if link.state in (LinkState.REAL_DIR, LinkState.FILE)]
    if own:
        return f"{own[0].consumer} has its own {own[0].state.value}, left alone (use r or p)"
    return "links already fine"


def _why_push(s) -> str:
    if s.installed is None:
        return "not installed"
    return "nothing to push (a link, a file, or it already is the repo copy)"


@dataclass(frozen=True)
class ActionSpec:
    verb: str
    root_label: str  # backup_root(label): retire/unlink use "retired-skills", the rest "installer"
    planner: Callable[[Any, Any, str], Tuple[Operation, ...]]  # (status, app, backup_root)
    reason: Callable[[Any], str]  # why the planner returned nothing
    tail: str = ""  # appended to the confirm title


ACTIONS: Mapping[str, ActionSpec] = MappingProxyType({
    "install": ActionSpec("install", "installer", lambda s, app, root: actions.plan_install(s, app.paths),
                          _why_install),
    "update": ActionSpec("update", "installer", lambda s, app, root: actions.plan_update(s, app.paths, root),
                         _why_update),
    "retire": ActionSpec("retire", "retired-skills", lambda s, app, root: actions.plan_retire(s, app.paths, root),
                         lambda s: "not installed"),
    "unlink": ActionSpec("unlink", "retired-skills",
                         lambda s, app, root: actions.plan_retire(s, app.paths, root, consumers_only=True),
                         _why_unlink, " from the tools"),
    "relink": ActionSpec("relink", "installer",
                         lambda s, app, root: actions.plan_relink(s, app.paths, root, installed_index=app.installed),
                         _why_relink),
    "push": ActionSpec("push", "installer", lambda s, app, root: actions.plan_push_to_repo(s, app.paths, root),
                       _why_push, " to the repo"),
})


def skip_reason(action: str, status) -> str:
    if status.state == State.IGNORED:
        return "tool-managed, never touched"
    return ACTIONS[action].reason(status)


def action_title(spec: ActionSpec, rows: Sequence[Any]) -> str:
    what = f"{rows[0].scope}/{rows[0].name}" if len(rows) == 1 else f"{len(rows)} skills"
    return f"{spec.verb.capitalize()} {what}{spec.tail}"


MOVE_KINDS = ("backup", "unlink-to-backup")


def plan_claims(steps: Sequence[Operation]) -> FrozenSet[str]:
    """Paths a row's plan writes or moves away. ``mkdir`` only ensures a parent, so it claims nothing."""
    claimed = set()
    for op in steps:
        if op.kind == "mkdir":
            continue
        claimed.add(os.path.normpath(op.dst))
        if op.kind in MOVE_KINDS and op.src:
            claimed.add(os.path.normpath(op.src))
    return frozenset(claimed)


def _plan_rows(app, action: str, rows: Sequence[Any], root: str):
    """(ops, planned rows, skipped notes). A row whose plan touches a path an earlier row already
    claimed is skipped: applying both would stop at the second one halfway through the batch."""
    spec = ACTIONS[action]
    ops: Tuple[Operation, ...] = ()
    planned: Tuple[Any, ...] = ()
    skipped: Tuple[str, ...] = ()
    owners: Mapping[str, str] = {}
    for row in rows:
        steps = spec.planner(row, app, root)
        claims = plan_claims(steps)
        clash = next((path for path in sorted(claims) if path in owners), None)
        if not steps:
            skipped += (f"{row.name} ({skip_reason(action, row)})",)
        elif clash is not None:
            skipped += (f"{row.name} (same path as {owners[clash]}: {app.paths.display(clash)})",)
        else:
            ops, planned = ops + steps, planned + (row,)
            owners = {**owners, **{path: f"{row.scope}/{row.name}" for path in claims}}
    return ops, planned, skipped


def run_action(app, action: str, rows: Sequence[Any], on_done: Optional[Callable[..., Any]] = None) -> bool:
    """Plan `action` for each status row and hand the plans to ``app.confirm``.

    Rows with nothing to do, or whose plan collides with an earlier row's, are skipped and named
    on the message line with the reason. Returns True when a confirm dialog was pushed. An empty
    plan never reaches the dialog.
    """
    spec = ACTIONS[action]
    if not rows:
        app.set_message(f"nothing to {spec.verb}: no row selected")
        return False
    ops, planned, skipped = _plan_rows(app, action, rows, app.paths.backup_root(spec.root_label))
    if not ops:
        app.set_message(f"nothing to {spec.verb}: " + "; ".join(skipped))
        return False
    if skipped:
        app.set_message(f"skipped {len(skipped)}: " + "; ".join(skipped))
    app.confirm(ops, action_title(spec, planned), on_done=on_done)
    return True


# -------------------------------------------------------------- list screens


class SkillListScreen(Screen):
    """Cursor, multi-select and the "/" filter shared by Skills, Installed and Issues.

    Subclasses provide ``build_rows`` (items from the App's data), ``row_text`` and ``on_key``
    (their own keys). Items need a ``key`` so the selection survives a rescan.
    """

    footer = ""

    def __init__(self, key_fn: Callable[[Any], str] = str) -> None:
        self.model: ListModel = ListModel(key_fn=key_fn)
        self._height = DEFAULT_HEIGHT
        self._filtering = False
        self._pos = 0

    # ------------------------------------------------------- subclass hooks

    def build_rows(self, app) -> Sequence[Any]:
        raise NotImplementedError

    def row_text(self, item, selected: bool, width: int) -> Tuple[str, int]:
        raise NotImplementedError

    def on_key(self, key: int, app) -> Optional[str]:
        return None

    def empty_text(self, app) -> str:
        return "nothing to show"

    # --------------------------------------------------------------- data

    def editing(self) -> bool:
        return self._filtering

    def on_enter(self, app) -> None:
        self.reload(app)

    def on_rescan(self, app) -> None:
        self.reload(app)

    def reload(self, app) -> None:
        """Rebuild the rows from the App; keep the cursor, the filter and the selection (by key)."""
        wanted = frozenset(item.key for item in self.model.selected_items())
        model = self.model.with_items(self.build_rows(app))
        keep = frozenset(i for i, item in enumerate(model.items) if item.key in wanted)
        self.model = replace(model, selected=keep)

    def targets(self) -> Tuple[Any, ...]:
        chosen = self.model.selected_items()
        if chosen:
            return chosen
        current = self.model.current()
        return () if current is None else (current,)

    def act(self, action: str, app) -> None:
        """Run `action` on the selected rows, else on the row under the cursor."""
        run_action(app, action, self.targets(), on_done=self._after_action)

    def _after_action(self) -> None:
        self.model = self.model.select_none()

    # ------------------------------------------------------------- drawing

    def footer_text(self) -> str:
        if self._filtering:
            return f"/{self.model.query}_   Enter keep the filter   Esc clear it"
        return self.footer

    def status_line(self) -> str:
        shown = f"{self.model.filtered_count}/{self.model.count} shown   {self.model.selected_count} selected"
        return shown + (f"   filter: {self.model.query}" if self.model.query else "")

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, self.footer_text())
        body = max(1, height - 1)
        self._height = body
        self.model = self.model.move(0, body)
        if not self.model.filtered_count:
            text = self.empty_text(app) if not self.model.query else "no rows match the filter"
            draw.safe_addstr(stdscr, y0, x0, text, draw.attr("dim"), width)
        draw.draw_list(stdscr, y0, x0, body, width, self.model, self.row_text)
        draw.safe_addstr(stdscr, y0 + height - 1, x0, self.status_line(), draw.attr("dim"), width)

    # ---------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if self._filtering:
                self._filter_key(key)
            elif not self._list_key(key):
                return self.on_key(key, app)
        except Exception as exc:  # noqa: BLE001 - report on the message line, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _list_key(self, key: int) -> bool:
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
        elif key == ESC and self.model.query:
            self.model = self.model.set_query("")
        else:
            return False
        return True

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
