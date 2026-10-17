"""Workflow maker: compose installed skills into one phased, gated skill.

A workflow lives in an ordinary shared skill directory
(``~/.agents/skills/<name>/``). Its source of truth is ``workflow.json``; the
installer renders ``SKILL.md`` and ``agents/openai.yaml`` from it, so Claude
Code and Codex run the result like any other skill.

Pure data in, pure data out. The only filesystem access is reading definitions
(``load_def``, ``list_workflows``, ``known_skill_names``) and writing the three
rendered files into a caller-chosen stage directory (``stage``). ``plan_save``
returns ``Operation`` tuples for ``core.actions.apply``; an existing copy is only
ever moved under the backup root, never deleted.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from installer.core.frontmatter import SKILL_FILE
from installer.core.paths import Paths
from installer.core.skills import is_valid_name, scan_catalog, scan_installed
from installer.core.types import (
    CONSUMERS,
    IGNORED_DIR_REASONS,
    ConsumerLink,
    LinkState,
    Operation,
)

WORKFLOW_FILE = "workflow.json"
MARKER = "<!-- ai-suite:workflow -->"
OPENAI_YAML = os.path.join("agents", "openai.yaml")
WARNING_PREFIX = "warning: "
DEFAULT_GATE_TEXT = "the user approves this phase's outputs before the next phase starts"
CLOSING_LINE = ("Edit this workflow with ./install.sh (Workflows tab); the source of truth "
                "is workflow.json next to this file.")
TRIGGER_PREFIX = "Use when the user says: "
BRAND_COLOR = "#7C3AED"
SHORT_DESCRIPTION_MAX = 100

# YAML plain scalars we emit unquoted; anything else is double-quoted.
_PLAIN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ,.()/+&-]*$")
_RESERVED_SCALARS = frozenset(("true", "false", "null", "yes", "no", "on", "off", "y", "n"))


@dataclass(frozen=True)
class Phase:
    name: str
    goal: str
    skills: Tuple[str, ...]
    steps: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    gate: bool = False
    gate_text: str = ""


@dataclass(frozen=True)
class WorkflowDef:
    name: str
    description: str
    triggers: Tuple[str, ...]
    phases: Tuple[Phase, ...]
    handback: str = ""
    version: int = 1


def to_json(wf: WorkflowDef) -> str:
    """Stable, human-editable JSON: indent 2, field order, trailing newline."""
    return json.dumps(asdict(wf), indent=2, ensure_ascii=False) + "\n"


def from_json(text: str) -> WorkflowDef:
    """Parse a definition. ``ValueError`` with a clear message on any bad shape.

    Required: the top-level object, its ``name`` and each phase's ``name``.
    Everything else defaults (empty text, empty lists, ``gate`` false,
    ``version`` 1); ``null`` counts as absent. Unknown keys are ignored.
    Whether the values make a *good* workflow is ``validate``'s job.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"workflow definition is not valid JSON: {exc}") from exc
    root = _object(data, "workflow definition")
    return WorkflowDef(
        name=_field(root, "name", "workflow", "str", required=True),
        description=_field(root, "description", "workflow", "str"),
        triggers=_field(root, "triggers", "workflow", "strs"),
        phases=_parse_phases(root.get("phases")),
        handback=_field(root, "handback", "workflow", "str"),
        version=_field(root, "version", "workflow", "int"),
    )


_JSON_NAMES = {"NoneType": "null", "bool": "boolean", "int": "number", "float": "number",
               "dict": "object", "list": "array", "str": "string"}


def _json_type(value: Any) -> str:
    """The JSON name of a parsed value's type, for error messages."""
    return _JSON_NAMES.get(type(value).__name__, type(value).__name__)


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a JSON object, got {_json_type(value)}")
    return value


# kind -> (default when absent, accepts(value), what the message says is expected)
_KINDS = {
    "str": ("", lambda v: isinstance(v, str), "a string"),
    "bool": (False, lambda v: isinstance(v, bool), "true or false"),
    "int": (1, lambda v: isinstance(v, int) and not isinstance(v, bool), "an integer"),
    "strs": ((), lambda v: isinstance(v, list), "a list of strings"),
}


