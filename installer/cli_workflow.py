"""`workflow` commands: list, show, render, example, save, retire, push.

A workflow is an ordinary shared skill (``~/.agents/skills/<name>/``) whose source of truth
is ``workflow.json``; ``installer.core.workflows`` renders the rest. ``save`` validates a
definition file, stages the rendered skill in a temp directory and applies the plan from
``workflows.plan_save`` through ``cli_io.run_plan`` like every other mutating command.
``retire`` and ``push`` reuse ``core.actions`` on the workflow's shared status row.

Validation errors exit 2 (each printed); warnings are printed and never block. ``save`` only
ever replaces an installed *workflow* (its previous copy goes to the backup folder); a
same-named installed skill that is not a workflow is refused, even with ``--yes``.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from installer.cli_commands import World, load_world
from installer.cli_io import (
    EXIT_OK, EXIT_USAGE, Ctx, dump_json, emit, glyph, print_table, read_text, run_plan,
    usage_error, warn,
)
from installer.core import actions, skills, workflows
from installer.core.frontmatter import SKILL_FILE
from installer.core.types import IGNORED_DIR_REASONS, ConsumerLink, Operation, SkillStatus
from installer.core.workflows import WARNING_PREFIX, WORKFLOW_FILE, WorkflowDef

STAGE_PREFIX = "installer-workflow-"
SAVE_LABEL = "installer"
RETIRE_LABEL = "retired-skills"
NO_WORKFLOWS_HELP = ("No workflows installed. Start from a sample: "
                     "'workflow example --json > my-workflow.json', edit it, then "
                     "'workflow save my-workflow.json'.")
DEFAULT_GATE_SHOWN = "(default: the user approves before the next phase)"
EXAMPLE_HINT = "Save a copy to edit with: workflow example --json > my-workflow.json"
PUSH_EMPTY_REASON = "nothing pushable (not a readable directory, or it already is the repo copy)"
RETIRE_EMPTY_REASON = "nothing to retire (tool-managed entry, or not a readable directory)"
# Compared case-folded: a case-insensitive filesystem (the macOS default) maps "Learned" onto
# the tool-managed "learned" directory.
RESERVED_NAMES: FrozenSet[str] = frozenset(name.casefold() for name in IGNORED_DIR_REASONS)
# The files `workflows.stage` writes; anything else in an existing copy is not carried over.
RENDERED_FILES: FrozenSet[str] = frozenset(
    (SKILL_FILE, WORKFLOW_FILE, workflows.OPENAI_YAML.replace(os.sep, "/")))
NOTE_FILE_LIMIT = 5
TOO_DEEP = "workflow definition is nested too deeply to read"


# ------------------------------------------------------------------ helpers


def _flat(text: str) -> str:
    return " ".join(text.split())


def _split(messages: Tuple[str, ...]) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """(errors, warnings) from ``workflows.validate`` output."""
    warnings = tuple(m for m in messages if m.startswith(WARNING_PREFIX))
    return tuple(m for m in messages if not m.startswith(WARNING_PREFIX)), warnings


def _message_line(message: str) -> str:
    return message if message.startswith(WARNING_PREFIX) else f"error: {message}"


def _validate(ctx: Ctx, wf: WorkflowDef,
              known: Optional[FrozenSet[str]] = None) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    known = workflows.known_skill_names(ctx.paths) if known is None else known
    return _split(workflows.validate(wf, known))


def _skill_count(wf: WorkflowDef) -> int:
    return len({skill for phase in wf.phases for skill in phase.skills if skill.strip()})


def _workflow_dir(ctx: Ctx, name: str) -> str:
    """The installed workflow directory called `name`; exit 2 when there is none."""
    if not skills.is_valid_name(name):
        raise usage_error(f"invalid workflow name: {name!r}")
    skill_dir = os.path.join(ctx.paths.install_dir("shared"), name)
    if not os.path.isfile(os.path.join(skill_dir, WORKFLOW_FILE)):
        raise usage_error(f"{name} is not an installed workflow "
                          f"(no {WORKFLOW_FILE} in {ctx.paths.display(skill_dir)})")
    return skill_dir


def _parse_definition(text: str) -> WorkflowDef:
    """`workflows.from_json`, with JSON nested deeper than the parser's stack allows reported
    as an ordinary ``ValueError``: a bad file is a usage error, never a crash."""
    try:
        return workflows.from_json(text)
    except RecursionError as exc:
        raise ValueError(TOO_DEEP) from exc


def _read_def(skill_dir: str, name: str) -> WorkflowDef:
    path = os.path.join(skill_dir, WORKFLOW_FILE)
    try:
        return _parse_definition(read_text(path))
    except (ValueError, OSError) as exc:
        raise usage_error(f"{name}/{WORKFLOW_FILE}: {exc}")


def _load_file(path: str) -> WorkflowDef:
    try:
        text = read_text(path)
    except OSError as exc:
        raise usage_error(f"cannot read {path}: {exc.strerror or exc}")
    try:
        return _parse_definition(text)
    except ValueError as exc:
        raise usage_error(f"{path}: {exc}")


def _shared_row(world: World, name: str) -> Optional[SkillStatus]:
    return next((row for row in world.statuses if row.key == ("shared", name)), None)


def _links_of(world: World, name: str) -> Tuple[ConsumerLink, ...]:
    row = _shared_row(world, name)
    return row.links if row is not None else ()


# ------------------------------------------------------------------ read-only


def _phase_lines(index: int, phase: workflows.Phase) -> List[str]:
    lines = [f"  {index}. {_flat(phase.name) or '(unnamed)'}" + ("  [gate]" if phase.gate else "")]
    if phase.goal.strip():
        lines.append(f"     goal:    {_flat(phase.goal)}")
    lines.append(f"     skills:  {', '.join(phase.skills) or '(none)'}")
    if any(step.strip() for step in phase.steps):
        lines.append("     steps:")
        lines.extend(f"       {n}. {_flat(step)}"
                     for n, step in enumerate((s for s in phase.steps if s.strip()), 1))
    if any(output.strip() for output in phase.outputs):
        lines.append(f"     outputs: {', '.join(_flat(o) for o in phase.outputs if o.strip())}")
    if phase.gate:
        lines.append(f"     gate:    {_flat(phase.gate_text) or DEFAULT_GATE_SHOWN}")
    return lines


def _definition_lines(wf: WorkflowDef) -> List[str]:
    lines = [f"{wf.name}  (definition version {wf.version})",
             f"description: {_flat(wf.description) or '(empty)'}",
             f"triggers:    {', '.join(_flat(t) for t in wf.triggers if t.strip()) or '(none)'}",
             f"handback:    {_flat(wf.handback) or '(default)'}",
             f"phases ({len(wf.phases)}):"]
    for index, phase in enumerate(wf.phases, 1):
        lines.extend(_phase_lines(index, phase))
    return lines


def _workflow_show(ctx: Ctx) -> int:
    name = ctx.args.name
    skill_dir = _workflow_dir(ctx, name)
    wf = _read_def(skill_dir, name)
    emit(f"location:    {ctx.paths.display(skill_dir)}")
    for line in _definition_lines(wf):
        emit(line)
    errors, warnings = _validate(ctx, wf)
    emit("")
    emit("validation:")
    for message in errors + warnings:
        emit(f"  {_message_line(message)}")
    if not (errors or warnings):
        emit("  ok")
    return EXIT_USAGE if errors else EXIT_OK


def _workflow_render(ctx: Ctx) -> int:
    name = ctx.args.name
    wf = _read_def(_workflow_dir(ctx, name), name)
    text = workflows.render_skill_md(wf)
    emit(text[:-1] if text.endswith("\n") else text)
    return EXIT_OK


def _workflow_example(ctx: Ctx) -> int:
    wf = workflows.example()
    if ctx.flag("json"):
        emit(workflows.to_json(wf).rstrip("\n"))
        return EXIT_OK
    for line in _definition_lines(wf):
        emit(line)
    emit("")
    emit(EXAMPLE_HINT)
    return EXIT_OK


@dataclass(frozen=True)
class _Row:
    """One line of ``workflow list`` (also its JSON shape)."""

    name: str
    workflow: str
    path: str
    phases: int
    skills: int
    valid: bool
    errors: Tuple[str, ...]
    warnings: Tuple[str, ...]


def _summary(ctx: Ctx, skill_dir: str, wf: WorkflowDef, known: FrozenSet[str]) -> _Row:
    errors, warnings = _validate(ctx, wf, known)
    return _Row(name=os.path.basename(skill_dir), workflow=wf.name, path=skill_dir,
                phases=len(wf.phases), skills=_skill_count(wf), valid=not errors,
                errors=errors, warnings=warnings)


def _notes(row: _Row) -> str:
    notes: List[str] = []
    if row.errors:
        notes.append(f"{len(row.errors)} error(s)")
    if row.warnings:
        notes.append(f"{len(row.warnings)} warning(s)")
    if row.workflow != row.name:
        notes.append(f"definition is named {row.workflow!r}")
    return "; ".join(notes)


def _list_one_by_one(root: str) -> Tuple[Tuple[str, WorkflowDef], ...]:
    """`workflows.list_workflows` for a folder, skipping definitions that overflow the parser."""
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return ()
    found: List[Tuple[str, WorkflowDef]] = []
    for entry in entries:
        if entry in IGNORED_DIR_REASONS or entry.startswith("."):
            continue
        path = os.path.join(root, entry)
        try:
            wf = workflows.load_def(path)
        except RecursionError:
            continue
        if wf is not None:
            found.append((path, wf))
    return tuple(sorted(found, key=lambda item: (item[1].name, item[0])))


def _installed_workflows(ctx: Ctx) -> Tuple[Tuple[str, WorkflowDef], ...]:
    """Every installed workflow. One definition too deeply nested to parse must not hide the
    others: it is skipped like any other unreadable definition."""
    try:
        return workflows.list_workflows(ctx.paths)
    except RecursionError:
        return _list_one_by_one(ctx.paths.install_dir("shared"))


def _workflow_list(ctx: Ctx) -> int:
    known = workflows.known_skill_names(ctx.paths)
    rows = [_summary(ctx, path, wf, known) for path, wf in _installed_workflows(ctx)]
    if ctx.flag("json"):
        dump_json(rows)
        return EXIT_OK
    if not rows:
        emit(NO_WORKFLOWS_HELP)
        return EXIT_OK
    table = [(glyph("ok" if r.valid else "bad"), r.name, str(r.phases), str(r.skills),
              "valid" if r.valid else "invalid", _notes(r)) for r in rows]
    print_table(("", "NAME", "PHASES", "SKILLS", "STATE", "NOTES"), table)
    return EXIT_OK


# ------------------------------------------------------------------ mutating


def _note_dropped_files(dest: str, name: str) -> None:
    """Say so when re-saving leaves files of the old copy behind in the backup folder."""
    try:
        present = skills.list_files(dest)
    except OSError:
        return
    extra = [rel for rel in present if rel not in RENDERED_FILES]
    if not extra:
        return
    more = len(extra) - NOTE_FILE_LIMIT
    shown = ", ".join(extra[:NOTE_FILE_LIMIT]) + (f", and {more} more" if more > 0 else "")
    emit(f"note: shared/{name} holds {len(extra)} file(s) a saved workflow does not carry over "
         f"({shown}); they will stay in the backup folder with its previous copy.")


def _guard_destination(ctx: Ctx, name: str) -> None:
    """`save` may replace an installed workflow of this name (its old copy is backed up) but
    never another installed skill: replacing one is 'update' / 'retire', an explicit action of
    its own, so a collision exits 2 even with --yes and before anything is staged."""
    dest = os.path.join(ctx.paths.install_dir("shared"), name)
    if not os.path.lexists(dest):
        return
    if not os.path.isfile(os.path.join(dest, WORKFLOW_FILE)):
        raise usage_error(
            f"shared/{name} already exists and is not a workflow; nothing was saved. "
            f"Pick another workflow name, or move that skill aside first "
            f"('retire {name} --scope shared').")
    _note_dropped_files(dest, name)


def _print_links(ctx: Ctx, name: str) -> None:
    links = _links_of(load_world(ctx.paths), name)
    if links:
        emit("Links: " + " ".join(f"{link.consumer}={link.state.value}" for link in links))


def _checked_definition(ctx: Ctx) -> WorkflowDef:
    """Read and validate the file argument; errors exit 2 (all printed), warnings print."""
    wf = _load_file(ctx.args.file)
    if wf.name.casefold() in RESERVED_NAMES:
        raise usage_error(f"{wf.name!r} is a tool-managed directory name; "
                          "pick another workflow name")
    errors, warnings = _validate(ctx, wf)
    for message in errors + warnings:
        warn(_message_line(message))
    if errors:
        raise usage_error(f"{ctx.args.file}: {len(errors)} validation error(s); nothing was saved")
    return wf


def _workflow_save(ctx: Ctx) -> int:
    wf = _checked_definition(ctx)
    _guard_destination(ctx, wf.name)
    backup_root = ctx.paths.backup_root(SAVE_LABEL)
    links = _links_of(load_world(ctx.paths), wf.name)
    stage_dir = tempfile.mkdtemp(prefix=STAGE_PREFIX)  # left for the OS to clean up
    ops = workflows.plan_save(wf, ctx.paths, backup_root, stage_dir, links)
    code = run_plan(ctx, ops, backup_root)
    if code == EXIT_OK and not ctx.flag("dry_run"):
        _print_links(ctx, wf.name)
    return code


def _installed_row(ctx: Ctx) -> SkillStatus:
    """The shared status row of the named installed workflow; exit 2 when there is none."""
    name = ctx.args.name
    _workflow_dir(ctx, name)
    row = _shared_row(load_world(ctx.paths), name)
    if row is None:
        raise usage_error(f"{name} is not installed")
    return row


def _run_planned(ctx: Ctx, row: SkillStatus, ops: Tuple[Operation, ...], backup_root: str,
                 reason: str) -> int:
    if not ops:
        emit(f"shared/{row.name}: skipped - {reason}")
    return run_plan(ctx, ops, backup_root)


def _workflow_retire(ctx: Ctx) -> int:
    row = _installed_row(ctx)
    backup_root = ctx.paths.backup_root(RETIRE_LABEL)
    ops = actions.plan_retire(row, ctx.paths, backup_root)
    return _run_planned(ctx, row, ops, backup_root, RETIRE_EMPTY_REASON)


def _workflow_push(ctx: Ctx) -> int:
    row = _installed_row(ctx)
    backup_root = ctx.paths.backup_root(SAVE_LABEL)
    ops = actions.plan_push_to_repo(row, ctx.paths, backup_root)
    return _run_planned(ctx, row, ops, backup_root, PUSH_EMPTY_REASON)


# ------------------------------------------------------------------ dispatch

_HANDLERS: Dict[str, Callable[[Ctx], int]] = {
    "list": _workflow_list,
    "show": _workflow_show,
    "render": _workflow_render,
    "example": _workflow_example,
    "save": _workflow_save,
    "retire": _workflow_retire,
    "push": _workflow_push,
}


def cmd_workflow(ctx: Ctx) -> int:
    return _HANDLERS[ctx.args.workflow_action](ctx)
