"""Tab 10 (Workflows): the workflows installed under ~/.agents/skills, with edit / new / retire / push / view.

A workflow is an ordinary shared skill that has a ``workflow.json`` next to its ``SKILL.md``. Rows come
from ``core.workflows.list_workflows`` and carry the validation result against the installed and catalog
skills. ``r`` and ``p`` plan with ``core.actions`` on the workflow's shared status row and hand the plan to
``App.confirm``; ``v`` shows the rendered SKILL.md in the viewer's text pane; ``Enter`` and ``n`` open the
editor in ``workflow_edit``.
"""

from __future__ import annotations

import curses
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from installer.core import actions, workflows
from installer.core.types import State
from installer.core.workflows import WARNING_PREFIX, Phase, WorkflowDef
from installer.tui import draw
from installer.tui.base import Screen
from installer.tui.listmodel import ListModel
from installer.tui.screens.skill_picker import plural
from installer.tui.screens.viewer import TextScreen
from installer.tui.screens.viewer_panes import ENTER_KEYS, ESC, move_model
from installer.tui.screens.workflow_edit import WorkflowEditScreen

NAME_WIDTH = 26
STATE_WIDTH = 13
DETAIL_LINES = 3
RETIRE_LABEL = "retired-skills"
PUSH_LABEL = "installer"
FOOTER = "Enter edit   n new   N example   r retire   p push   v view   / filter   q back"
EMPTY_TEXT = "no workflows yet - press n for a blank one or N to start from the example"


def blank_definition() -> WorkflowDef:
    """What ``n`` starts from: no name yet and one empty phase."""
    return WorkflowDef(name="", description="", triggers=(), phases=(Phase(name="Phase 1", goal="", skills=()),))


@dataclass(frozen=True)
class WorkflowRow:
    skill_dir: str
    wf: WorkflowDef
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]

    @property
    def key(self) -> str:
        return self.skill_dir

    @property
    def skill_count(self) -> int:
        return len({skill for phase in self.wf.phases for skill in phase.skills if skill.strip()})

    @property
    def state_text(self) -> str:
        if self.errors:
            return plural(len(self.errors), "error")
        return plural(len(self.warnings), "warning") if self.warnings else "ok"

    @property
    def state_attr(self) -> str:
        return "error" if self.errors else "warn" if self.warnings else "ok"


def row_search(row: WorkflowRow) -> str:
    """What the "/" filter matches against."""
    return f"{row.wf.name} {row.wf.description}"


def build_rows(paths) -> Tuple[WorkflowRow, ...]:
    """One row per installed workflow, validated against the installed and catalog skill names."""
    known = workflows.known_skill_names(paths)
    rows = []
    for skill_dir, wf in workflows.list_workflows(paths):
        issues = workflows.validate(wf, known)
        errors = tuple(text for text in issues if not text.startswith(WARNING_PREFIX))
        rows.append(WorkflowRow(skill_dir, wf, errors, tuple(text for text in issues if text not in errors)))
    return tuple(rows)


