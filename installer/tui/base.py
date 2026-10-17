"""Interfaces every screen and the App share. Screens import only this module,
``installer.tui.draw`` and ``installer.tui.listmodel`` from the tui package.

The App (``installer/tui/app.py``) exposes, as plain attributes:

    paths        installer.core.paths.Paths
    config       installer.core.config.Config
    caps         installer.core.capabilities.Capabilities
    context      Mapping from installer.core.render.build_context
    catalog      Dict[(scope, name)] -> SkillSource
    repo_issues  Tuple[RepoIssue, ...]
    installed    Dict[(scope, name)] -> InstalledSkill
    statuses     Tuple[SkillStatus, ...]
    git          installer.core.types.GitInfo
    remote       Dict[(scope, name)] -> RemoteChange
    extras       Tuple[ExtraStatus, ...]
    message      str  (one transient line shown in the footer; cleared on next key)
    tabs         Tuple[Tuple[int, str], ...]  ((1, "Overview"), (2, "Skills"), ...)
    active_tab   int

and these methods:

    push(screen) / pop() / replace(screen)      screen stack
    goto_tab(number)                             replace the stack with that tab's screen
    rescan()                                     recompute catalog/installed/statuses/extras (no git fetch)
    refresh_git() / fetch() / pull()             git.detect / git.fetch + remote_changes / pull_ff, then rescan
    set_message(text)
    confirm(ops, title, on_done=None)            push ConfirmScreen; on 'y' apply, show results, call on_done, rescan
    run_command(argv, title, cwd=None)           push an OutputScreen that streams the command's output
    suspend()                                    context manager: curses endwin() ... reset; used to run $EDITOR
    reload_config()                              re-read ~/.agents/config.json and rebuild context
"""

from __future__ import annotations

from typing import Optional


class Screen:
    """Base class for screens. Subclasses override draw() and handle_key()."""

    title: str = ""
    tab: Optional[int] = None  # the tab number this screen represents, or None for dialogs

    def on_enter(self, app) -> None:
        """Called when the screen becomes the top of the stack."""

    def draw(self, stdscr, app) -> None:
        raise NotImplementedError

    def handle_key(self, key: int, app) -> Optional[str]:
        """Return "pop" to close this screen, "quit" to exit the app, or None."""
        return None

    def editing(self) -> bool:
        """True while a filter or prompt owns the keyboard (global keys are suspended)."""
        return False


# Return values a screen may hand back from handle_key().
POP = "pop"
QUIT = "quit"

# Tab numbering is fixed so every screen can label its chrome the same way.
TABS = (
    (1, "Overview"),
    (2, "Skills"),
    (3, "Installed"),
    (4, "Issues"),
    (5, "Updates"),
    (6, "Settings"),
    (7, "Files"),
    (8, "Install"),
    (9, "Extras"),
    (10, "Workflows"),  # reached with key "0"
)
