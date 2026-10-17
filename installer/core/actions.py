"""Plan and apply filesystem operations for the installer.

Plans are tuples of `Operation`; `apply` executes them in order. Nothing here
ever deletes: whatever has to go away is moved under a backup root that the
caller picks (`Paths.backup_root`).

Conventions encoded in the plans:

* "copytree" and "symlink" do not create parent directories, so each one is
  preceded by a "mkdir" of its parent (deduplicated within a plan).
* "backup" (a real directory or file) and "unlink-to-backup" (a symlink) create
  the parent of their destination themselves and refuse an existing
  destination, so one backup can never overwrite or merge into another.
* Plans only touch what is known to be safe. Anything unexpected on disk is
  left alone; core.status reports it through `SkillStatus.issues`.
"""

from __future__ import annotations

import errno
import os
import shutil
from typing import Callable, Dict, Mapping, Optional, Tuple

from installer.core.paths import Paths
from installer.core.types import (
    CONSUMERS,
    IGNORED_DIR_NAMES,
    IGNORED_FILE_NAMES,
    ConsumerLink,
    InstalledSkill,
    LinkState,
    Operation,
    OpResult,
    SkillStatus,
    State,
)

DRY_RUN_MESSAGE = "(dry run)"
OK_MESSAGE = "ok"
# core.status puts this in a `duplicates` string when a consumer's real
# directory has the same content as the shared copy.
IDENTICAL_MARKER = "identical copy"

_LINK_KINDS = ("symlink", "broken-symlink")
_PUSHABLE_KINDS = ("dir", "symlink")
# states in which the entry under install_dir(scope) exists on disk
_ON_DISK = (State.INSTALLED, State.MODIFIED, State.FOREIGN)
_RELINK_STATES = (LinkState.MISSING, LinkState.BROKEN, LinkState.WRONG_TARGET)

InstalledIndex = Mapping[Tuple[str, str], InstalledSkill]


# ---------------------------------------------------------------- helpers


def _place(ops: Tuple[Operation, ...], op: Operation) -> Tuple[Operation, ...]:
    """Append `op`, preceded by a mkdir of its parent unless already planned."""
    parent = os.path.dirname(op.dst)
    planned = any(o.kind == "mkdir" and o.dst == parent for o in ops)
    mkdir = () if planned else (Operation(kind="mkdir", dst=parent),)
    return ops + mkdir + (op,)


def _move_op(src: str, dst: str, is_link: bool, note: str) -> Operation:
    kind = "unlink-to-backup" if is_link else "backup"
    return Operation(kind=kind, dst=dst, src=src, note=note)


def _symlink_op(link: ConsumerLink, paths: Paths, name: str) -> Operation:
    target = paths.expected_link_target(link.consumer, name)
    return Operation(kind="symlink", dst=link.path, src=target,
                     note=f"link {link.consumer} -> shared/{name}")


def _points_at_shared(link: ConsumerLink, name: str) -> bool:
    """OK links, plus broken links whose raw target ends with /skills/<name>."""
    if link.state == LinkState.OK:
        return True
    if link.state != LinkState.BROKEN or not link.target:
        return False
    target = link.target.replace(os.sep, "/").rstrip("/")
    return target.endswith("/skills/" + name)


def _real_dir_identical(link: ConsumerLink, status: SkillStatus,
                        installed_index: Optional[InstalledIndex]) -> bool:
    """See plan_relink for the policy."""
    if installed_index is not None:
        entry = installed_index.get((link.consumer, status.name))
        shared = status.installed
        return bool(entry is not None and shared is not None
                    and entry.digest is not None and entry.digest == shared.digest)
    return any(IDENTICAL_MARKER in text and link.consumer in text
               for text in status.duplicates)


def _relinkable(link: ConsumerLink, status: SkillStatus,
                installed_index: Optional[InstalledIndex]) -> bool:
    if link.state in _RELINK_STATES:
        return True
    if link.state == LinkState.REAL_DIR:
        return _real_dir_identical(link, status, installed_index)
    return False


def _overlapping(a: str, b: str) -> bool:
    """True when the real paths of `a` and `b` are equal or one contains the other."""
    real_a, real_b = os.path.realpath(a), os.path.realpath(b)
    return (real_a == real_b or real_a.startswith(real_b + os.sep)
            or real_b.startswith(real_a + os.sep))


# ------------------------------------------------------------------ plans