class WorkflowsScreen(Screen):
    title = "Workflows"
    tab = 10

    def __init__(self) -> None:
        self.model: ListModel = ListModel(key_fn=row_search)
        self._height = 8
        self._filtering = False
        self._pos = 0

    def editing(self) -> bool:
        return self._filtering

    # -------------------------------------------------------------- data

    def reload(self, app) -> None:
        self.model = self.model.with_items(build_rows(app.paths))

    def on_enter(self, app) -> None:
        self.reload(app)

    def on_rescan(self, app) -> None:
        self.reload(app)

    def shared_row(self, app, row: WorkflowRow):
        """The shared status row of the workflow's skill directory (None before the first rescan)."""
        name = os.path.basename(os.path.normpath(row.skill_dir))
        return next((s for s in app.statuses if s.scope == "shared" and s.name == name), None)

    # -------------------------------------------------------------- draw

    def _row_text(self, row: WorkflowRow, selected: bool, width: int) -> Tuple[str, int]:
        head = (f"  {row.wf.name:<{NAME_WIDTH}.{NAME_WIDTH}}{len(row.wf.phases):>7}{row.skill_count:>7}   "
                f"{row.state_text:<{STATE_WIDTH}} ")
        return draw.truncate(head + " ".join(row.wf.description.split()), width), draw.attr(row.state_attr)

    def _detail(self, app, row: WorkflowRow) -> Tuple[Tuple[str, str], ...]:
        problems = row.errors + row.warnings
        return ((f"path: {app.paths.display(row.skill_dir)}", "dim"),
                (f"triggers: {', '.join(row.wf.triggers) or '(none)'}", "dim"),
                (problems[0] if problems else "valid", "error" if row.errors else "warn" if problems else "ok"))

    def draw(self, stdscr, app) -> None:
        footer = f"/{self.model.query}_   Enter keep the filter   Esc clear it" if self._filtering else FOOTER
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, footer)
        head = f"  {'Workflow':<{NAME_WIDTH}}{'Phases':>7}{'Skills':>7}   {'State':<{STATE_WIDTH}} Description"
        draw.safe_addstr(stdscr, y0, x0, head, draw.attr("title"), width)
        self._height = max(1, height - 1 - DETAIL_LINES)
        self.model = self.model.move(0, self._height)
        if not self.model.filtered_count:
            text = "no workflow matches the filter" if self.model.query else EMPTY_TEXT
            draw.safe_addstr(stdscr, y0 + 1, x0, text, draw.attr("dim"), width)
        draw.draw_list(stdscr, y0 + 1, x0, self._height, width, self.model, self._row_text)
        row = self.model.current()
        if row is not None:
            for offset, (text, name) in enumerate(self._detail(app, row)):
                draw.safe_addstr(stdscr, y0 + height - DETAIL_LINES + offset, x0, text, draw.attr(name), width)

    # -------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if self._filtering:
                self._filter_key(key)
            else:
                self._dispatch(key, app)
        except Exception as exc:  # noqa: BLE001 - a bad key must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
        return None

    def _dispatch(self, key: int, app) -> None:
        moved = move_model(self.model, key, self._height)
        row = self.model.current()
        on_row = {ord("e"): self._edit, ord("r"): self._retire, ord("p"): self._push, ord("v"): self._view}
        on_row.update({enter: self._edit for enter in ENTER_KEYS})
        if moved is not None:
            self.model = moved
        elif key == ord("/"):
            self._filtering, self._pos = True, len(self.model.query)
        elif key == ESC and self.model.query:
            self.model = self.model.set_query("")
        elif key == ord("n"):
            app.push(WorkflowEditScreen(blank_definition()))
        elif key == ord("N"):
            app.push(WorkflowEditScreen(workflows.example()))
        elif key in on_row and row is None:
            app.set_message("no workflow selected: n creates one")
        elif key in on_row:
            on_row[key](app, row)

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

    # ----------------------------------------------------------- actions

    def _edit(self, app, row: WorkflowRow) -> None:
        app.push(WorkflowEditScreen(row.wf, row.skill_dir))

    def _retire(self, app, row: WorkflowRow) -> None:
        status = self.shared_row(app, row)
        if status is None:
            app.set_message(f"{row.wf.name} has no installed skill row yet: press R to rescan")
            return
        ops = actions.plan_retire(status, app.paths, app.paths.backup_root(RETIRE_LABEL))
        if not ops:
            app.set_message(f"nothing to retire for {row.wf.name}")
            return
        app.confirm(ops, f"Retire workflow {row.wf.name}")

    def _push(self, app, row: WorkflowRow) -> None:
        status = self.shared_row(app, row)
        if status is None:
            app.set_message(f"{row.wf.name} has no installed skill row yet: press R to rescan")
        elif status.state == State.INSTALLED:
            app.set_message(f"{row.wf.name} is already identical to its copy in the repo")
        else:
            ops = actions.plan_push_to_repo(status, app.paths, app.paths.backup_root(PUSH_LABEL))
            if ops:
                app.confirm(ops, f"Push workflow {row.wf.name} into the repo")
            else:
                app.set_message(f"nothing to push for {row.wf.name}: it is not a readable directory, "
                                f"or it is the repo copy itself")

    def _view(self, app, row: WorkflowRow) -> None:
        text = workflows.render_skill_md(row.wf)
        app.push(TextScreen(f"SKILL.md - {row.wf.name}", text.splitlines()))
