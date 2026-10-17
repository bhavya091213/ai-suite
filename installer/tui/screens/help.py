"""Scrollable key reference covering every screen."""

from __future__ import annotations

from typing import List, Optional, Tuple

from installer.tui import draw
from installer.tui.base import POP, QUIT, Screen
from installer.tui.screens.skill_picker import OwnedScreen

NamedLine = Tuple[str, str]  # (text, attr name)
ESC = 27

# (heading, ((keys, what it does), ...))
SECTIONS = (
    ("Everywhere", (
        ("q", "back; quits from a top-level tab"),
        ("Q", "quit"),
        ("?", "this help"),
        ("R", "recheck tools, git, config and the disk"),
        ("F", "git fetch, then show what changed upstream"),
        ("1 .. 9, 0", "jump to a tab (1 Overview .. 9 Extras, 0 Workflows)"),
        ("Tab / Shift-Tab", "next / previous tab (not inside the viewer)"),
        ("Resize", "just redraws; the terminal must be at least 80x24"),
    )),
    ("Lists (Skills, Installed, Issues, Updates, Extras)", (
        ("j k / arrows", "move the cursor"),
        ("PgUp PgDn", "page up / down"),
        ("g G", "first / last row"),
        ("space", "toggle selection of the row"),
        ("a  n", "select all visible / select none"),
        ("/", "filter by text (Esc clears)"),
        ("Enter", "open the row (viewer, details)"),
    )),
    ("1 Overview", (
        ("S", "start the setup wizard"),
        ("c", "detected tools with install hints"),
        ("j k", "scroll when the terminal is short"),
    )),
    ("2 Skills", (
        ("i", "install the selected skills (or the current one)"),
        ("Enter", "open the viewer"),
    )),
    ("3 Installed", (
        ("u", "update a modified skill from the repo (old copy is backed up)"),
        ("r", "retire: move to a backup, never delete"),
        ("l", "relink shared skills into Claude and Codex"),
        ("p", "push the installed copy back into the repo"),
        ("d", "diff repo against installed"),
        ("x", "unlink from the tools but keep the shared copy"),
    )),
    ("4 Issues", (
        ("Enter", "show every problem text for the row"),
        ("l  r", "relink / retire the row"),
    )),
    ("5 Updates", (
        ("F", "fetch from the remote"),
        ("P", "pull --ff-only (asks first), then rescan"),
    )),
    ("6 Settings", (
        ("Enter / space", "toggle a bool, cycle an enum, edit text or numbers inline"),
        ("a x d o", "in list editors: add / remove / make default / import Obsidian vaults"),
        ("s", "save (the previous file is backed up)"),
        ("A", "apply: re-render and install, output in a pane"),
        ("R", "reload from disk"),
        ("n p", "wizard: next / previous section"),
    )),
    ("7 Files", (
        ("Enter / e", "open in your editor (the terminal UI suspends)"),
        ("v  d  c", "view here / diff against the repo / create from the example"),
    )),
    ("8 Install", (
        ("s c x", "toggle shared / claude / codex sections"),
        ("D  A", "dry run / apply ./install.sh (A asks first)"),
    )),
    ("9 Extras", (
        ("Enter", "details, commands and the after-install note"),
        ("i", "install; third-party code runs only after you confirm"),
        ("o", "show the URL on the message line"),
    )),
    ("10 Workflows (key 0)", (
        ("Enter / e", "open the workflow in the editor"),
        ("n  N", "new blank workflow / new one started from the example"),
        ("r", "retire: move the workflow to a backup, never delete"),
        ("p", "push the installed workflow into the repo's shared/skills"),
        ("v", "view the rendered SKILL.md"),
        ("/", "filter by name or description (Esc clears)"),
    )),
    ("Workflow editor", (
        ("Enter / e", "edit the field under the cursor, or open the phase"),
        ("a  x", "add a phase after the current one / remove the current phase"),
        ("J  K", "move the current phase down / up"),
        ("s", "validate (errors block, warnings do not), then confirm and save"),
        ("q  Q", "back / quit; both ask for y while changes are unsaved"),
    )),
    ("Phase editor", (
        ("Enter / e", "edit a field or a line; on a heading it adds a line"),
        ("s", "open the skill picker"),
        ("t / space", "toggle the gate (space only on the Gate row)"),
        ("a  x  J  K", "steps and outputs: add / remove / move down / move up"),
        ("q", "back; every change is already in the workflow"),
    )),
    ("Skill picker", (
        ("space", "tick or untick the skill"),
        ("/  a  n", "filter / tick all shown / untick all"),
        ("Enter  q", "accept the ticked skills / cancel"),
    )),
    ("Viewer", (
        ("j k / Enter / l / h", "tree: move / expand or open / collapse"),
        ("J K / PgUp PgDn", "scroll the file text"),
        ("Tab", "switch focus between tree and text"),
        ("d", "show the diff when the skill is modified"),
    )),
    ("Dialogs", (
        ("y  n", "confirm: apply / cancel; any key returns after the log"),
        ("arrows PgUp PgDn", "scroll output; k stops it (asks); q closes when done"),
    )),
)


