"""Tab 4 (Issues): duplicates, broken links, foreign entries and frontmatter problems.

Rows are ``core.status.problems`` plus repo issues that no problem row already lists (a
directory without SKILL.md has no status row, or only a foreign one that does not mention the
repo problem, so it appears as a pseudo-row). Enter
shows every note for the row; ``l`` relinks and ``r`` retires the status rows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from installer.core import status as status_mod
from installer.core.types import RepoIssue, SkillStatus, State
from installer.tui import draw
from installer.tui.screens.viewer import TextScreen
from installer.tui.screens.viewer_panes import ENTER_KEYS, SkillListScreen, run_action, select_box

NAME_WIDTH = 26
FOOTER = "space select   / filter   Enter details   l relink   r retire   R recheck   q back"


@dataclass(frozen=True)
class IssueRow:
    """One line of the Issues list: a problem status row or a repo-level pseudo-row."""

    scope: str
    name: str
    origin: str  # "status" | "repo"
    kind: str  # RepoIssue.kind for repo rows, "" otherwise
    lines: Tuple[str, ...]  # every note for the row, the headline first
    status: Optional[SkillStatus] = None
    severity: str = "warn"  # draw.attr name

    @property
    def key(self) -> Tuple[str, str, str, str]:
        return (self.origin, self.scope, self.name, self.kind)

    @property
    def headline(self) -> str:
        return self.lines[0] if self.lines else ""

    @property
    def search(self) -> str:
        return " ".join((self.scope, self.name) + self.lines)


def _notes(status: SkillStatus) -> Tuple[str, ...]:
    notes: List[str] = list(status.issues)
    notes += [d for d in status.duplicates if d not in notes]
    notes += [f"{link.consumer}: {link.state.value} ({link.path})" for link in status.link_problems
              if not status.issues]
    return tuple(notes)


def _carried(row: Optional[IssueRow], issue: RepoIssue) -> bool:
    """True when the problem row already lists this repo issue among its notes.

    ``status.compute`` writes ``repo: <message>`` into a row's notes only for platform and shared
    rows. A FOREIGN row with the same (scope, name) never gets it, so the key alone proves nothing.
    """
    return row is not None and f"repo: {issue.message}" in row.lines


def build_issue_rows(statuses: Sequence[SkillStatus], repo_issues: Sequence[RepoIssue]) -> Tuple[IssueRow, ...]:
    """Problem rows first, then the repo issues no problem row already shows."""
    rows = tuple(IssueRow(s.scope, s.name, "status", "", _notes(s), s, "error" if s.issues else "warn")
                 for s in status_mod.problems(statuses))
    by_key = {(row.scope, row.name): row for row in rows}
    extra = tuple(IssueRow(i.scope, i.name, "repo", i.kind, (i.message,), None, "error")
                  for i in repo_issues if not _carried(by_key.get((i.scope, i.name)), i))
    return rows + extra


def fix_hint(status: SkillStatus) -> str:
    if status.scope == "shared" and status.link_problems:
        return ("Fix: l relinks the tools to the shared copy (a real directory with different "
                "content is left alone); r retires the skill.")
    if status.state == State.FOREIGN:
        return "Fix: r moves it to a backup; p copies it into the repo first if you want to keep it."
    return ""


def detail_lines(row: IssueRow, paths) -> Tuple[str, ...]:
    """The full text pane for one row."""
    head = f"{row.scope}/{row.name}"
    if row.status is None:
        where = paths.display(os.path.join(paths.source_dir(row.scope), row.name))
        return (head, f"repo issue ({row.kind})", "", row.headline, "", f"Fix it in the repo: {where}")
    status = row.status
    out: List[str] = [f"{head}   state: {status.state.value}"]
    if status.installed is not None:
        out.append(f"installed: {paths.display(status.installed.path)}")
    if status.source is not None:
        out.append(f"repo: {paths.display(status.source.path)}")
    if status.issues:
        out += ["", "Problems:"] + [f"  - {text}" for text in status.issues]
    notes = [d for d in status.duplicates if d not in status.issues]
    if notes:
        out += ["", "Duplicates and notes:"] + [f"  - {text}" for text in notes]
    if not status.issues and not notes:
        out += ["", "Link problems:"] + [f"  - {text}" for text in row.lines]
    hint = fix_hint(status)
    return tuple(out + (["", hint] if hint else []))


class IssuesScreen(SkillListScreen):
    title = "Issues"
    tab = 4
    footer = FOOTER

    def __init__(self) -> None:
        super().__init__(lambda row: row.search)

    def build_rows(self, app) -> Sequence[IssueRow]:
        return build_issue_rows(app.statuses, app.repo_issues)

    def empty_text(self, app) -> str:
        return "no problems found"

    def row_text(self, row: IssueRow, selected: bool, width: int) -> Tuple[str, int]:
        count = f"[{len(row.lines)}] " if len(row.lines) > 1 else ""
        head = f"{select_box(selected)} {draw.glyph('problem')} {row.scope:<6} {row.name:<{NAME_WIDTH}.{NAME_WIDTH}} "
        return draw.truncate(head + count + row.headline, width), draw.attr(row.severity)

    def act(self, action: str, app) -> None:
        """Relink / retire the status rows among the targets; repo-only rows cannot be planned."""
        rows = self.targets()
        statuses = tuple(row.status for row in rows if row.status is not None)
        if rows and not statuses:
            app.set_message("repo issues can only be fixed in the repo - press Enter for the path")
            return
        run_action(app, action, statuses, on_done=self._after_action)

    def on_key(self, key: int, app) -> Optional[str]:
        if key == ord("l"):
            self.act("relink", app)
        elif key == ord("r"):
            self.act("retire", app)
        elif key in ENTER_KEYS:
            current = self.model.current()
            if current is not None:
                app.push(TextScreen(f"{current.scope}/{current.name}", detail_lines(current, app.paths)))
        return None
