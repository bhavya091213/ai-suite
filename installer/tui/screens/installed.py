"""Tab 3 (Installed): what is on disk, with update / retire / relink / unlink / push / diff.

Rows are the statuses with an installed entry; tool-managed (IGNORED) entries are listed last
and dimmed, and refuse every action. Shared rows show how each tool links to them
("claude ✓ codex !"). Every mutating key builds a plan and hands it to ``App.confirm``.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from installer.core.types import State
from installer.tui import draw
from installer.tui.screens.viewer import TextScreen, ViewerScreen
from installer.tui.screens.viewer_panes import (
    ENTER_KEYS, STATE_ATTR, SkillListScreen, diff_pane, link_summary, one_line, select_box,
    state_glyph, status_search,
)

KIND_TEXT = {"dir": "dir", "symlink": "link", "broken-symlink": "brkn", "file": "file"}
STATE_WIDTH = 13
LINKS_WIDTH = 16  # "claude ✓ codex !"
FIXED_WIDTH = 50  # every column but the name and the description
FOOTER = ("space select   / filter   u update   r retire   l relink   x unlink   p push to repo   "
          "d diff   Enter view")


def name_width(width: int) -> int:
    """Room for the name: the rest of the line minus ~10 columns of description, 14..30."""
    return max(14, min(30, width - FIXED_WIDTH - 10))


class InstalledScreen(SkillListScreen):
    title = "Installed"
    tab = 3
    footer = FOOTER

    def __init__(self) -> None:
        super().__init__(status_search)

    def build_rows(self, app) -> Sequence:
        live = tuple(s for s in app.statuses if s.installed is not None and s.state != State.IGNORED)
        ignored = tuple(s for s in app.statuses if s.state == State.IGNORED)
        return live + ignored

    def empty_text(self, app) -> str:
        return "nothing is installed yet - press 2 to browse the catalog"

    def row_text(self, status, selected: bool, width: int) -> Tuple[str, int]:
        installed = status.installed
        kind = KIND_TEXT.get(installed.kind, "?") if installed is not None else ""
        detail = one_line(status.description or (installed.ignored_reason if installed else "") or "")
        room = name_width(width)
        head = (f"{select_box(selected)} {state_glyph(status)} {status.scope:<6} {status.name:<{room}.{room}} "
                f"{kind:<4} {status.state.value:<{STATE_WIDTH}} {link_summary(status):<{LINKS_WIDTH}} ")
        return draw.truncate(head + detail, width), draw.attr(STATE_ATTR[status.state])

    def on_key(self, key: int, app) -> Optional[str]:
        action = {ord("u"): "update", ord("r"): "retire", ord("l"): "relink",
                  ord("x"): "unlink", ord("p"): "push"}.get(key)
        if action is not None:
            self.act(action, app)
            return None
        current = self.model.current()
        if current is None:
            return None
        if key == ord("d"):
            self._diff(current, app)
        elif key in ENTER_KEYS:
            app.push(ViewerScreen(current, side="installed"))
        return None

    @staticmethod
    def _diff(status, app) -> None:
        pane, why = diff_pane(status)
        if pane is None:
            app.set_message(why)
        else:
            app.push(TextScreen(pane.title, pane.lines, kind="diff"))
