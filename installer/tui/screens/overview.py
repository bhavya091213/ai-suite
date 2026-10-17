"""Tab 1: git banner, detected tools, counts per scope and the menu of the other tabs."""

from __future__ import annotations

import textwrap
import time
from typing import List, Optional, Sequence, Tuple

from installer.core import status as status_mod
from installer.tui import draw
from installer.tui.base import Screen
from installer.tui.screens.capabilities import CapabilitiesScreen

Segment = draw.Segment
Row = Tuple[Segment, ...]

TOOLS = ("claude", "codex", "git", "node", "docker", "obsidian", "tmux", "headroom")
FOOTER = "S setup wizard   c detected tools   j/k scroll   ? help   R recheck   q quit"

MENU = (
    (2, "Skills", "browse the repo catalog and install skills"),
    (3, "Installed", "what is on disk: update, retire, relink, push to the repo"),
    (4, "Issues", "duplicates, broken links, foreign skills, frontmatter problems"),
    (5, "Updates", "git fetch / pull and the skills changed upstream"),
    (6, "Settings", "models, guardrails, vaults, hooks (~/.agents/config.json)"),
    (7, "Files", "open CLAUDE.md, LOCAL.md, config and settings in your editor"),
    (8, "Install", "run install.sh for rules, agents, commands and hooks"),
    (9, "Extras", "Impeccable, Figma MCP, ppt-master, presentation-skill, Anthropic pptx"),
    (10, "Workflows", "compose installed skills into phased, gated workflows and manage them"),
)

# Tab 10 has no single-digit number, so it is reached with the key "0" (see ARCHITECTURE Part 5).
WORKFLOWS_TAB = 10
WORKFLOWS_KEY = "0"


def key_hint(number: int) -> str:
    """"(key 0) " for a tab whose key differs from its number, "" for tabs 2-9 where the number is the key."""
    return f"(key {WORKFLOWS_KEY}) " if number == WORKFLOWS_TAB else ""


def fetch_age_text(last_fetch: Optional[float], now: Optional[float] = None) -> str:
    """"fetched N min ago" / "never fetched" (hours and days once it is old)."""
    if last_fetch is None:
        return "never fetched"
    seconds = max(0.0, (time.time() if now is None else now) - last_fetch)
    minutes = int(seconds // 60)
    if minutes < 1:
        return "fetched just now"
    if minutes < 120:
        return f"fetched {minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"fetched {hours} h ago"
    return f"fetched {hours // 24} days ago"


def tool_segments(caps) -> Tuple[Segment, ...]:
    """One "check name" fragment per important tool; a missing git is an error, others dim."""
    segments: List[Segment] = []
    for name in TOOLS:
        present = caps.present(name)
        mark = draw.glyph("yes" if present else "no")
        style = "ok" if present else ("error" if name == "git" else "dim")
        segments.append((f"{mark} {name}", style))
    return tuple(segments)


def counts_rows(statuses: Sequence) -> Tuple[Row, ...]:
    """The per-scope counts table: a header row and one row per scope."""
    head = f"{'Scope':<8}{'Avail':>7}{'Installed':>11}{'Modified':>10}{'Missing':>9}{'Foreign':>9}" \
           f"{'Problems':>10}{'Updates':>9}"
    rows: List[Row] = [((head, "title"),)]
    for c in status_mod.counts(statuses):
        text = (f"{c.scope:<8}{c.available:>7}{c.installed:>11}{c.modified:>10}{c.missing:>9}"
                f"{c.foreign:>9}{c.problems:>10}{c.remote_updates:>9}")
        style = "warn" if (c.modified or c.problems or c.remote_updates) else "normal"
        rows.append(((text, style),))
    return tuple(rows)


def git_rows(info, width: int, now: Optional[float] = None) -> Tuple[Row, ...]:
    """Git banner: status message, wrapped hint (when non-empty) and the last-fetch line."""
    rows: List[Row] = [(("Git: ", "title"), (info.message, draw.git_attr(info)))]
    if info.hint:
        for piece in textwrap.wrap(info.hint, max(20, width - 4)):
            rows.append(((f"  {piece}", "warn"),))
    where = f"   {info.branch} @ {info.head}" if info.is_repo and info.branch else ""
    rows.append(((f"  {fetch_age_text(info.last_fetch, now)}{where}", "dim"),))
    return tuple(rows)


def menu_rows(width: Optional[int] = None) -> Tuple[Row, ...]:
    """One row per tab. A description that does not fit `width` is cut with an ellipsis; rows never wrap.

    A tab whose key is not its number (Workflows: 10, key 0) leads its description with a "(key 0)" hint,
    so the hint survives the truncation.
    """
    rows: List[Row] = []
    for number, label, text in MENU:
        head, name = f" {number:>2}  ", f"{label:<10}"
        text = key_hint(number) + text
        if width is not None:
            text = draw.truncate(text, width - len(head) - len(name))
        rows.append(((head, "title"), (name, "normal"), (text, "dim")))
    return tuple(rows)


def build_lines(app, width: int, now: Optional[float] = None) -> Tuple[Row, ...]:
    """Every overview row as coloured fragments, top to bottom."""
    blank: Row = (("", "normal"),)
    tools = draw.wrap_segments((("Detected tools:", "title"),) + tool_segments(app.caps), width)
    lines: List[Row] = list(git_rows(app.git, width, now))
    lines += [blank, *tools, blank, *counts_rows(app.statuses), blank, *menu_rows(width)]
    return tuple(lines)


class OverviewScreen(Screen):
    title = "Overview"
    tab = 1

    def __init__(self) -> None:
        self._top = 0
        self._height = 1
        self._total = 0

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, FOOTER)
        lines = build_lines(app, width)
        self._height, self._total = height, len(lines)
        self._top = draw.clamp_top(self._top, len(lines), height)
        for row in range(height):
            index = self._top + row
            if index < len(lines):
                draw.draw_segments(stdscr, y0 + row, x0, lines[index], width)

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if key == ord("S"):
                app.start_wizard()
            elif key == ord("c"):
                app.push(CapabilitiesScreen())
            elif key == ord(WORKFLOWS_KEY):
                # The app's global 1-9 dispatch cannot express tab 10, so the advertised key is handled here.
                app.goto_tab(WORKFLOWS_TAB)
            else:
                moved = draw.scroll_key(key, self._top, self._total, self._height)
                if moved is not None:
                    self._top = moved
        except Exception as exc:  # noqa: BLE001 - report, never crash
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None