def plan_install(status: SkillStatus, paths: Paths,
                 consumers: Tuple[str, ...] = CONSUMERS) -> Tuple[Operation, ...]:
    """Copy a NOT_INSTALLED skill from the repo onto disk.

    Any other state, or a row without a repo source, yields an empty plan.
    For the shared scope a symlink is planned for each consumer in `consumers`
    whose `ConsumerLink.state` is MISSING; a consumer with anything else there
    (or without a link entry) is left alone and reported by core.status.
    """
    if status.state != State.NOT_INSTALLED or status.source is None:
        return ()
    scope, name = status.scope, status.name
    dst = os.path.join(paths.install_dir(scope), name)
    copy = Operation(kind="copytree", dst=dst, src=status.source.path,
                     note=f"install {scope}/{name}")
    ops = _place((), copy)
    if scope != "shared":
        return ops
    for link in status.links:
        if link.consumer in consumers and link.state == LinkState.MISSING:
            ops = _place(ops, _symlink_op(link, paths, name))
    return ops


def plan_update(status: SkillStatus, paths: Paths,
                backup_root: str) -> Tuple[Operation, ...]:
    """MODIFIED only: move the installed copy under the backup root, then copy
    the repo version into place."""
    if status.state != State.MODIFIED or status.source is None or status.installed is None:
        return ()
    scope, name = status.scope, status.name
    installed = status.installed
    backup = _move_op(installed.path, os.path.join(backup_root, scope, name),
                      installed.kind in _LINK_KINDS, f"keep the modified copy of {scope}/{name}")
    copy = Operation(kind="copytree", dst=os.path.join(paths.install_dir(scope), name),
                     src=status.source.path, note=f"update {scope}/{name} from the repo")
    return _place((backup,), copy)


def plan_retire(status: SkillStatus, paths: Paths, backup_root: str,
                consumers_only: bool = False) -> Tuple[Operation, ...]:
    """Move the installed entry under <backup_root>/<scope>/<name>.

    For the shared scope every consumer symlink that points at it (state OK,
    or BROKEN with a raw target ending in /skills/<name>) is moved to
    <backup_root>/<consumer>/<name> as well. `consumers_only=True` moves just
    those links and keeps the shared copy. IGNORED rows yield an empty plan.
    """
    if status.state == State.IGNORED:
        return ()
    scope, name = status.scope, status.name
    ops: Tuple[Operation, ...] = ()
    installed = status.installed
    if not consumers_only and installed is not None and installed.ignored_reason is None:
        ops += (_move_op(installed.path, os.path.join(backup_root, scope, name),
                         installed.kind in _LINK_KINDS, f"retire {scope}/{name}"),)
    if scope != "shared":
        return ops
    for link in status.links:
        if _points_at_shared(link, name):
            ops += (_move_op(link.path, os.path.join(backup_root, link.consumer, name),
                             True, f"unlink {link.consumer} from shared/{name}"),)
    return ops


def plan_relink(status: SkillStatus, paths: Paths, backup_root: str, *,
                installed_index: Optional[InstalledIndex] = None) -> Tuple[Operation, ...]:
    """Shared scope only: point every consumer entry at the shared copy.

    Handled link states: MISSING (symlink), BROKEN and WRONG_TARGET (move the
    link under <backup_root>/<consumer>/<name>, then symlink), and REAL_DIR
    when its content is identical to the shared copy (move the directory under
    the backup root, then symlink). A REAL_DIR with different content, a FILE,
    and an OK link are left untouched. Rows whose shared copy is not on disk
    yield an empty plan (install it first).

    Whether a REAL_DIR is identical is decided by content digest when
    `installed_index` (the mapping from core.skills.scan_installed, keyed by
    (consumer, name)) is given: the consumer entry's digest must equal
    `status.installed.digest`. Without an index the decision falls back to
    the "identical copy" marker core.status writes into `status.duplicates`
    for that consumer. Prefer passing the index.
    """
    if status.scope != "shared" or status.state not in _ON_DISK or status.installed is None:
        return ()
    name = status.name
    ops: Tuple[Operation, ...] = ()
    for link in status.links:
        if not _relinkable(link, status, installed_index):
            continue
        if link.state != LinkState.MISSING:
            is_link = link.state != LinkState.REAL_DIR
            what = "stale link" if is_link else "duplicate directory"
            ops += (_move_op(link.path, os.path.join(backup_root, link.consumer, name),
                             is_link, f"move {link.consumer}'s {what} aside"),)
        ops = _place(ops, _symlink_op(link, paths, name))
    return ops