def _field(obj: Mapping[str, Any], key: str, where: str, kind: str,
           required: bool = False) -> Any:
    default, accepts, expected = _KINDS[kind]
    value = obj.get(key)
    if value is None:
        if required:
            raise ValueError(f"{where}: missing required field {key!r}")
        return default
    if not accepts(value):
        raise ValueError(f"{where}: {key!r} must be {expected}, got {_json_type(value)}")
    if kind == "strs":
        bad = next((i for i, item in enumerate(value) if not isinstance(item, str)), None)
        if bad is not None:
            raise ValueError(f"{where}: {key!r}[{bad}] must be a string, "
                             f"got {_json_type(value[bad])}")
        return tuple(value)
    return value


def _parse_phases(value: Any) -> Tuple[Phase, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"workflow: 'phases' must be a list of objects, got {_json_type(value)}")
    return tuple(_parse_phase(raw, index) for index, raw in enumerate(value, start=1))


def _parse_phase(raw: Any, index: int) -> Phase:
    where = f"phase {index}"
    obj = _object(raw, where)
    name = _field(obj, "name", where, "str", required=True)
    if name:
        where = f"phase {index} ({name!r})"
    return Phase(
        name=name,
        goal=_field(obj, "goal", where, "str"),
        skills=_field(obj, "skills", where, "strs"),
        steps=_field(obj, "steps", where, "strs"),
        outputs=_field(obj, "outputs", where, "strs"),
        gate=_field(obj, "gate", where, "bool"),
        gate_text=_field(obj, "gate_text", where, "str"),
    )


def load_def(skill_dir: str) -> Optional[WorkflowDef]:
    """The definition in ``<skill_dir>/workflow.json``; ``None`` when the file is
    missing, unreadable or not a valid definition (so listings never crash)."""
    try:
        with open(os.path.join(skill_dir, WORKFLOW_FILE), "r", encoding="utf-8") as handle:
            text = handle.read()
        return from_json(text)
    except (OSError, ValueError):
        return None


def list_workflows(paths: Paths) -> Tuple[Tuple[str, WorkflowDef], ...]:
    """``(skill_dir, definition)`` for every shared skill with a valid
    ``workflow.json``, sorted by workflow name."""
    root = paths.install_dir("shared")
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return ()
    dirs = [os.path.join(root, entry) for entry in entries
            if entry not in IGNORED_DIR_REASONS and not entry.startswith(".")]
    found = [(path, wf) for path in dirs for wf in (load_def(path),) if wf is not None]
    return tuple(sorted(found, key=lambda item: (item[1].name, item[0])))


def known_skill_names(paths: Paths) -> FrozenSet[str]:
    """The repo catalog plus every skill dir (or link) installed under shared,
    claude or codex; tool-managed and hidden entries are left out."""
    catalog, _issues = scan_catalog(paths)
    names = {name for (_scope, name) in catalog}
    names.update(entry.name for entry in scan_installed(paths).values()
                 if entry.ignored_reason is None and entry.kind in ("dir", "symlink"))
    return frozenset(names)


def _name_ok(name: str) -> bool:
    return is_valid_name(name) and name == name.strip()


def validate(wf: WorkflowDef, known_skills: FrozenSet[str]) -> Tuple[str, ...]:
    """Errors (block saving) first, then warnings prefixed ``"warning: "``.

    Errors: invalid name, empty description, no phases, a phase without a
    name, duplicate phase names, a phase with neither skills nor steps, an
    invalid skill name. Warnings: a skill that is not in ``known_skills`` (the
    installed shared/claude/codex names plus the repo catalog).
    """
    errors: List[str] = []
    if not _name_ok(wf.name):
        errors.append(f"invalid workflow name {wf.name!r}: use one visible path component, "
                      f"for example 'my-workflow'")
    if not wf.description.strip():
        errors.append("description is empty")
    if not wf.phases:
        errors.append("workflow has no phases")
    errors.extend(_phase_errors(wf.phases))
    return tuple(errors) + _skill_warnings(wf.phases, known_skills)