def legend_rows() -> Tuple[Tuple[str, str], ...]:
    return (
        (draw.glyph("installed"), "installed and identical to the repo"),
        (draw.glyph("missing"), "in the repo, not installed"),
        (draw.glyph("modified"), "installed but different from the repo"),
        (draw.glyph("foreign"), "installed, not in the repo"),
        (draw.glyph("remote"), "changed upstream, not pulled yet"),
        (draw.glyph("problem"), "has a problem or duplicate"),
        (draw.glyph("selected"), "selected for the next action"),
    )


def help_lines() -> Tuple[NamedLine, ...]:
    """The whole reference as (text, attr name) lines."""
    lines: List[NamedLine] = [("Skill installer - key reference", "title")]
    for heading, rows in SECTIONS:
        lines += [("", "normal"), (heading, "title")]
        lines += [(f"  {keys:<22}{text}", "normal") for keys, text in rows]
    lines += [("", "normal"), ("Symbols", "title")]
    lines += [(f"  {mark:<22}{text}", "normal") for mark, text in legend_rows()]
    lines += [("", "normal"), ("Nothing is ever deleted: replaced or retired items move under ~/.agents/backups/.", "dim")]
    return tuple(lines)


class HelpScreen(Screen):
    title = "Help"
    tab = None

    def __init__(self) -> None:
        self._top = 0
        self._height = 1

    def editing(self) -> bool:
        return True  # owns q / Esc / ? so the global keys do not fire underneath

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, "j/k scroll   q or Esc close")
        lines = help_lines()
        self._height = height
        self._top = draw.clamp_top(self._top, len(lines), height)
        shown = [(text, draw.attr(name)) for text, name in lines]
        draw.draw_text(stdscr, y0, x0, height, width, shown, self._top)

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key in (ord("q"), ord("?"), ESC, ord("\n")):
                return POP
            if key == ord("Q"):
                return self._quit(app)
            moved = draw.scroll_key(key, self._top, len(help_lines()), self._height)
            if moved is not None:
                self._top = moved
        except Exception as exc:  # noqa: BLE001
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _quit(self, app) -> Optional[str]:
        """``Q``: quit, unless an editor underneath owns the keyboard; then help closes and it answers.

        The editors keep ``Q`` from dropping unsaved work (the workflow editor asks for ``y``, the phase
        editor and the skill picker send the user back a level first), so help must not bypass that.
        """
        stack = app.stack
        under = stack[-2] if len(stack) > 1 and stack[-1] is self else None
        if not isinstance(under, OwnedScreen):
            return QUIT
        app.pop()
        return under.handle_key(ord("Q"), app)