def plan_push_to_repo(status: SkillStatus, paths: Paths,
                      backup_root: str) -> Tuple[Operation, ...]:
    """Copy the installed directory into <source_dir(scope)>/<name>.

    An existing repo copy is moved under <backup_root>/repo/<scope>/<name>
    first. Works for FOREIGN (adds a skill to the repo) and MODIFIED rows; a
    symlinked entry is copied through its resolved target. Rows without a
    readable directory (missing, broken link, plain file, ignored) yield ().

    An entry whose real path is the repo copy itself, or lies inside or
    around it, also yields (): that is a live-editing setup such as
    `~/.agents/skills/<name> -> <repo>/<scope dir>/<name>` (or an install
    dir that is itself a symlink into the repo), so there is nothing to push
    and the backup move would take the copytree source away with it.
    """
    installed = status.installed
    if installed is None or installed.ignored_reason is not None or status.state == State.IGNORED:
        return ()
    src = installed.resolved or installed.path
    if installed.kind not in _PUSHABLE_KINDS or not src:
        return ()
    scope, name = status.scope, status.name
    dst = os.path.join(paths.source_dir(scope), name)
    if _overlapping(src, dst):
        return ()
    ops: Tuple[Operation, ...] = ()
    if status.source is not None or os.path.lexists(dst):
        ops += (_move_op(dst, os.path.join(backup_root, "repo", scope, name),
                         os.path.islink(dst), f"keep the repo copy of {scope}/{name}"),)
    copy = Operation(kind="copytree", dst=dst, src=src,
                     note=f"push {scope}/{name} into the repo")
    return _place(ops, copy)


# ------------------------------------------------------------------ apply


def _do_mkdir(op: Operation) -> None:
    os.makedirs(op.dst, exist_ok=True)


def _do_copytree(op: Operation) -> None:
    ignore = shutil.ignore_patterns(*IGNORED_FILE_NAMES, *IGNORED_DIR_NAMES)
    shutil.copytree(op.src, op.dst, symlinks=True, ignore=ignore)


def _do_symlink(op: Operation) -> None:
    os.symlink(op.src, op.dst)


def _do_move(op: Operation) -> None:
    """Move src (a symlink is moved as the link itself) to a fresh dst."""
    if os.path.lexists(op.dst):
        raise FileExistsError(errno.EEXIST, "backup destination already exists", op.dst)
    os.makedirs(os.path.dirname(op.dst), exist_ok=True)
    shutil.move(op.src, op.dst)


_EXECUTORS: Dict[str, Callable[[Operation], None]] = {
    "mkdir": _do_mkdir,
    "copytree": _do_copytree,
    "symlink": _do_symlink,
    "backup": _do_move,
    "unlink-to-backup": _do_move,
}


def _run(op: Operation) -> OpResult:
    executor = _EXECUTORS.get(op.kind)
    if executor is None:
        return OpResult(op, False, f"unknown operation kind {op.kind!r}")
    if op.kind != "mkdir" and not op.src:
        return OpResult(op, False, f"{op.kind} needs a source")
    try:
        executor(op)
    except OSError as exc:
        return OpResult(op, False, str(exc))
    return OpResult(op, True, OK_MESSAGE)


def apply(ops: Tuple[Operation, ...], dry_run: bool = False) -> Tuple[OpResult, ...]:
    """Execute `ops` in order, stopping after the first failure.

    Every op is wrapped so an OSError becomes an `OpResult(ok=False)` instead
    of an exception. With `dry_run=True` nothing is touched and every op is
    reported ok with the message "(dry run)".
    """
    results: Tuple[OpResult, ...] = ()
    for op in ops:
        if dry_run:
            results += (OpResult(op, True, DRY_RUN_MESSAGE),)
            continue
        result = _run(op)
        results += (result,)
        if not result.ok:
            break
    return results


def describe(op: Operation, paths: Paths) -> str:
    """One line for confirm screens: "<kind>  <src> -> <dst>  (<note>)".

    Paths are ~-shortened through `paths.display`; a symlink's src is the
    link target text and is shown verbatim.
    """
    dst = paths.display(op.dst)
    if op.src is None:
        text = f"{op.kind}  {dst}"
    else:
        src = op.src if op.kind == "symlink" else paths.display(op.src)
        text = f"{op.kind}  {src} -> {dst}"
    return f"{text}  ({op.note})" if op.note else text
