"""What the probe found on this machine, with a hint for each missing tool that matters."""

from __future__ import annotations

import textwrap
from typing import List, Optional, Tuple

from installer.core import git as git_mod
from installer.tui import draw
from installer.tui.base import Screen

NamedLine = Tuple[str, str]  # (text, attr name)

TMUX_HINT = "tmux is missing: consider disabling the tmux hooks in Settings."
HEADROOM_HINT = ("headroom is missing: ANTHROPIC_BASE_URL/headroom entries are stripped from "
                 "rendered examples.")
FOOTER = "j/k scroll   R recheck after installing a tool   q back"


def table_lines(caps) -> Tuple[NamedLine, ...]:
    """Header plus one row per probed capability: name, found mark, version, detail."""
    lines: List[NamedLine] = [(f"{'Tool':<12}{'Found':<7}{'Version':<26}Detail", "title")]
    for name, cap in caps.items.items():
        mark = draw.glyph("yes" if cap.present else "no")
        detail = cap.detail or cap.path or ""
        text = f"{name:<12}{mark:<7}{(cap.version or '-'):<26}{detail}"
        lines.append((text, "ok" if cap.present else "dim"))
    return tuple(lines)


def extra_lines(caps) -> Tuple[NamedLine, ...]:
    """Obsidian vaults and nvm node versions, when the probe found any."""
    lines: List[NamedLine] = []
    if caps.vaults:
        lines += [("", "normal"), ("Obsidian vaults (open first):", "title")]
        lines += [(f"  {vault}", "normal") for vault in caps.vaults]
    if caps.nvm_versions:
        lines += [("", "normal"), ("nvm node versions:", "title"), ("  " + ", ".join(caps.nvm_versions), "normal")]
    return tuple(lines)


def missing_hints(caps) -> Tuple[str, ...]:
    """Hint texts for the missing tools that matter: git, tmux, headroom."""
    hints: List[str] = []
    if not caps.present("git"):
        hints.append(git_mod.install_hint())
    if not caps.present("tmux"):
        hints.append(TMUX_HINT)
    if not caps.present("headroom"):
        hints.append(HEADROOM_HINT)
    return tuple(hints)


def hint_lines(caps, width: int) -> Tuple[NamedLine, ...]:
    """The "Hints" block: one wrapped bullet per missing tool, or an all-clear line."""
    lines: List[NamedLine] = [("Hints", "title")]
    hints = missing_hints(caps)
    if not hints:
        return tuple(lines + [("  Nothing to fix: every tool the installer cares about is present.", "ok")])
    for hint in hints:
        wrapped = textwrap.wrap(hint, max(20, width - 4)) or [hint]
        lines += [(f"  {draw.glyph('bullet')} {wrapped[0]}", "warn")]
        lines += [(f"    {piece}", "warn") for piece in wrapped[1:]]
    return tuple(lines)


def build_lines(app, width: int) -> Tuple[NamedLine, ...]:
    """Hints first when something is missing (they are what the user must act on), else last."""
    table = table_lines(app.caps) + extra_lines(app.caps)
    hints = hint_lines(app.caps, width)
    if missing_hints(app.caps):
        return hints + (("", "normal"),) + table
    return table + (("", "normal"),) + hints


class CapabilitiesScreen(Screen):
    title = "Detected tools"
    tab = None

    def __init__(self) -> None:
        self._top = 0
        self._height = 1
        self._total = 0

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, FOOTER)
        lines = build_lines(app, width)
        self._height, self._total = height, len(lines)
        self._top = draw.clamp_top(self._top, len(lines), height)
        shown = [(text, draw.attr(name)) for text, name in lines]
        draw.draw_text(stdscr, y0, x0, height, width, shown, self._top)

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            moved = draw.scroll_key(key, self._top, self._total, self._height)
            if moved is not None:
                self._top = moved
        except Exception as exc:  # noqa: BLE001
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None
