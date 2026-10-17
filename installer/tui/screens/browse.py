"""Tab 2 (Skills): the repo catalog with multi-select, install and update.

Rows are every status that has a repo source (foreign and tool-managed entries are not in
the catalog). ``i`` installs the selected rows, or the row under the cursor; ``u`` updates
modified ones. Both only build a plan and hand it to ``App.confirm``.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from installer.core.types import State
from installer.tui import draw
from installer.tui.screens.viewer import ViewerScreen
from installer.tui.screens.viewer_panes import (
    ENTER_KEYS, STATE_ATTR, SkillListScreen, one_line, select_box, state_glyph, status_search,
)

NAME_WIDTH = 30
STATE_WIDTH = 13  # fits "not-installed"
FOOTER = ("space select   a all   n none   / filter   i install   u update   Enter view   "
          "R recheck   q back")


class BrowseScreen(SkillListScreen):
    title = "Skills"
    tab = 2
    footer = FOOTER

    def __init__(self) -> None:
        super().__init__(status_search)

    def build_rows(self, app) -> Sequence:
        hidden = (State.FOREIGN, State.IGNORED)
        return tuple(s for s in app.statuses if s.source is not None and s.state not in hidden)

    def empty_text(self, app) -> str:
        return "the repo catalog is empty (check the repo path in the header)"

    def row_text(self, status, selected: bool, width: int) -> Tuple[str, int]:
        remote = draw.glyph("remote") if status.has_remote_update else " "
        head = (f"{select_box(selected)} {state_glyph(status)} {status.scope:<6} "
                f"{status.name:<{NAME_WIDTH}.{NAME_WIDTH}} {status.state.value:<{STATE_WIDTH}} {remote} ")
        return draw.truncate(head + one_line(status.description), width), draw.attr(STATE_ATTR[status.state])

    def on_key(self, key: int, app) -> Optional[str]:
        if key == ord("i"):
            self.act("install", app)
        elif key == ord("u"):
            self.act("update", app)
        elif key in ENTER_KEYS:
            current = self.model.current()
            if current is not None:
                app.push(ViewerScreen(current))
        return None
