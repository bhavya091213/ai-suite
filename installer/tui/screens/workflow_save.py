"""What the workflow editor checks before a save and what it keeps through one.

``core.workflows.plan_save`` moves the whole ``~/.agents/skills/<name>`` into a backup and copies back only
the three files the installer writes. Nothing is lost, because the backup keeps it, but the live skill
would silently lose every other file in its directory and every ``workflow.json`` key the editor does not
know. So a save copies those files into the staged copy first and names whatever stays behind in the
confirm dialog. A name the tools would not run as this workflow (tool-managed, shadowed by another skill)
is refused before anything is staged.

Everything here only reads the live directory; the one write is the copy into the caller's stage directory.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import fields, replace
from typing import Any, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from installer.core import workflows
from installer.core.frontmatter import SKILL_FILE
from installer.core.paths import Paths
from installer.core.skills import is_valid_name, list_files
from installer.core.types import CONSUMERS, IGNORED_DIR_REASONS, Operation
from installer.core.workflows import OPENAI_YAML, WORKFLOW_FILE, Phase, WorkflowDef
from installer.tui.screens.skill_picker import plural

# list_files reports POSIX relative paths
MANAGED_FILES = frozenset((SKILL_FILE, WORKFLOW_FILE, OPENAI_YAML.replace(os.sep, "/")))


# ----------------------------------------------------------------- the name


def reserved_error(name: str) -> Optional[str]:
    """An error for a name the installer leaves to the tools (``learned``, ``synced``), else None.

    Names that ``is_valid_name`` already refuses (``.system``) are left to ``workflows.validate``.
    """
    key = name.strip().casefold()
    for reserved, reason in IGNORED_DIR_REASONS.items():
        if reserved.casefold() == key and is_valid_name(reserved):
            return f"workflow name {name!r} is reserved: {reason}"
    return None


def edit_issues(wf: WorkflowDef, known: FrozenSet[str]) -> Tuple[str, ...]:
    """``workflows.validate`` plus the reserved-name error; errors first, warnings last, as there."""
    reserved = reserved_error(wf.name)
    issues = workflows.validate(wf, known)
    return issues if reserved is None else (reserved,) + issues


def tools_in_the_way(name: str, paths: Paths) -> Tuple[Tuple[str, str], ...]:
    """``(tool, path)`` for each tool whose entry named `name` is not a link to the shared copy.

    ``plan_save`` leaves those entries alone, so that tool would keep running whatever sits there.
    """
    shared = os.path.realpath(os.path.join(paths.install_dir("shared"), name))
    found: List[Tuple[str, str]] = []
    for consumer in CONSUMERS:
        entry = os.path.join(paths.consumer_dir(consumer), name)
        if os.path.lexists(entry) and not (os.path.islink(entry) and os.path.realpath(entry) == shared):
            found.append((consumer, entry))
    return tuple(found)


def name_taken(name: str, paths: Paths, catalog: Mapping[Tuple[str, str], Any]) -> Optional[str]:
    """Why a workflow that is not yet saved cannot use `name`, or None.

    Taken means: a shared skill of that name exists, a tool has its own entry of that name, or the repo
    catalog has a skill of that name in any scope.
    """
    shared = os.path.join(paths.install_dir("shared"), name)
    if os.path.lexists(shared):
        return f"{paths.display(shared)} already exists and is not this workflow"
    blocked = tools_in_the_way(name, paths)
    if blocked:
        places = " and ".join(paths.display(entry) for _tool, entry in blocked)
        tools = " and ".join(tool for tool, _entry in blocked)
        return (f"{places} {'is' if len(blocked) == 1 else 'are'} already taken, so {tools} would keep "
                f"running that instead of this workflow")
    scopes = sorted(scope for scope, skill in catalog if skill == name)
    if scopes:
        return f"{name} is already a skill in the repo catalog ({', '.join(scopes)})"
    return None


# ------------------------------------------------------ what a save carries


def unmanaged_files(skill_dir: str) -> Tuple[str, ...]:
    """Relative paths of the files in `skill_dir` that the installer does not write itself."""
    return tuple(rel for rel in list_files(skill_dir) if rel not in MANAGED_FILES)


def carry_unmanaged(skill_dir: str, staged_root: str) -> Tuple[str, ...]:
    """Copy (never move) those files into the staged copy; returns their relative paths.

    Symlinks are copied as symlinks. The stage directory must be a fresh one, so a file removed from
    the live skill since an earlier save cannot come back.
    """
    kept = unmanaged_files(skill_dir)
    for rel in kept:
        parts = rel.split("/")
        destination = os.path.join(staged_root, *parts)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(os.path.join(skill_dir, *parts), destination, follow_symlinks=False)
    return kept


def _field_names(cls: Any) -> Tuple[str, ...]:
    return tuple(item.name for item in fields(cls))


def unknown_keys(skill_dir: str) -> Tuple[str, ...]:
    """Keys of the live ``workflow.json`` that ``WorkflowDef`` / ``Phase`` do not have (they are not
    read, so a save writes none of them back); phase keys are named as ``phase N key``."""
    try:
        with open(os.path.join(skill_dir, WORKFLOW_FILE), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    extra = [key for key in data if key not in _field_names(WorkflowDef)]
    phases = data.get("phases")
    for number, phase in enumerate(phases if isinstance(phases, list) else (), start=1):
        if isinstance(phase, dict):
            extra.extend(f"phase {number} {key}" for key in phase if key not in _field_names(Phase))
    return tuple(extra)


# ------------------------------------------------------------ the confirm


def save_notes(kept: Sequence[str], dropped_keys: Sequence[str],
               unlinked: Sequence[Tuple[str, str]]) -> Tuple[str, ...]:
    """Short phrases for whatever the confirm dialog should say about this save; empty when nothing."""
    notes: List[str] = []
    if kept:
        notes.append(f"keeps {plural(len(kept), 'other file')}")
    if dropped_keys:
        notes.append("workflow.json keys kept only in the backup: " + ", ".join(dropped_keys))
    if unlinked:
        notes.append("not linked into " + " and ".join(tool for tool, _entry in unlinked)
                     + " (it has its own entry of this name)")
    return tuple(notes)


def save_title(name: str, notes: Sequence[str]) -> str:
    return f"Save workflow {name}" + (f" ({'; '.join(notes)})" if notes else "")


def with_notes(ops: Sequence[Operation], notes: Sequence[str]) -> Tuple[Operation, ...]:
    """`ops` with the notes appended to the note of the copy that puts the workflow in place."""
    if not notes:
        return tuple(ops)
    return tuple(replace(op, note=f"{op.note}; {'; '.join(notes)}") if op.kind == "copytree" else op
                 for op in ops)
