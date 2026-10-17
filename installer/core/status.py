"""Merge the repo catalog, the on-disk install and git state into status rows.

Pure data in, pure data out: nothing here prints or touches the terminal. The
only filesystem access is ``os.path.realpath`` (to decide whether a consumer
symlink resolves to the shared copy) and reading files inside ``diff_text``.

The catalog and installed mappings are plain inputs (produced by
``core.skills``); this module never scans directories itself.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from installer.core.paths import Paths
from installer.core.types import (
    CONSUMERS,
    SCOPES,
    ConsumerLink,
    Counts,
    InstalledSkill,
    LinkState,
    RemoteChange,
    RepoIssue,
    SkillSource,
    SkillStatus,
    State,
)

Key = Tuple[str, str]
Catalog = Mapping[Key, SkillSource]
Installed = Mapping[Key, InstalledSkill]
Remote = Mapping[Key, RemoteChange]

SKILL_MD = "SKILL.md"
SHARED = "shared"

# Human strings other modules (actions, TUI) may look for verbatim.
IDENTICAL_COPY = "identical copy - can be converted to a symlink"
DIFFERENT_COPY = "different content from the shared copy"
CANDIDATE_FOR_SHARED = "same name installed for both tools - candidate for shared/"

_LINK_FINE = (LinkState.OK, LinkState.MISSING)


# ----------------------------------------------------------------- public API


def compute(catalog: Catalog, installed: Installed, paths: Paths,
            remote: Optional[Remote] = None,
            repo_issues: Tuple[RepoIssue, ...] = ()) -> Tuple[SkillStatus, ...]:
    """One SkillStatus per (scope, name), ordered by SCOPES then name."""
    world = _World(catalog=catalog, installed=installed, paths=paths,
                   remote=remote or {}, repo_issues=tuple(repo_issues))
    rows: List[SkillStatus] = list(_shared_rows(world))
    for consumer in CONSUMERS:
        rows.extend(_consumer_rows(world, consumer))
    return tuple(sorted(rows, key=_row_order))


def counts(statuses: Sequence[SkillStatus]) -> Tuple[Counts, ...]:
    """One Counts per scope, in SCOPES order."""
    return tuple(_count_scope(scope, [s for s in statuses if s.scope == scope]) for scope in SCOPES)


def problems(statuses: Sequence[SkillStatus]) -> Tuple[SkillStatus, ...]:
    """Rows with issues, duplicates or link problems."""
    return tuple(s for s in statuses if s.has_problem or s.link_problems)


def diff_text(source: SkillSource, installed: InstalledSkill) -> str:
    """Unified diff of SKILL.md (repo -> installed), then file-list differences.

    Returns an empty string when nothing differs.
    """
    name = source.name
    repo_md = _read_text(os.path.join(source.path, SKILL_MD))
    disk_md = _read_text(os.path.join(installed.path, SKILL_MD))
    lines = [
        _with_newline(line)
        for line in difflib.unified_diff(
            repo_md.splitlines(True), disk_md.splitlines(True),
            fromfile=f"repo/{name}/{SKILL_MD}", tofile=f"installed/{name}/{SKILL_MD}",
        )
    ]
    repo_files, disk_files = frozenset(source.files), frozenset(installed.files)
    lines.extend(f"only in repo: {p}\n" for p in sorted(repo_files - disk_files))
    lines.extend(f"only installed: {p}\n" for p in sorted(disk_files - repo_files))
    for rel in sorted(repo_files & disk_files):
        if _read_bytes(os.path.join(source.path, rel)) != _read_bytes(os.path.join(installed.path, rel)):
            lines.append(f"changed: {rel}\n")
    return "".join(lines)


# ---------------------------------------------------------------- world view


@dataclass(frozen=True)
class _World:
    """Read-only view over the inputs of compute(), with the lookups rows need."""

    catalog: Catalog
    installed: Installed
    paths: Paths
    remote: Remote
    repo_issues: Tuple[RepoIssue, ...]

    def source(self, scope: str, name: str) -> Optional[SkillSource]:
        return self.catalog.get((scope, name))

    def entry(self, scope: str, name: str) -> Optional[InstalledSkill]:
        """The disk entry, ignored ones included."""
        return self.installed.get((scope, name))

    def active(self, scope: str, name: str) -> Optional[InstalledSkill]:
        """The disk entry unless it is tool-managed (ignored)."""
        entry = self.entry(scope, name)
        return None if entry is None or entry.ignored_reason else entry

    def catalog_names(self, scope: str) -> frozenset:
        return frozenset(name for (s, name) in self.catalog if s == scope)

    def shared_names(self) -> Tuple[str, ...]:
        """Names that get a shared row: in the shared catalog or under ~/.agents/skills."""
        names = set(self.catalog_names(SHARED))
        names.update(name for (s, name), e in self.installed.items()
                     if s == SHARED and not e.ignored_reason)
        return tuple(sorted(names))

    def entries_in(self, scope: str) -> Tuple[InstalledSkill, ...]:
        items = sorted(self.installed.items(), key=lambda kv: kv[0])
        return tuple(e for (s, _), e in items if s == scope)


# --------------------------------------------------------------- shared rows


def _shared_rows(world: _World) -> Iterable[SkillStatus]:
    for name in world.shared_names():
        yield _shared_row(world, name)
    for entry in world.entries_in(SHARED):
        if entry.ignored_reason:
            yield _ignored_row(world, entry)


def _shared_row(world: _World, name: str) -> SkillStatus:
    source = world.source(SHARED, name)
    inst = world.active(SHARED, name)
    links = tuple(_consumer_link(world, consumer, name) for consumer in CONSUMERS)
    repo_dups, repo_issues = _repo_notes(world, SHARED, name)
    return SkillStatus(
        scope=SHARED,
        name=name,
        state=_state(source, inst),
        source=source,
        installed=inst,
        links=links,
        duplicates=_real_dir_notes(world, name, source, inst, links) + repo_dups,
        issues=_link_issues(links) + _entry_issues(inst, name) + repo_issues,
        remote=world.remote.get((SHARED, name)),
    )


def _consumer_link(world: _World, consumer: str, name: str) -> ConsumerLink:
    entry = world.entry(consumer, name)
    return ConsumerLink(
        consumer=consumer,
        path=os.path.join(world.paths.consumer_dir(consumer), name),
        state=_link_state(world, entry, name),
        target=entry.link_target if entry is not None else None,
        expected=world.paths.expected_link_target(consumer, name),
    )


def _link_state(world: _World, entry: Optional[InstalledSkill], name: str) -> LinkState:
    if entry is None:
        return LinkState.MISSING
    if entry.kind == "dir":
        return LinkState.REAL_DIR
    if entry.kind == "file":
        return LinkState.FILE
    if entry.kind == "broken-symlink":
        return LinkState.BROKEN
    shared_copy = os.path.join(world.paths.install_dir(SHARED), name)
    if os.path.realpath(entry.path) == os.path.realpath(shared_copy):
        return LinkState.OK
    return LinkState.WRONG_TARGET


def _real_dir_notes(world: _World, name: str, source: Optional[SkillSource],
                    shared_inst: Optional[InstalledSkill],
                    links: Tuple[ConsumerLink, ...]) -> Tuple[str, ...]:
    """One duplicate note per consumer whose entry is a real directory."""
    notes = []
    for link in links:
        if link.state is not LinkState.REAL_DIR:
            continue
        entry = world.entry(link.consumer, name)
        verdict = _copy_verdict(entry, shared_inst, source)
        notes.append(f"{link.consumer}: real directory at {world.paths.display(link.path)} - {verdict}")
    return tuple(notes)


def _copy_verdict(entry: Optional[InstalledSkill], shared_inst: Optional[InstalledSkill],
                  source: Optional[SkillSource]) -> str:
    digest = entry.digest if entry is not None else None
    if shared_inst is not None and shared_inst.digest is not None:
        return IDENTICAL_COPY if digest == shared_inst.digest else DIFFERENT_COPY
    if source is not None:
        same = digest is not None and digest == source.digest
        verdict = "identical to the repo copy" if same else "differs from the repo copy"
        return f"{verdict} (shared copy not installed)"
    return "no shared copy to compare with"


def _link_issues(links: Tuple[ConsumerLink, ...]) -> Tuple[str, ...]:
    return tuple(f"{link.consumer}: {_describe_link(link)}" for link in links
                 if link.state not in _LINK_FINE)


def _describe_link(link: ConsumerLink) -> str:
    if link.state is LinkState.REAL_DIR:
        return f"real directory shadows the shared skill (expected symlink -> {link.expected})"
    if link.state is LinkState.WRONG_TARGET:
        return f"symlink points to {link.target} (expected {link.expected})"
    if link.state is LinkState.BROKEN:
        return f"broken symlink -> {link.target} (expected {link.expected})"
    return f"plain file where a symlink is expected (-> {link.expected})"


# ------------------------------------------------------------- consumer rows


def _consumer_rows(world: _World, consumer: str) -> List[SkillStatus]:
    """Platform rows for the catalog, then IGNORED / FOREIGN rows for stray entries.

    Entries whose name belongs to a shared skill are described by that shared
    row's links instead and get no row here.
    """
    catalog_names = world.catalog_names(consumer)
    shared_names = frozenset(world.shared_names())
    rows = [_platform_row(world, consumer, name) for name in sorted(catalog_names)]
    for entry in world.entries_in(consumer):
        if entry.name in catalog_names:
            continue
        if entry.ignored_reason:
            rows.append(_ignored_row(world, entry))
        elif entry.name not in shared_names:
            rows.append(_foreign_row(world, entry))
    return rows


def _platform_row(world: _World, consumer: str, name: str) -> SkillStatus:
    source = world.source(consumer, name)
    entry = world.entry(consumer, name)
    if entry is not None and entry.ignored_reason:
        return _ignored_row(world, entry, source)
    repo_dups, repo_issues = _repo_notes(world, consumer, name)
    return SkillStatus(
        scope=consumer,
        name=name,
        state=_state(source, entry),
        source=source,
        installed=entry,
        duplicates=_candidate_note(world, name) + repo_dups,
        issues=_entry_issues(entry, name) + repo_issues,
        remote=world.remote.get((consumer, name)),
    )


def _foreign_row(world: _World, entry: InstalledSkill) -> SkillStatus:
    return SkillStatus(
        scope=entry.scope,
        name=entry.name,
        state=State.FOREIGN,
        source=None,
        installed=entry,
        duplicates=_candidate_note(world, entry.name),
        issues=_entry_issues(entry, entry.name),
        remote=world.remote.get(entry.key),
    )


def _ignored_row(world: _World, entry: InstalledSkill,
                 source: Optional[SkillSource] = None) -> SkillStatus:
    return SkillStatus(
        scope=entry.scope,
        name=entry.name,
        state=State.IGNORED,
        source=source,
        installed=entry,
        remote=world.remote.get(entry.key),
    )


def _candidate_note(world: _World, name: str) -> Tuple[str, ...]:
    """Real directories in BOTH consumers, nothing shared (repo or disk), and
    the name is either unknown to the repo or identical in both consumers.

    A platform variant pair with differing content is sanctioned by the repo
    rules, so it gets no note; the note appears once the two installed copies
    converge (that is when the pair should collapse into shared/).
    """
    if (SHARED, name) in world.catalog or world.active(SHARED, name) is not None:
        return ()
    entries = tuple(world.active(consumer, name) for consumer in CONSUMERS)
    if any(entry is None or entry.kind != "dir" for entry in entries):
        return ()
    in_repo = any((consumer, name) in world.catalog for consumer in CONSUMERS)
    if in_repo and not _same_content(entries):
        return ()
    return (CANDIDATE_FOR_SHARED,)


def _same_content(entries: Sequence[Optional[InstalledSkill]]) -> bool:
    """True when every entry has a digest and all digests are equal."""
    digests = {entry.digest for entry in entries if entry is not None}
    return len(digests) == 1 and None not in digests


# ------------------------------------------------------------ shared helpers


def _state(source: Optional[SkillSource], entry: Optional[InstalledSkill]) -> State:
    if entry is not None and entry.ignored_reason:
        return State.IGNORED
    if source is None:
        return State.FOREIGN
    if entry is None:
        return State.NOT_INSTALLED
    if entry.digest is not None and entry.digest == source.digest:
        return State.INSTALLED
    return State.MODIFIED


def _entry_issues(entry: Optional[InstalledSkill], name: str) -> Tuple[str, ...]:
    """Problems with the installed entry itself: kind, then frontmatter."""
    if entry is None:
        return ()
    if entry.kind == "broken-symlink":
        return (f"broken symlink -> {entry.link_target}",)
    if entry.kind == "file":
        return ("plain file, not a skill directory",)
    issues: List[str] = []
    if entry.kind == "symlink":
        issues.append(f"symlink -> {entry.link_target} (expected a real directory)")
    issues.extend(_frontmatter_issues(entry, name))
    return tuple(issues)


def _frontmatter_issues(entry: InstalledSkill, name: str) -> Tuple[str, ...]:
    meta = entry.meta
    if meta is None:
        return (f"no readable {SKILL_MD}",)
    issues: List[str] = []
    if not meta.valid:
        issues.append(f"{SKILL_MD} frontmatter is missing name or description")
    if meta.name and meta.name != name:
        issues.append(f"frontmatter name {meta.name!r} does not match directory name {name!r}")
    return tuple(issues)


def _repo_notes(world: _World, scope: str, name: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """(duplicates, issues) contributed by RepoIssue records.

    A duplicate-scope issue is noted on every catalog row carrying that name;
    every issue is reported as an issue on the row of its own key only.
    """
    dups: List[str] = []
    issues: List[str] = []
    in_catalog = (scope, name) in world.catalog
    for issue in world.repo_issues:
        if issue.name != name:
            continue
        text = f"repo: {issue.message}"
        if issue.kind == "duplicate-scope" and in_catalog and text not in dups:
            dups.append(text)
        if issue.scope == scope:
            issues.append(text)
    return tuple(dups), tuple(issues)


def _row_order(row: SkillStatus) -> Tuple[int, str]:
    rank = SCOPES.index(row.scope) if row.scope in SCOPES else len(SCOPES)
    return (rank, row.name)


def _count_scope(scope: str, rows: Sequence[SkillStatus]) -> Counts:
    return Counts(
        scope=scope,
        available=sum(1 for r in rows if r.source is not None),
        installed=sum(1 for r in rows if r.state is State.INSTALLED),
        modified=sum(1 for r in rows if r.state is State.MODIFIED),
        missing=sum(1 for r in rows if r.state is State.NOT_INSTALLED),
        foreign=sum(1 for r in rows if r.state is State.FOREIGN),
        problems=sum(1 for r in rows if r.has_problem or r.link_problems),
        remote_updates=sum(1 for r in rows if r.remote is not None),
    )


def _read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _read_text(path: str) -> str:
    data = _read_bytes(path)
    return "" if data is None else data.decode("utf-8", errors="replace")


def _with_newline(line: str) -> str:
    return line if line.endswith("\n") else line + "\n"