def _phase_errors(phases: Sequence[Phase]) -> List[str]:
    errors: List[str] = []
    seen: Dict[str, int] = {}
    for index, phase in enumerate(phases, start=1):
        name = phase.name.strip()
        label = f"phase {index} ({name!r})" if name else f"phase {index}"
        if not name:
            errors.append(f"{label} has no name")
        elif name.casefold() in seen:
            errors.append(f"duplicate phase name {name!r} (phases {seen[name.casefold()]} "
                          f"and {index})")
        else:
            seen[name.casefold()] = index
        if not phase.skills and not any(step.strip() for step in phase.steps):
            errors.append(f"{label} has neither skills nor steps")
        errors.extend(f"{label} lists an invalid skill name {skill!r}"
                      for skill in phase.skills if not _name_ok(skill))
    return errors


def _skill_warnings(phases: Sequence[Phase], known: FrozenSet[str]) -> Tuple[str, ...]:
    used: Dict[str, List[str]] = {}
    for index, phase in enumerate(phases, start=1):
        for skill in _unique(phase.skills):
            if _name_ok(skill) and skill not in known:
                used.setdefault(skill, []).append(str(index))
    return tuple(f"{WARNING_PREFIX}skill {skill!r} is neither installed nor in the repo "
                 f"catalog (phase {', '.join(where)})" for skill, where in used.items())


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _unique(items: Sequence[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item.strip()))


def _display_name(name: str) -> str:
    """"deep-research" -> "Deep Research" (used for the H1 and Codex display name)."""
    words = _one_line(name.replace("-", " ").replace("_", " ")).split(" ")
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or "Workflow"


