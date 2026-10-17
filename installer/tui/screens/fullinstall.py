"""Tab 8: run ./install.sh (rules, agents, commands, hooks, shared skills links) from the TUI.

Sections map to install.sh flags (``--shared`` ``--claude`` ``--codex``). The defaults follow
the same logic as ``python3 -m installer sections``: shared always, a tool only when its
``tools.*`` setting resolves to on. ``D`` previews with ``--dry-run``; ``A`` installs for real
after a ``y``. Output streams into the App's command pane; the working directory is the repo.

``install.sh`` writes to ``$HOME/.agents``, ``$HOME/.claude`` and ``$HOME/.codex``, while the
screens show ``app.paths``. When the session was started with a relocated ``--home`` those two
differ, and the child process would inherit the real ``$HOME``. ``with_home`` closes the gap by
putting ``env HOME=<dir>`` in front of the command; the Settings and Extras screens use it too.
"""

from __future__ import annotations

import os
import textwrap
from typing import List, Optional, Sequence, Tuple

from installer.core import capabilities
from installer.core import config as cfg
from installer.core.paths import Paths
from installer.tui import draw
from installer.tui.base import Screen

SECTIONS: Tuple[Tuple[str, str, str, str], ...] = (
    ("shared", "s", "~/.agents", "RULES.md, LOCAL.md, config.json, mcp-servers.json, bin/sync-agents, shared skills"),
    ("claude", "c", "~/.claude", "CLAUDE.md, agents, commands, rules, hooks, scripts, settings; links shared skills"),
    ("codex", "x", "~/.codex", "AGENTS.md, agents, prompts, workflows, hooks.json, config.toml; links shared skills"),
)
KEY_TO_SECTION = {ord(key): name for name, key, _, _ in SECTIONS}
EXPLANATION = (
    "Runs the repo's install.sh for the sections you pick. Files that are yours once installed "
    "(CLAUDE.md, settings.json, config.toml, config.json, LOCAL.md) are only created when absent. "
    "Anything the install would replace is moved to ~/.agents/backups/ first; nothing is deleted. "
    "Press D for a dry run that changes nothing."
)
FOOTER = "s/c/x toggle shared/claude/codex   D dry run   A install   q back"
HOME_DIRS = (".agents", ".claude", ".codex")  # the directories install.sh creates under $HOME
Styled = Tuple[str, str]  # (text, attr name)


def install_home(paths: Paths) -> Optional[str]:
    """The ``$HOME`` under which ``install.sh`` lands in `paths`, or None when it cannot be told.

    The three tool homes must be ``.agents``, ``.claude`` and ``.codex`` side by side in one
    directory; a layout built from ``AGENTS_HOME`` / ``CLAUDE_CONFIG_DIR`` / ``CODEX_HOME``
    overrides has no single home that install.sh could be pointed at.
    """
    homes = (paths.agents_home, paths.claude_home, paths.codex_home)
    if tuple(os.path.basename(home) for home in homes) != HOME_DIRS:
        return None
    parents = {os.path.dirname(home) for home in homes}
    return parents.pop() if len(parents) == 1 else None


def relocated_home(paths: Paths) -> Optional[str]:
    """`install_home(paths)` when it is not the ``$HOME`` this process runs under, else None."""
    home = install_home(paths)
    if home is None or os.path.realpath(home) == os.path.realpath(os.path.expanduser("~")):
        return None
    return home


def with_home(paths: Paths, argv: Sequence[str]) -> Tuple[str, ...]:
    """`argv`, prefixed with ``env HOME=<dir>`` when the session's home is relocated.

    The App's command pane starts processes with the inherited environment only, so this is how a
    ``--home`` fixture reaches install.sh and the extras. Unchanged when nothing is relocated.
    """
    home = relocated_home(paths)
    command = tuple(argv)
    if home is None:
        return command
    if not command or "=" in command[0]:
        shown = command[0] if command else "(empty command)"
        raise ValueError(f"cannot run {shown!r} under HOME={home}: env would read it as an assignment")
    return ("env", f"HOME={home}") + command


def home_suffix(paths: Paths) -> str:
    """`` [HOME=<dir>]`` for a command-pane title when the home is relocated, else an empty string."""
    home = relocated_home(paths)
    return "" if home is None else f"  [HOME={paths.display(home)}]"


def run_dir(paths: Paths) -> str:
    """Working directory for third-party commands: the (possibly relocated) home, never the repo."""
    return install_home(paths) or os.path.expanduser("~")


def default_sections(app) -> Tuple[str, ...]:
    """shared plus every tool whose tools.* setting resolves to on (same rule as `installer sections`)."""
    chosen = ["shared"]
    for tool in ("claude", "codex"):
        if capabilities.resolve_tool(cfg.get(app.config, f"tools.{tool}"), app.caps.get(tool)):
            chosen.append(tool)
    return tuple(chosen)


