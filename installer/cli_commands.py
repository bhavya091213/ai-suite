"""Skill and git commands: status, list, issues, tree, show, install, update, retire,
relink, push, updates, pull.

Each ``cmd_*`` takes a :class:`~installer.cli_io.Ctx` and returns an exit status.
Mutating commands build plans with ``installer.core.actions`` and hand them to
``cli_io.run_plan``, so every one of them previews, confirms and reports the same way.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from installer.cli_io import (
    EXIT_FAIL, EXIT_OK, Ctx, confirm, dump_json, emit, failure, glyph, print_table,
    read_text, run_plan, truncate, usage_error, use_unicode, warn,
)
from installer.core import actions, git, skills, tree
from installer.core import status as status_core
from installer.core.paths import Paths
from installer.core.types import (
    LinkState, Operation, RemoteChange, RepoIssue, SkillStatus, State,
)

Key = Tuple[str, str]
Planner = Callable[[SkillStatus, str], Tuple[Operation, ...]]

DESCRIPTION_WIDTH = 60
SKILL_FILE = "SKILL.md"


@dataclass(frozen=True)
class World:
    """One consistent snapshot of the catalog, the disk and the computed status rows."""

    catalog: Mapping
    repo_issues: Tuple[RepoIssue, ...]
    installed: Mapping
    statuses: Tuple[SkillStatus, ...]


def load_world(paths: Paths, with_remote: bool = False) -> World:
    catalog, issues = skills.scan_catalog(paths)
    installed = skills.scan_installed(paths)
    remote: Dict[Key, RemoteChange] = {}
    if with_remote:
        info = git.detect(paths)
        if info.available and info.is_repo and info.upstream:
            remote = git.remote_changes(paths, catalog)
    rows = status_core.compute(catalog, installed, paths, remote, issues)
    return World(catalog=catalog, repo_issues=issues, installed=installed, statuses=rows)


def resolve(world: World, name: str, scope: Optional[str]) -> SkillStatus:
    """The one status row called `name` (in `scope` when given); exit 2 on none or several."""
    if not skills.is_valid_name(name):
        raise usage_error(f"invalid skill name: {name!r}")
    rows = [s for s in world.statuses if s.name == name and (scope is None or s.scope == scope)]
    if not rows:
        where = f" in scope {scope}" if scope else ""
        raise usage_error(f"unknown skill: {name}{where}")
    if len(rows) > 1:
        options = "\n".join(f"  --scope {s.scope}  ({s.state.value})" for s in rows)
        raise usage_error(f"{name} exists in several scopes; pick one with --scope:\n{options}")
    return rows[0]


def _resolve_all(world: World, names: Sequence[str], scope: Optional[str]) -> Tuple[SkillStatus, ...]:
    rows: List[SkillStatus] = []
    for name in names:
        row = resolve(world, name, scope)
        if row.key not in [r.key for r in rows]:
            rows.append(row)
    return tuple(rows)


def _scope_rows(world: World, scope: Optional[str]) -> Tuple[SkillStatus, ...]:
    return tuple(s for s in world.statuses if scope is None or s.scope == scope)


# ------------------------------------------------------------------ read-only


def _links_text(row: SkillStatus) -> str:
    return " ".join(f"{link.consumer}={link.state.value}" for link in row.links)


def _notes_text(row: SkillStatus) -> str:
    notes: List[str] = []
    if row.remote is not None:
        notes.append(f"{glyph('remote')} {len(row.remote.files)} file(s) upstream")
    if row.issues:
        notes.append(f"{glyph('problem')} {len(row.issues)} issue(s)")
    elif row.duplicates:
        notes.append(f"{glyph('problem')} {len(row.duplicates)} note(s)")
    return "  ".join(notes)


def _counts_line(world: World, scope: Optional[str]) -> str:
    parts = []
    for c in status_core.counts(world.statuses):
        if scope is None or c.scope == scope:
            parts.append(f"{c.scope}: {c.available} in repo, {c.installed} installed, "
                         f"{c.modified} modified, {c.missing} not installed, "
                         f"{c.foreign} foreign, {c.problems} with problems")
    return "\n".join(parts)


def cmd_status(ctx: Ctx) -> int:
    world = load_world(ctx.paths, with_remote=True)
    scope = ctx.flag("scope", None)
    rows = _scope_rows(world, scope)
    if ctx.flag("json"):
        dump_json(rows)
        return EXIT_OK
    table = [(glyph(r.state.value), r.scope, r.name, r.state.value, _links_text(r), _notes_text(r))
             for r in rows]
    print_table(("", "SCOPE", "NAME", "STATE", "LINKS", "NOTES"), table)
    emit("")
    emit(_counts_line(world, scope))
    return EXIT_OK


def _install_label(row: SkillStatus) -> str:
    return {State.INSTALLED: "yes", State.MODIFIED: "modified"}.get(row.state, "no")


def cmd_list(ctx: Ctx) -> int:
    world = load_world(ctx.paths, with_remote=True)
    rows = [r for r in _scope_rows(world, ctx.flag("scope", None)) if r.source is not None]
    if ctx.flag("json"):
        dump_json([{"scope": r.scope, "name": r.name, "state": r.state, "installed": _install_label(r),
                    "description": r.description, "path": r.source.path if r.source else None}
                   for r in rows])
        return EXIT_OK
    table = [(glyph(r.state.value), r.scope, r.name, _install_label(r),
              truncate(r.description, DESCRIPTION_WIDTH)) for r in rows]
    print_table(("", "SCOPE", "NAME", "INSTALLED", "DESCRIPTION"), table)
    return EXIT_OK


def _print_problem(row: SkillStatus) -> None:
    emit(f"{row.scope}/{row.name}  [{row.state.value}]")
    for text in row.issues:
        emit(f"  problem: {text}")
    for text in row.duplicates:
        emit(f"  note:    {text}")


def cmd_issues(ctx: Ctx) -> int:
    world = load_world(ctx.paths)
    problems = status_core.problems(world.statuses)
    seen = {row.key for row in problems}
    loose = tuple(i for i in world.repo_issues if (i.scope, i.name) not in seen)
    if ctx.flag("json"):
        dump_json({"problems": problems, "repo_issues": loose})
        return EXIT_OK
    if not problems and not loose:
        emit("No problems found.")
        return EXIT_OK
    for row in problems:
        _print_problem(row)
    for issue in loose:
        emit(f"{issue.scope}/{issue.name}  [repo]")
        emit(f"  problem: {issue.message}")
    return EXIT_OK


def _skill_root(row: SkillStatus) -> Tuple[str, str]:
    """(directory to read, where it is): the installed copy when there is one, else the repo copy."""
    entry = row.installed
    if entry is not None and entry.ignored_reason is None and entry.kind in ("dir", "symlink"):
        return entry.resolved or entry.path, "installed"
    if row.source is not None:
        return row.source.path, "repo"
    raise failure(f"{row.scope}/{row.name} has no readable directory on disk or in the repo")


def cmd_tree(ctx: Ctx) -> int:
    world = load_world(ctx.paths)
    row = resolve(world, ctx.args.name, ctx.flag("scope", None))
    root, where = _skill_root(row)
    emit(f"{row.scope}/{row.name}  ({where}: {ctx.paths.display(root)})")
    for line in tree.render(tree.build_tree(root), ascii_only=not use_unicode()):
        emit(line)
    return EXIT_OK


def _inside(root: str, rel: str) -> str:
    """Absolute path of `rel` under `root`, or a usage error when it would escape the skill."""
    real_root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel))
    if os.path.isabs(rel) or not (target == real_root or target.startswith(real_root + os.sep)):
        raise usage_error(f"{rel}: path is outside the skill directory")
    return target


def cmd_show(ctx: Ctx) -> int:
    world = load_world(ctx.paths)
    row = resolve(world, ctx.args.name, ctx.flag("scope", None))
    root, _ = _skill_root(row)
    rel = ctx.flag("file", None) or SKILL_FILE
    target = _inside(root, rel)
    if not os.path.isfile(target):
        raise failure(f"{rel}: no such file in {row.scope}/{row.name}")
    text = read_text(target)
    emit(text[:-1] if text.endswith("\n") else text)
    return EXIT_OK


# ------------------------------------------------------------------ mutating


def _empty_reason(command: str, row: SkillStatus) -> str:
    reasons = {
        "install": f"already {row.state.value}" if row.state != State.NOT_INSTALLED else "not installable",
        "update": "only modified skills can be updated" if row.state != State.MODIFIED else "no change",
        "retire": "nothing installed to retire" if row.installed is None else "tool-managed entry",
        "push": "nothing pushable (not a readable directory, or it already is the repo copy)",
        "relink": "no link needs fixing",
    }
    return reasons.get(command, "nothing to do")


def _skipped_links(command: str, row: SkillStatus) -> Tuple[str, ...]:
    if command != "install" or row.scope != "shared":
        return ()
    return tuple(f"{row.name}: {link.consumer} entry is {link.state.value}; left alone (see 'relink')"
                 for link in row.links if link.state not in (LinkState.MISSING, LinkState.OK))


def _collect(command: str, rows: Sequence[SkillStatus], planner: Planner,
             backup_root: str) -> Tuple[Operation, ...]:
    ops: Tuple[Operation, ...] = ()
    for row in rows:
        planned = planner(row, backup_root)
        if not planned:
            emit(f"{row.scope}/{row.name}: skipped - {_empty_reason(command, row)}")
            continue
        ops += planned
        for note in _skipped_links(command, row):
            emit(f"note: {note}")
    return ops


def _mutate(ctx: Ctx, command: str, label: str, planner: Planner,
            rows: Optional[Sequence[SkillStatus]] = None) -> int:
    world = load_world(ctx.paths)
    chosen = rows if rows is not None else _resolve_all(world, ctx.args.names, ctx.flag("scope", None))
    backup_root = ctx.paths.backup_root(label)
    return run_plan(ctx, _collect(command, chosen, planner, backup_root), backup_root)


def cmd_install(ctx: Ctx) -> int:
    paths = ctx.paths
    return _mutate(ctx, "install", "installer", lambda row, root: actions.plan_install(row, paths))


def cmd_update(ctx: Ctx) -> int:
    paths = ctx.paths
    return _mutate(ctx, "update", "installer", lambda row, root: actions.plan_update(row, paths, root))


def cmd_retire(ctx: Ctx) -> int:
    paths, only_links = ctx.paths, bool(ctx.flag("consumers_only"))
    return _mutate(ctx, "retire", "retired-skills",
                   lambda row, root: actions.plan_retire(row, paths, root, consumers_only=only_links))


def cmd_push(ctx: Ctx) -> int:
    paths = ctx.paths
    return _mutate(ctx, "push", "installer", lambda row, root: actions.plan_push_to_repo(row, paths, root))


def cmd_relink(ctx: Ctx) -> int:
    world = load_world(ctx.paths)
    names = ctx.flag("names", ()) or ()
    rows = _resolve_all(world, names, "shared") if names else _scope_rows(world, "shared")
    paths, index = ctx.paths, world.installed
    backup_root = paths.backup_root("installer")
    ops: Tuple[Operation, ...] = ()
    for row in rows:
        planned = actions.plan_relink(row, paths, backup_root, installed_index=index)
        ops += planned
        _explain_untouched(row, planned, bool(names))
    return run_plan(ctx, ops, backup_root)


def _explain_untouched(row: SkillStatus, planned: Tuple[Operation, ...], named: bool) -> None:
    """Say why a link problem (or a named skill) was not changed by the relink plan."""
    fixed = {op.dst for op in planned}
    left = [link for link in row.link_problems if link.path not in fixed]
    for link in left:
        emit(f"{row.name}: {link.consumer} is {link.state.value}; not changed "
             "(different content or not a directory - resolve it by hand)")
    if named and not planned and not left:
        emit(f"{row.scope}/{row.name}: skipped - {_empty_reason('relink', row)}")


# ------------------------------------------------------------------ git


def _fmt_time(epoch: Optional[float]) -> str:
    if epoch is None:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch))


def _print_banner(info) -> None:
    emit(info.message)
    if info.hint:
        emit(f"hint: {info.hint}")
    if info.branch:
        emit(f"branch {info.branch} @ {info.head}  upstream {info.upstream or '(none)'}  "
             f"last fetch {_fmt_time(info.last_fetch)}")
    if info.error:
        warn(f"git: {info.error}")


def _upstream_data(ctx: Ctx, info) -> Tuple[Tuple[str, ...], Mapping[Key, RemoteChange]]:
    """Commits behind the upstream and the skills they touch; empty when there is no upstream."""
    if not (info.available and info.is_repo and info.upstream):
        return (), {}
    commits = tuple(git.commits_behind(ctx.paths))
    remote = git.remote_changes(ctx.paths, load_world(ctx.paths).catalog)
    return commits, remote


def _print_upstream(info, commits: Sequence[str], remote: Mapping[Key, RemoteChange]) -> None:
    if not (info.available and info.is_repo and info.upstream):
        return
    emit("")
    emit(f"Commits behind {info.upstream} ({len(commits)}):")
    for line in commits:
        emit(f"  {line}")
    emit("")
    emit(f"Skills with upstream changes ({len(remote)}):")
    for (scope, name), change in sorted(remote.items()):
        emit(f"  {glyph('remote')} {scope}/{name}  ({len(change.files)} file(s))")


def _updates_json(info, commits: Sequence[str], remote: Mapping[Key, RemoteChange]) -> dict:
    return {
        "git": {
            "message": info.message, "hint": info.hint, "branch": info.branch,
            "upstream": info.upstream, "ahead": info.ahead, "behind": info.behind,
            "last_fetch": info.last_fetch,
        },
        "commits": list(commits),
        "changed": [{"scope": scope, "name": name, "files": list(change.files)}
                    for (scope, name), change in sorted(remote.items())],
    }


def cmd_updates(ctx: Ctx) -> int:
    """Git status of the repo. ``--fetch`` runs git fetch first; ``--json`` prints
    {git: {message, hint, branch, upstream, ahead, behind, last_fetch}, commits: [...],
    changed: [{scope, name, files}]} instead of the text report (problems still go to stderr)."""
    fetching = bool(ctx.flag("fetch"))
    info = git.fetch(ctx.paths) if fetching else git.detect(ctx.paths)
    commits, remote = _upstream_data(ctx, info)
    if ctx.flag("json"):
        dump_json(_updates_json(info, commits, remote))
        if info.error:
            warn(f"git: {info.error}")
    else:
        _print_banner(info)
        _print_upstream(info, commits, remote)
    failed = fetching and info.is_repo and "fetch failed" in (info.error or "")
    return EXIT_FAIL if failed else EXIT_OK


def cmd_pull(ctx: Ctx) -> int:
    info = git.detect(ctx.paths)
    if not (info.available and info.is_repo):
        raise failure(f"{info.message}" + (f" - {info.hint}" if info.hint else ""))
    emit(f"Plan: git pull --ff-only  (in {ctx.paths.display(ctx.paths.repo_dir)}; {info.message})")
    if info.dirty:
        emit("note: the working tree has uncommitted changes; a fast-forward pull may refuse")
    if ctx.flag("dry_run"):
        emit("Dry run only; nothing was changed.")
        return EXIT_OK
    if not confirm(ctx.args):
        emit("Aborted.")
        return EXIT_FAIL
    ok, message = git.pull_ff(ctx.paths)
    emit(message)
    return EXIT_OK if ok else EXIT_FAIL