def _dq(text: str) -> str:
    """A YAML double-quoted scalar (also understood by core.frontmatter)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _scalar(text: str) -> str:
    """Plain YAML scalar when that is unambiguous, else double-quoted."""
    plain = (bool(_PLAIN_RE.match(text)) and text == text.strip()
             and text.lower() not in _RESERVED_SCALARS)
    return text if plain else _dq(text)


def _frontmatter_description(wf: WorkflowDef) -> str:
    triggers = [_one_line(t) for t in wf.triggers if t.strip()]
    suffix = TRIGGER_PREFIX + ", ".join(triggers) if triggers else ""
    return " ".join(part for part in (_one_line(wf.description), suffix) if part)


def render_skill_md(wf: WorkflowDef) -> str:
    """Deterministic SKILL.md; the same definition always yields identical text."""
    frontmatter = (f"---\nname: {_scalar(wf.name)}\n"
                   f"description: {_scalar(_frontmatter_description(wf))}\n---\n{MARKER}")
    blocks = [frontmatter, f"# {_display_name(wf.name)}"]
    if wf.description.strip():
        blocks.append(_one_line(wf.description))
    blocks.append(_flow_paragraph(wf.phases))
    blocks.append(_skills_table(wf.phases))
    blocks.extend(_render_phase(index, phase) for index, phase in enumerate(wf.phases, start=1))
    blocks.append("## Handback\n\n" + (wf.handback.strip() or _default_handback(wf.phases)))
    blocks.append(CLOSING_LINE)
    return "\n\n".join(blocks) + "\n"


def _flow_paragraph(phases: Sequence[Phase]) -> str:
    if not phases:
        return "This workflow has no phases yet."
    count, gated = len(phases), sum(1 for phase in phases if phase.gate)
    text = (f"This workflow has {count} phase{'' if count == 1 else 's'}. Run them in order "
            f"and do not start a phase until the previous one has produced its outputs.")
    if gated:
        text += (" A phase marked as gated stops for the user: show its outputs and wait "
                 "for approval before going on.")
    return text


def _skills_table(phases: Sequence[Phase]) -> str:
    used: Dict[str, List[str]] = {}
    for index, phase in enumerate(phases, start=1):
        for skill in _unique(phase.skills):
            used.setdefault(skill, []).append(f"Phase {index} - {_one_line(phase.name)}")
    heading = "## Skills this workflow loads"
    if not used:
        return f"{heading}\n\nNone; every phase is described by its steps."
    rows = [f"| `{skill}` | {', '.join(where).replace('|', chr(92) + '|')} |"
            for skill, where in used.items()]
    return "\n".join([heading, "", "| Skill | Used in |", "| --- | --- |"] + rows)


def _render_phase(index: int, phase: Phase) -> str:
    parts = [f"## Phase {index} - {_one_line(phase.name)}"]
    if phase.goal.strip():
        parts.append(f"**Goal:** {_one_line(phase.goal)}")
    skills = _unique(phase.skills)
    if skills:
        listed = ", ".join(f"`{skill}`" for skill in skills)
        parts.append(f"Load: {listed} (read each skill's SKILL.md before acting).")
    steps = [_one_line(step) for step in phase.steps if step.strip()]
    if steps:
        parts.append("**Steps:**\n\n" + "\n".join(f"{n}. {s}" for n, s in enumerate(steps, 1)))
    outputs = [_one_line(output) for output in phase.outputs if output.strip()]
    if outputs:
        parts.append("**Outputs:**\n\n" + "\n".join(f"- {output}" for output in outputs))
    if phase.gate:
        text = _one_line(phase.gate_text) or DEFAULT_GATE_TEXT
        parts.append(f"**Gate:** {text}" + ("" if text[-1] in ".!?" else "."))
    return "\n\n".join(parts)


def _default_handback(phases: Sequence[Phase]) -> str:
    lines = ["When the last phase is done, report to the user in a short summary:", ""]
    for index, phase in enumerate(phases, start=1):
        outputs = [_one_line(o) for o in phase.outputs if o.strip()]
        lines.append(f"- Phase {index} - {_one_line(phase.name)}: "
                     f"{', '.join(outputs) if outputs else 'no recorded outputs'}")
    if any(phase.gate for phase in phases):
        lines.append("- The decisions the user made when a phase stopped for approval.")
    lines.append("- Anything left undone or not verified, stated plainly.")
    return "\n".join(lines)


def render_openai_yaml(wf: WorkflowDef) -> str:
    """Codex display metadata; same shape as the other shared skills' openai.yaml."""
    lines = [
        "interface:",
        f"  display_name: {_dq(_display_name(wf.name))}",
        f"  short_description: {_dq(_short_description(wf))}",
        f"  brand_color: {_dq(BRAND_COLOR)}",
        f"  default_prompt: {_dq(_default_prompt(wf))}",
        "policy:",
        "  allow_implicit_invocation: true",
    ]
    return "\n".join(lines) + "\n"


def _short_description(wf: WorkflowDef) -> str:
    text = _one_line(wf.description) or _display_name(wf.name)
    if len(text) <= SHORT_DESCRIPTION_MAX:
        return text
    cut = text[:SHORT_DESCRIPTION_MAX - 3].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "..."


def _default_prompt(wf: WorkflowDef) -> str:
    names = [_one_line(phase.name) for phase in wf.phases if phase.name.strip()]
    prompt = f"Run the {wf.name} workflow"
    if names:
        prompt += f" one phase at a time: {', '.join(names)}"
    if any(phase.gate for phase in wf.phases):
        prompt += ", and wait for my approval at every gate"
    return prompt


def stage(wf: WorkflowDef, stage_dir: str) -> str:
    """Write SKILL.md, workflow.json and agents/openai.yaml under
    ``<stage_dir>/<name>/`` and return that directory. ``ValueError`` for a name
    that is not a single visible path component."""
    if not _name_ok(wf.name):
        raise ValueError(f"invalid workflow name {wf.name!r}")
    root = os.path.join(stage_dir, wf.name)
    files = (
        (SKILL_FILE, render_skill_md(wf)),
        (WORKFLOW_FILE, to_json(wf)),
        (OPENAI_YAML, render_openai_yaml(wf)),
    )
    for rel, text in files:
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    return root