def build_argv(paths: Paths, sections: Sequence[str], dry_run: bool) -> Tuple[str, ...]:
    """install.sh --headless [--shared] [--claude] [--codex] [--dry-run], sections in fixed order."""
    argv: List[str] = [os.path.join(paths.repo_dir, "install.sh"), "--headless"]
    argv += [f"--{name}" for name, _, _, _ in SECTIONS if name in sections]
    if dry_run:
        argv.append("--dry-run")
    return tuple(argv)


def command_text(argv: Sequence[str]) -> str:
    """The command as a user would type it from the repo root."""
    return " ".join(["./install.sh"] + list(argv[1:]))


class FullInstallScreen(Screen):
    title = "Install"
    tab = 8

    def __init__(self) -> None:
        self.chosen: Tuple[str, ...] = ()
        self._touched = False
        self._confirm = False
        self._started = False

    # ------------------------------------------------------------ state

    def editing(self) -> bool:
        return self._confirm

    def _refresh_defaults(self, app) -> None:
        """Follow the config/tool detection until the user toggles something themselves."""
        if not self._touched:
            self.chosen = default_sections(app)
        self._started = True

    def on_enter(self, app) -> None:
        self._refresh_defaults(app)

    def on_rescan(self, app) -> None:
        self._refresh_defaults(app)

    def toggle(self, name: str) -> None:
        if name in self.chosen:
            self.chosen = tuple(s for s, _, _, _ in SECTIONS if s in self.chosen and s != name)
        else:
            self.chosen = tuple(s for s, _, _, _ in SECTIONS if s in self.chosen or s == name)
        self._touched = True

    # ------------------------------------------------------------- draw

    def lines(self, app, width: int) -> Tuple[Styled, ...]:
        out: List[Styled] = [(piece, "normal") for piece in textwrap.wrap(EXPLANATION, max(20, width - 2))]
        out += [("", "normal"), ("Sections", "title")]
        for name, key, target, what in SECTIONS:
            box = draw.glyph("selected") if name in self.chosen else draw.glyph("unselected")
            text = f"  [{box}] {key}  {name:<7}-> {target:<11}{what}"
            out.append((text[:max(20, width)], "ok" if name in self.chosen else "dim"))
        out += [("", "normal"), ("Detected", "title"), (self._tools_line(app), "dim"), ("", "normal")]
        shown = command_text(build_argv(app.paths, self.chosen, False)) if self.chosen else "(no section selected)"
        out += [("Install command", "title"), (f"  {shown}", "normal"), (f"  dry run: {shown} --dry-run", "dim")]
        home = relocated_home(app.paths)
        if home is not None:
            out.append((f"  runs with HOME={app.paths.display(home)} (relocated)", "warn"))
        if self._confirm:
            out += [("", "normal"), ("Run the real install now? Press y to run, any other key cancels.", "warn")]
        return tuple(out)

    @staticmethod
    def _tools_line(app) -> str:
        parts = []
        for tool in ("claude", "codex"):
            mark = draw.glyph("yes" if app.caps.present(tool) else "no")
            parts.append(f"{tool} {mark} (tools.{tool} = {cfg.get(app.config, 'tools.' + tool)})")
        return "  " + "   ".join(parts)

    def draw(self, stdscr, app) -> None:
        if not self._started:
            self._refresh_defaults(app)
        footer = "y run the real install   any other key cancels" if self._confirm else FOOTER
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, footer)
        for offset, (text, name) in enumerate(self.lines(app, width)[:height]):
            draw.safe_addstr(stdscr, y0 + offset, x0, text, draw.attr(name), width)

    # ------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            self._dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - a bad key must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _dispatch(self, key: int, app) -> None:
        if self._confirm:
            self._confirm = False
            if key in (ord("y"), ord("Y")):
                self._run(app, dry_run=False)
            else:
                app.set_message("install cancelled")
        elif key in KEY_TO_SECTION:
            self.toggle(KEY_TO_SECTION[key])
        elif key == ord("D"):
            self._run(app, dry_run=True)
        elif key == ord("A"):
            self._ask(app)

    def _ask(self, app) -> None:
        if not self.chosen:
            app.set_message("select at least one section first (s, c or x)")
            return
        self._confirm = True

    def _run(self, app, dry_run: bool) -> None:
        if not self.chosen:
            app.set_message("select at least one section first (s, c or x)")
            return
        argv = build_argv(app.paths, self.chosen, dry_run)
        label = "Dry run" if dry_run else "Install"
        title = f"{label}: {command_text(argv)}{home_suffix(app.paths)}"
        app.run_command(list(with_home(app.paths, argv)), title, cwd=app.paths.repo_dir)
