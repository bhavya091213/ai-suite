"""Workflow editor: header fields and ordered phases, and the editor for one phase.

``WorkflowEditScreen`` holds a ``WorkflowDef`` and swaps it for a ``dataclasses.replace`` copy on every
change; it is dirty while it differs from the definition it was loaded with. ``PhaseEditScreen`` edits
one phase and reports each change straight back through ``on_change``, so closing it never loses
anything. Both own the keyboard (``OwnedScreen``): the global digits, ``q`` and ``Q`` cannot throw
unsaved work away, and ``q`` in the workflow editor asks for ``y`` while there are unsaved changes.
Saving validates (errors block, warnings do not) and hands ``workflows.plan_save`` to ``app.confirm``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from typing import Callable, FrozenSet, List, Optional, Sequence, Tuple

from installer.core import workflows
from installer.core.workflows import WARNING_PREFIX, Phase, WorkflowDef
from installer.tui import draw
from installer.tui.base import POP, QUIT
from installer.tui.listmodel import ListModel
from installer.tui.screens.skill_picker import (BACK_FIRST, OwnedScreen, SkillPickerScreen, at_position,
                                                inserted, moved, plural, skill_choices, without)
from installer.tui.screens import workflow_save as save
from installer.tui.screens.viewer_panes import ENTER_KEYS, ESC, move_model

FIELD_LABELS = (("name", "Name"), ("description", "Description"), ("triggers", "Triggers (a, b)"),
                ("handback", "Handback"))
LIST_LABELS = (("steps", "Steps"), ("outputs", "Outputs"))
SAVE_LABEL = "installer"
STAGE_PREFIX = "installer-workflow-"
PANEL_LINES = 4
DEFAULT_HEIGHT = 12
EDIT_FOOTER = "Enter edit   a add phase   x remove phase   J/K move phase   s save   q back"
PHASE_FOOTER = "Enter edit   s skills   t gate   a add   x remove   J/K move   q back"
DISCARD_FOOTER = "y discard the unsaved changes   any other key keeps editing"
UNSAVED = "unsaved changes: y discards them, any other key keeps editing"


# ------------------------------------------------------------- pure helpers


def new_phase(phases: Sequence[Phase]) -> Phase:
    """An empty phase named "Phase N", with N the first number not used by a phase name."""
    taken = {phase.name.strip().casefold() for phase in phases}
    number = len(phases) + 1
    while f"phase {number}" in taken:
        number += 1
    return Phase(name=f"Phase {number}", goal="", skills=())


def field_value(wf: WorkflowDef, key: str) -> str:
    value = getattr(wf, key)
    return ", ".join(value) if key == "triggers" else value


def with_field(wf: WorkflowDef, key: str, text: str) -> WorkflowDef:
    """`wf` with one header field replaced; triggers are split on commas."""
    text = text.strip()
    if key == "triggers":
        return replace(wf, triggers=tuple(part.strip() for part in text.split(",") if part.strip()))
    return replace(wf, **{key: text})


@dataclass(frozen=True)
class EditRow:
    kind: str  # "field" | "phase"
    key: str  # the header field name; "" for a phase
    index: int  # position of the phase; -1 for a field
    label: str
    text: str


def phase_summary(phase: Phase) -> str:
    gate = "[gate]" if phase.gate else "      "
    counts = (plural(len(phase.skills), "skill"), plural(len(phase.steps), "step"),
              plural(len(phase.outputs), "output"))
    return f"{phase.name.strip() or '(unnamed)':<22.22} {gate}  " + ", ".join(counts)


def edit_rows(wf: WorkflowDef) -> Tuple[EditRow, ...]:
    """The header fields, then one row per phase."""
    fields = tuple(EditRow("field", key, -1, label, field_value(wf, key)) for key, label in FIELD_LABELS)
    phases = tuple(EditRow("phase", "", i, f"Phase {i + 1}", phase_summary(phase))
                   for i, phase in enumerate(wf.phases))
    return fields + phases


@dataclass(frozen=True)
class PhaseRow:
    kind: str  # "field" | "head" (a list's heading) | "item" (one step or output)
    key: str  # name goal skills gate gate_text, or steps / outputs
    index: int  # position inside steps / outputs; -1 otherwise
    label: str
    text: str


def phase_rows(phase: Phase) -> Tuple[PhaseRow, ...]:
    """The scalar fields, then the steps and the outputs, each a heading plus one row per line."""
    gate = "on - stops for the user's approval" if phase.gate else "off"
    rows: List[PhaseRow] = [
        PhaseRow("field", "name", -1, "Name", phase.name),
        PhaseRow("field", "goal", -1, "Goal", phase.goal),
        PhaseRow("field", "skills", -1, "Skills", ", ".join(phase.skills)),
        PhaseRow("field", "gate", -1, "Gate", gate),
        PhaseRow("field", "gate_text", -1, "Gate text", phase.gate_text),
    ]
    for key, label in LIST_LABELS:
        lines = getattr(phase, key)
        rows.append(PhaseRow("head", key, -1, label, f"({len(lines)})"))
        rows.extend(PhaseRow("item", key, i, "", text) for i, text in enumerate(lines))
    return tuple(rows)


# -------------------------------------------------------------- phase editor


class PhaseEditScreen(OwnedScreen):
    """Fields of one phase; steps and outputs are lists (``a`` add, ``x`` remove, ``J``/``K`` move)."""

    def __init__(self, phase: Phase, index: int, on_change: Callable[[Phase], None]) -> None:
        self.index = index
        self.phase = phase
        self.on_change = on_change
        self.model: ListModel = ListModel(items=phase_rows(phase))
        self._height = DEFAULT_HEIGHT

    @property
    def title(self) -> str:
        return f"Phase {self.index + 1}: {self.phase.name.strip() or '(unnamed)'}"

    # -------------------------------------------------------------- draw

    def _row(self, item: PhaseRow, selected: bool, width: int) -> Tuple[str, int]:
        if item.kind == "head":
            return draw.truncate(f"  {item.label} {item.text}", width), draw.attr("title")
        if item.kind == "item":
            return draw.truncate(f"      {item.index + 1:>2}. {item.text}", width), draw.attr("normal")
        empty = "(none - s picks skills)" if item.key == "skills" else "(empty)"
        shown = draw.truncate(f"  {item.label:<10}{item.text or empty}", width)
        return shown, draw.attr("normal" if item.text else "dim")

    def draw(self, stdscr, app) -> None:
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, PHASE_FOOTER)
        self._height = height
        self.model = self.model.move(0, height)
        draw.draw_list(stdscr, y0, x0, height, width, self.model, self._row)

    # -------------------------------------------------------------- keys

    def dispatch(self, key: int, app) -> Optional[str]:
        if key in (ord("q"), ESC):
            return POP
        moves = move_model(self.model, key, self._height)
        row = self.model.current()
        shift = {ord("J"): 1, ord("K"): -1}
        if moves is not None:
            self.model = moves
        elif key == ord("Q"):
            app.set_message(BACK_FIRST)
        elif key in ENTER_KEYS or key == ord("e"):
            self._edit(app, row)
        elif key == ord("a"):
            self._add(app, row)
        elif key == ord("x"):
            self._remove(app, row)
        elif key in shift:
            self._shift(shift[key], row)
        elif key == ord("s"):
            self._pick_skills(app)
        elif key == ord("t") or (key == ord(" ") and row is not None and row.key == "gate"):
            self._set(replace(self.phase, gate=not self.phase.gate), ("gate", -1))
        return None

    # ------------------------------------------------------------- edits

    def _set(self, phase: Phase, focus: Optional[Tuple[str, int]] = None) -> None:
        """Adopt `phase`, rebuild the rows, put the cursor on `focus` (key, index) and tell the parent."""
        self.phase = phase
        self.model = self.model.with_items(phase_rows(phase))
        rows = [(row.key, row.index) for row in self.model.items]
        if focus in rows:
            self.model = at_position(self.model, rows.index(focus), self._height)
        self.on_change(phase)

    def _ask(self, app, label: str, initial: str = "") -> Optional[str]:
        text = draw.prompt_line(app.stdscr, f"{label}: ", initial=initial)
        if text is None:
            app.set_message("unchanged")
            return None
        return text.strip()

    def _edit(self, app, row: Optional[PhaseRow]) -> None:
        if row is None:
            return
        if row.kind == "head":
            self._add(app, row)
        elif row.kind == "item":
            self._edit_line(app, row)
        elif row.key == "skills":
            self._pick_skills(app)
        elif row.key == "gate":
            self._set(replace(self.phase, gate=not self.phase.gate), ("gate", -1))
        else:
            text = self._ask(app, row.label, row.text)
            if text is not None:
                self._set(replace(self.phase, **{row.key: text}), (row.key, -1))

    def _pick_skills(self, app) -> None:
        choices = skill_choices(app.statuses, self.phase.skills)

        def accept(names: Tuple[str, ...]) -> None:
            self._set(replace(self.phase, skills=names), ("skills", -1))

        app.push(SkillPickerScreen(choices, self.phase.skills, accept, f"Skills for phase {self.index + 1}"))

    def _put_lines(self, key: str, lines: Sequence[str], focus: int) -> None:
        self._set(replace(self.phase, **{key: tuple(lines)}), (key, focus))

    def _edit_line(self, app, row: PhaseRow) -> None:
        text = self._ask(app, f"{row.key[:-1]} {row.index + 1}", row.text)
        if text == "":
            app.set_message("an empty line is not kept: x removes the line")
        elif text is not None:
            lines = getattr(self.phase, row.key)
            self._put_lines(row.key, [text if i == row.index else old for i, old in enumerate(lines)], row.index)

    def _add(self, app, row: Optional[PhaseRow]) -> None:
        if row is None or row.kind == "field":
            app.set_message("move the cursor to Steps or Outputs, then press a")
            return
        lines = getattr(self.phase, row.key)
        position = len(lines) if row.kind == "head" else row.index + 1
        text = self._ask(app, f"new {row.key[:-1]}")
        if text:
            self._put_lines(row.key, inserted(lines, position, text), position)

    def _remove(self, app, row: Optional[PhaseRow]) -> None:
        if row is None or row.kind != "item":
            app.set_message("move the cursor to a step or an output line, then press x")
            return
        lines = without(getattr(self.phase, row.key), row.index)
        self._put_lines(row.key, lines, min(row.index, len(lines) - 1))

    def _shift(self, delta: int, row: Optional[PhaseRow]) -> None:
        if row is None or row.kind != "item":
            return
        lines = getattr(self.phase, row.key)
        shifted = moved(lines, row.index, delta)
        if shifted != tuple(lines):
            self._put_lines(row.key, shifted, row.index + delta)


# ----------------------------------------------------------- workflow editor


class WorkflowEditScreen(OwnedScreen):
    """Header fields and the phase list of one workflow; ``s`` validates, plans and confirms the save."""

    def __init__(self, wf: WorkflowDef, skill_dir: Optional[str] = None,
                 stage_dir: Optional[str] = None) -> None:
        self.loaded = wf
        self.wf = wf
        self.skill_dir = skill_dir
        self.known: FrozenSet[str] = frozenset()
        self.model: ListModel = ListModel(items=edit_rows(wf))
        self._stage_dir = stage_dir
        self._known_loaded = False
        self._discard: Optional[str] = None  # POP or QUIT while waiting for "y" to discard changes
        self._height = DEFAULT_HEIGHT

    @property
    def dirty(self) -> bool:
        return self.wf != self.loaded

    @property
    def title(self) -> str:
        name = self.wf.name.strip() or "(unnamed)"
        return f"{'Edit' if self.skill_dir else 'New'} workflow: {name}{' *' if self.dirty else ''}"

    # -------------------------------------------------------------- data

    def _refresh_known(self, app) -> None:
        """Installed and catalog skill names for validation (the App reports a failure here)."""
        self.known = workflows.known_skill_names(app.paths)
        self._known_loaded = True

    def on_enter(self, app) -> None:
        if not self._known_loaded:
            self._refresh_known(app)

    def on_rescan(self, app) -> None:
        self._refresh_known(app)

    def _replace(self, wf: WorkflowDef, focus: Optional[int] = None) -> None:
        """Adopt `wf` and rebuild the rows; `focus` is the row position for the cursor."""
        self.wf = wf
        self.model = self.model.with_items(edit_rows(wf))
        if focus is not None:
            self.model = at_position(self.model, focus, self._height)

    # -------------------------------------------------------------- draw

    def _panel(self) -> Tuple[Tuple[str, str], ...]:
        issues = save.edit_issues(self.wf, self.known)
        errors = [text for text in issues if not text.startswith(WARNING_PREFIX)]
        state = "modified" if self.dirty else "saved" if self.skill_dir else "not saved yet"
        counts = f"{plural(len(errors), 'error')}, {plural(len(issues) - len(errors), 'warning')}"
        lines = [(f"{state}   {counts if issues else 'valid'}",
                  "error" if errors else "warn" if issues else "ok")]
        return tuple(lines + [(f"  {text}", "error" if text in errors else "warn")
                              for text in issues[:PANEL_LINES - 1]])

    def _row(self, item: EditRow, selected: bool, width: int) -> Tuple[str, int]:
        text = item.text or ("" if item.kind == "phase" else "(not set)")
        return draw.truncate(f"  {item.label:<17}{text}", width), draw.attr("normal" if item.text else "dim")

    def draw(self, stdscr, app) -> None:
        footer = DISCARD_FOOTER if self._discard is not None else EDIT_FOOTER
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, footer)
        body = max(1, height - PANEL_LINES)
        self._height = body
        self.model = self.model.move(0, body)
        draw.draw_list(stdscr, y0, x0, body, width, self.model, self._row)
        for offset, (text, name) in enumerate(self._panel()):
            draw.safe_addstr(stdscr, y0 + body + offset, x0, text, draw.attr(name), width)

    # -------------------------------------------------------------- keys

    def dispatch(self, key: int, app) -> Optional[str]:
        if self._discard is not None:
            return self._answer(key, app)
        if key in (ord("q"), ESC):
            return self._leave(app, POP)
        if key == ord("Q"):
            return self._leave(app, QUIT)
        moves = move_model(self.model, key, self._height)
        if moves is not None:
            self.model = moves
            return None
        actions = {ord("a"): self._add_phase, ord("x"): self._remove_phase, ord("s"): self._save,
                   ord("e"): self._open_row,
                   ord("J"): lambda a: self._move_phase(1), ord("K"): lambda a: self._move_phase(-1)}
        actions.update({enter: self._open_row for enter in ENTER_KEYS})
        if key in actions:
            actions[key](app)
        return None

    def _leave(self, app, outcome: str) -> Optional[str]:
        if not self.dirty:
            return outcome
        self._discard = outcome
        app.set_message(UNSAVED)
        return None

    def _answer(self, key: int, app) -> Optional[str]:
        outcome, self._discard = self._discard, None
        if key in (ord("y"), ord("Y")):
            return outcome
        app.set_message("kept editing")
        return None

    # ------------------------------------------------------------ edits

    def _current_phase(self) -> Optional[int]:
        row = self.model.current()
        return row.index if row is not None and row.kind == "phase" else None

    def _open_row(self, app) -> None:
        row = self.model.current()
        if row is None:
            return
        if row.kind == "phase":
            index = row.index
            app.push(PhaseEditScreen(self.wf.phases[index], index, lambda phase: self._set_phase(index, phase)))
            return
        text = draw.prompt_line(app.stdscr, f"{row.label}: ", initial=field_value(self.wf, row.key))
        if text is None:
            app.set_message("unchanged")
            return
        self._replace(with_field(self.wf, row.key, text))

    def _set_phase(self, index: int, phase: Phase) -> None:
        phases = tuple(phase if i == index else old for i, old in enumerate(self.wf.phases))
        self._replace(replace(self.wf, phases=phases))

    def _add_phase(self, app) -> None:
        current = self._current_phase()
        position = len(self.wf.phases) if current is None else current + 1
        phases = inserted(self.wf.phases, position, new_phase(self.wf.phases))
        self._replace(replace(self.wf, phases=phases), len(FIELD_LABELS) + position)

    def _remove_phase(self, app) -> None:
        current = self._current_phase()
        if current is None:
            app.set_message("move the cursor to a phase, then press x")
            return
        phases = without(self.wf.phases, current)
        self._replace(replace(self.wf, phases=phases), len(FIELD_LABELS) + max(0, min(current, len(phases) - 1)))

    def _move_phase(self, delta: int) -> None:
        current = self._current_phase()
        if current is None:
            return
        phases = moved(self.wf.phases, current, delta)
        if phases != self.wf.phases:
            self._replace(replace(self.wf, phases=phases), len(FIELD_LABELS) + current + delta)

    # -------------------------------------------------------------- save

    def _stage(self) -> str:
        """A fresh, empty staging directory for one save attempt, inside `stage_dir` when that was given."""
        where = {} if self._stage_dir is None else {"dir": self._stage_dir}
        return tempfile.mkdtemp(prefix=STAGE_PREFIX, **where)

    def _save(self, app) -> None:
        issues = save.edit_issues(self.wf, self.known)
        errors = [text for text in issues if not text.startswith(WARNING_PREFIX)]
        if errors:
            app.set_message(f"cannot save: {errors[0]}" + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
            return
        target = os.path.join(app.paths.install_dir("shared"), self.wf.name)
        own = self.skill_dir is not None and os.path.abspath(self.skill_dir) == os.path.abspath(target)
        taken = None if own else save.name_taken(self.wf.name, app.paths, app.catalog)
        if taken:
            app.set_message(f"cannot save: {taken}; choose another name")
        elif own and not self.dirty and os.path.lexists(target):
            app.set_message("no changes to save")
        else:
            self._confirm_save(app, target)

    def _confirm_save(self, app, target: str) -> None:
        row = next((s for s in app.statuses if s.scope == "shared" and s.name == self.wf.name), None)
        stage = self._stage()
        kept = save.carry_unmanaged(target, os.path.join(stage, self.wf.name)) if os.path.isdir(target) else ()
        ops = workflows.plan_save(self.wf, app.paths, app.paths.backup_root(SAVE_LABEL), stage,
                                  row.links if row is not None else ())
        notes = save.save_notes(kept, save.unknown_keys(target), save.tools_in_the_way(self.wf.name, app.paths))
        saved = self.wf
        done = lambda results: self._saved(app, saved, target, results)  # noqa: E731
        app.confirm(save.with_notes(ops, notes), save.save_title(saved.name, notes), on_done=done)

    def _saved(self, app, saved: WorkflowDef, target: str, results: Sequence) -> None:
        """Adopt `saved` as the loaded workflow as soon as its copy is in place, even if a later link failed.

        Once the copy ran, ``~/.agents/skills/<name>`` holds this workflow: an editor that stayed dirty
        with no ``skill_dir`` would offer a save that ``name_taken`` then refuses. A failed link is
        reported on its own and is fixed from the Installed tab (``l``).
        """
        failed = [result for result in results if not result.ok]
        placed = any(result.ok and result.op.kind == "copytree" and result.op.dst == target
                     for result in results)
        if not placed:
            app.set_message("save failed: " + (failed[0].message if failed else "nothing ran") + " - see the log")
            return
        self.loaded, self.skill_dir = saved, target
        app.rescan()
        if failed:
            app.set_message(f"saved workflow {saved.name}, but {plural(len(failed), 'step')} failed: "
                            f"{failed[0].message} - see the log; l on the Installed tab relinks")
        else:
            app.set_message(f"saved workflow {saved.name}")