def _place(ops: Tuple[Operation, ...], op: Operation) -> Tuple[Operation, ...]:
    """Append `op`, preceded by a mkdir of its parent when that does not exist yet."""
    parent = os.path.dirname(op.dst)
    planned = any(o.kind == "mkdir" and o.dst == parent for o in ops)
    if planned or os.path.isdir(parent):
        return ops + (op,)
    return ops + (Operation(kind="mkdir", dst=parent), op)


def _unlinked_consumers(name: str, paths: Paths,
                        links: Tuple[ConsumerLink, ...]) -> Tuple[str, ...]:
    """Consumers that need a new symlink: those whose given link is MISSING, and
    those without a given link when nothing exists at their path."""
    given = {link.consumer: link.state == LinkState.MISSING for link in links}
    absent = {c: not os.path.lexists(os.path.join(paths.consumer_dir(c), name)) for c in CONSUMERS}
    return tuple(consumer for consumer in CONSUMERS if given.get(consumer, absent[consumer]))


def plan_save(wf: WorkflowDef, paths: Paths, backup_root: str, stage_dir: str,
              links: Tuple[ConsumerLink, ...] = ()) -> Tuple[Operation, ...]:
    """Stage the workflow, then plan putting it in place as a shared skill.

    An existing ``~/.agents/skills/<name>`` is moved to
    ``<backup_root>/shared/<name>`` first; the staged directory is copied into
    place; each consumer whose link is MISSING gets a symlink. A consumer with a
    REAL_DIR, WRONG_TARGET, BROKEN or FILE entry is left alone (the Issues
    screen handles those). A consumer missing from ``links`` is checked on
    disk, so a brand-new workflow (which has no status row yet) is still linked.
    """
    staged = stage(wf, stage_dir)
    name = wf.name
    dest = os.path.join(paths.install_dir("shared"), name)
    ops: Tuple[Operation, ...] = ()
    if os.path.lexists(dest):
        kind = "unlink-to-backup" if os.path.islink(dest) else "backup"
        ops += (Operation(kind=kind, dst=os.path.join(backup_root, "shared", name), src=dest,
                          note=f"keep the previous copy of shared/{name}"),)
    ops = _place(ops, Operation(kind="copytree", dst=dest, src=staged,
                                note=f"save workflow {name}"))
    for consumer in _unlinked_consumers(name, paths, links):
        ops = _place(ops, Operation(
            kind="symlink", dst=os.path.join(paths.consumer_dir(consumer), name),
            src=paths.expected_link_target(consumer, name),
            note=f"link {consumer} -> shared/{name}"))
    return ops


def _example_phases() -> Tuple[Phase, ...]:
    return (
        Phase("Research", "Understand the problem and the prior art before proposing anything.",
              ("deep-research",),
              ("Restate the question and what would change the decision.",
               "Search broadly, read the strongest sources, cite every claim."),
              ("docs/research.md",), gate=True,
              gate_text="the user confirms the findings and picks the direction to design"),
        Phase("Design", "Turn the chosen direction into a structure and look the user can approve.",
              ("information-architecture", "frontend-design"),
              ("Draft the screens or modules and how they connect.",
               "Choose a visual direction that fits the audience."),
              ("docs/design.md",), gate=True),
        Phase("Build", "Implement the approved design test-first and verify it works.",
              ("tdd-workflow",),
              ("Write a failing test per behaviour, then make it pass.",
               "Run the full test suite and fix what it finds."),
              ("the implementation and its tests", "a short build report")),
    )


def example() -> WorkflowDef:
    """A 3-phase sample (research -> design -> build) to start from. It only
    uses skills that exist in this repo's shared/skills."""
    return WorkflowDef(
        name="research-design-build",
        description=("Take a feature from research through design to a tested build, "
                     "stopping for approval after research and after design."),
        triggers=("research design build", "plan and build this feature",
                  "take this from idea to code"),
        phases=_example_phases(),
    )
