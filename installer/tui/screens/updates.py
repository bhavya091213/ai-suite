"""Tab 5 (Updates): git banner, commits behind the upstream and the skills they change.

``P`` starts a fast-forward pull and needs a second key, ``y``, to run: the pull rewrites the
repo checkout, so one stray key must not do it.

The two lists switch with ``h``/``l`` (or the arrows). ``F`` (fetch) and Tab / Shift-Tab (next and
previous tab) are global keys the App takes before any tab screen sees them, so this screen does
not handle them; the footer advertises ``h``/``l`` for the lists instead.
"""

from __future__ import annotations

import curses
import textwrap
import time
from typing import List, Optional, Tuple

from installer.core import git as git_mod
from installer.tui import draw
from installer.tui.base import Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.viewer import TextScreen
from installer.tui.screens.viewer_panes import DEFAULT_HEIGHT, ENTER_KEYS, move_model

COMMITS, SKILLS = "commits", "skills"
NAME_WIDTH = 28
FOOTER = "F fetch   P pull (fast-forward only)   h/l switch list   j/k move   Enter details   q back"
Row = Tuple[draw.Segment, ...]


def age_text(last_fetch: Optional[float], now: Optional[float] = None) -> str:
    """"fetched N min ago" / "never fetched" (hours and days once it is old)."""
    if last_fetch is None:
        return "never fetched"
    minutes = int(max(0.0, (time.time() if now is None else now) - last_fetch) // 60)
    if minutes < 1:
        return "fetched just now"
    if minutes < 120:
        return f"fetched {minutes} min ago"
    hours = minutes // 60
    return f"fetched {hours} h ago" if hours < 48 else f"fetched {hours // 24} days ago"


def banner_rows(info, width: int, now: Optional[float] = None) -> Tuple[Row, ...]:
    """Git status line, the wrapped hint (when there is one) and the last-fetch line."""
    rows: List[Row] = [(("Git: ", "title"), (info.message, draw.git_attr(info)))]
    if info.hint:
        rows += [((f"  {piece}", "warn"),) for piece in textwrap.wrap(info.hint, max(20, width - 4))]
    where = f"   {info.branch} @ {info.head}" if info.is_repo and info.branch else ""
    rows.append(((f"  {age_text(info.last_fetch, now)}{where}", "dim"),))
    return tuple(rows)


def pull_blocker(info) -> str:
    """Why a fast-forward pull cannot run right now ("" when it can)."""
    if not info.available:
        return "git is not available - " + (info.hint or "install git first")
    if not info.is_repo:
        return "this folder is not a git checkout"
    if info.upstream is None:
        return "no upstream branch configured - nothing to pull"
    if info.ahead and info.behind:
        return f"diverged (ahead {info.ahead}, behind {info.behind}): a fast-forward pull is not possible"
    if not info.behind:
        return f"already up to date with {info.upstream} (press F to fetch first)"
    return ""


def skill_line(status, width: int) -> str:
    change = status.remote
    files = len(change.files) if change is not None else 0
    latest = change.commits[0] if change is not None and change.commits else ""
    text = (f"{draw.glyph('remote')} {status.scope:<6} {status.name:<{NAME_WIDTH}.{NAME_WIDTH}} "
            f"{files:>3} file{'' if files == 1 else 's'}  {latest}")
    return draw.truncate(text, width)


def detail_lines(status) -> Tuple[str, ...]:
    change = status.remote
    out: List[str] = [f"{status.scope}/{status.name}: changed upstream"]
    if change is None:
        return tuple(out)
    out += [f"upstream: {change.upstream}", "", "Files:"] + [f"  {path}" for path in change.files]
    return tuple(out + ["", "Commits (newest first):"] + [f"  {line}" for line in change.commits])


class UpdatesScreen(Screen):
    title = "Updates"
    tab = 5

    def __init__(self) -> None:
        self.commits: ListModel = ListModel()
        self.skills: ListModel = ListModel(key_fn=lambda s: f"{s.scope} {s.name}")
        self.focus = COMMITS
        self.pull_armed = False
        self._heights = {COMMITS: DEFAULT_HEIGHT, SKILLS: DEFAULT_HEIGHT}

    # ------------------------------------------------------------------ data

    def on_enter(self, app) -> None:
        self.pull_armed = False
        self.reload(app)

    def on_rescan(self, app) -> None:
        self.pull_armed = False  # the data under the question changed (fetch, recheck, pull)
        self.reload(app)

    def reload(self, app) -> None:
        """Re-read the commit list (only worth a git call while we are behind) and the changed skills."""
        info = app.git
        behind = git_mod.commits_behind(app.paths) if info.available and info.is_repo and info.behind else ()
        self.commits = self.commits.with_items(behind)
        self.skills = self.skills.with_items(s for s in app.statuses if s.remote is not None)

    def _focused(self) -> ListModel:
        return self.commits if self.focus == COMMITS else self.skills

    def _set_focused(self, model: ListModel) -> None:
        if self.focus == COMMITS:
            self.commits = model
        else:
            self.skills = model

    # ------------------------------------------------------------------ draw

    def draw(self, stdscr, app) -> None:
        footer = self._prompt(app) if self.pull_armed else FOOTER
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, footer)
        banner = banner_rows(app.git, width)[:max(1, height - 6)]
        for offset, segments in enumerate(banner):
            draw.draw_segments(stdscr, y0 + offset, x0, segments, width)
        y = y0 + len(banner) + 1
        room = max(2, y0 + height - y - 2)  # list rows left after the two section headings
        first = (room + 1) // 2
        y = self._section(stdscr, y, x0, width, COMMITS, first, app)
        self._section(stdscr, y, x0, width, SKILLS, max(1, room - first), app)

    def _prompt(self, app) -> str:
        return f"Pull {app.git.upstream or 'upstream'} (fast-forward only)?  y = pull, any other key = cancel"

    def _section(self, stdscr, y: int, x0: int, width: int, which: str, height: int, app) -> int:
        """Heading plus list of one section; returns the row below it."""
        upstream = app.git.upstream or "upstream"
        count = (self.commits if which == COMMITS else self.skills).count
        label = (f"Commits behind {upstream} ({count})" if which == COMMITS
                 else f"Skills changed upstream ({count})")
        focused = self.focus == which
        draw.safe_addstr(stdscr, y, x0, label, draw.attr("title" if focused else "dim"), width)
        self._heights[which] = height
        model = (self.commits if which == COMMITS else self.skills).move(0, height)
        if which == COMMITS:
            self.commits = model
        else:
            self.skills = model
        if not model.count:
            draw.safe_addstr(stdscr, y + 1, x0, "  (none - press F to fetch)", draw.attr("dim"), width)
        draw.draw_list(stdscr, y + 1, x0, height, width, model, self._row_fn(which), focused=focused)
        return y + 1 + height

    @staticmethod
    def _row_fn(which: str):
        if which == COMMITS:
            return lambda item, selected, width: (draw.truncate("  " + item, width), 0)
        return lambda item, selected, width: (skill_line(item, width), draw.attr("warn"))

    # ------------------------------------------------------------------ keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if self.pull_armed:
                self._answer_pull(key, app)
            else:
                self._key(key, app)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _answer_pull(self, key: int, app) -> None:
        self.pull_armed = False
        if key not in (ord("y"), ord("Y")):
            app.set_message("pull cancelled")
            return
        app.pull()
        app.rescan()

    def _key(self, key: int, app) -> None:
        if key == ord("P"):
            self._arm_pull(app)
        elif key in (ord("h"), curses.KEY_LEFT):
            self.focus = COMMITS
        elif key in (ord("l"), curses.KEY_RIGHT):
            self.focus = SKILLS
        elif key in ENTER_KEYS:
            self._details(app)
        else:
            moved = move_model(self._focused(), key, self._heights[self.focus])
            if moved is not None:
                self._set_focused(moved)

    def _arm_pull(self, app) -> None:
        blocker = pull_blocker(app.git)
        if blocker:
            app.set_message(blocker)
            return
        self.pull_armed = True
        app.set_message(self._prompt(app))

    def _details(self, app) -> None:
        if self.focus != SKILLS:
            return
        status = self.skills.current()
        if status is not None:
            app.push(TextScreen(f"{status.scope}/{status.name}", detail_lines(status)))
