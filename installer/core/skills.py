"""Scanning: the repo catalog, what is installed on disk, digests and file lists.

Everything here is read-only. Paths inside a skill are reported POSIX-style
(``"/"`` separators) relative to the skill directory, sorted, with the names in
``IGNORED_FILE_NAMES`` / ``IGNORED_DIR_NAMES`` left out. A symlinked
subdirectory is listed as a single entry and never descended; the root itself
is followed when it is a symlink.
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional, Tuple

from installer.core.frontmatter import SKILL_FILE, read_meta
from installer.core.paths import Paths
from installer.core.types import (
    CONSUMERS,
    IGNORED_DIR_NAMES,
    IGNORED_DIR_REASONS,
    IGNORED_FILE_NAMES,
    SCOPES,
    InstalledSkill,
    RepoIssue,
    SkillMeta,
    SkillSource,
)

_READ_CHUNK = 1 << 16
_HIDDEN_REASON = "hidden entry (dot-prefixed)"

Catalog = Dict[Tuple[str, str], SkillSource]
Installed = Dict[Tuple[str, str], InstalledSkill]


# --------------------------------------------------------------- file lists


def list_files(root: str) -> Tuple[str, ...]:
    """Sorted relative POSIX paths of the regular files (and symlinks) under root.

    Raises ``OSError`` when root is missing or unreadable; callers that must
    not fail (``scan_installed``) catch it.
    """
    found: List[str] = []
    _walk(root, "", found)
    return tuple(sorted(found))


def _walk(dir_path: str, prefix: str, found: List[str]) -> None:
    with os.scandir(dir_path) as iterator:
        entries = list(iterator)
    for entry in entries:
        rel = prefix + entry.name
        if entry.is_symlink():
            if entry.name not in IGNORED_FILE_NAMES and entry.name not in IGNORED_DIR_NAMES:
                found.append(rel)
        elif entry.is_dir():
            if entry.name not in IGNORED_DIR_NAMES:
                _walk(entry.path, rel + "/", found)
        elif entry.is_file():
            if entry.name not in IGNORED_FILE_NAMES:
                found.append(rel)


def _fs_path(root: str, rel: str) -> str:
    return os.path.join(root, *rel.split("/"))


# ------------------------------------------------------------------ digests


def digest(root: str) -> str:
    """sha256 over ``path + "\\0" + sha256(content).hexdigest() + "\\n"`` per file."""
    return _digest(root, list_files(root))


def size_of(root: str) -> int:
    """Total bytes of the files ``list_files`` reports (symlinks count their link)."""
    return _size(root, list_files(root))


def _digest(root: str, files: Tuple[str, ...]) -> str:
    total = hashlib.sha256()
    for rel in files:
        total.update(rel.encode("utf-8", "surrogateescape"))
        total.update(b"\0")
        total.update(_content_hash(_fs_path(root, rel)).encode("ascii"))
        total.update(b"\n")
    return total.hexdigest()


def _content_hash(path: str) -> str:
    """sha256 hex of a file's bytes; for a symlink, of its target string."""
    hasher = hashlib.sha256()
    if os.path.islink(path):
        hasher.update(os.readlink(path).encode("utf-8", "surrogateescape"))
        return hasher.hexdigest()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _size(root: str, files: Tuple[str, ...]) -> int:
    return sum(os.lstat(_fs_path(root, rel)).st_size for rel in files)


# ------------------------------------------------------------------ catalog


def scan_catalog(paths: Paths) -> Tuple[Catalog, Tuple[RepoIssue, ...]]:
    """One ``SkillSource`` per ``<source_dir(scope)>/<name>/`` holding a SKILL.md.

    Issues: ``missing-skill-md``, ``missing-frontmatter``, ``name-mismatch`` and
    ``duplicate-scope`` (a platform scope repeating a shared name). Dot-prefixed
    and tool-managed directory names are skipped silently.
    """
    catalog: Catalog = {}
    issues: List[RepoIssue] = []
    for scope in SCOPES:
        _scan_source_dir(scope, paths.source_dir(scope), catalog, issues)
    issues.extend(_duplicate_issues(catalog))
    return catalog, tuple(issues)


def _scan_source_dir(scope: str, source_dir: str, catalog: Catalog,
                     issues: List[RepoIssue]) -> None:
    if not os.path.isdir(source_dir):
        return
    for name in sorted(os.listdir(source_dir)):
        skill_dir = os.path.join(source_dir, name)
        if _ignored_reason(name) is not None or not os.path.isdir(skill_dir):
            continue
        if not os.path.isfile(os.path.join(skill_dir, SKILL_FILE)):
            issues.append(RepoIssue(scope, name, "missing-skill-md",
                                    f"{scope}/{name}: directory has no {SKILL_FILE}"))
            continue
        source = _read_source(scope, name, skill_dir)
        catalog[source.key] = source
        issues.extend(_meta_issues(source))


def _read_source(scope: str, name: str, skill_dir: str) -> SkillSource:
    files = list_files(skill_dir)
    meta = read_meta(skill_dir) or SkillMeta(None, None)
    return SkillSource(
        scope=scope,
        name=name,
        path=skill_dir,
        meta=meta,
        digest=_digest(skill_dir, files),
        files=files,
        size_bytes=_size(skill_dir, files),
    )


def _meta_issues(source: SkillSource) -> List[RepoIssue]:
    scope, name, meta = source.scope, source.name, source.meta
    out: List[RepoIssue] = []
    if not meta.valid:
        missing = [key for key in ("name", "description") if not getattr(meta, key)]
        out.append(RepoIssue(scope, name, "missing-frontmatter",
                             f"{scope}/{name}: {SKILL_FILE} frontmatter lacks "
                             f"{' and '.join(missing)}"))
    if meta.name and meta.name != name:
        out.append(RepoIssue(scope, name, "name-mismatch",
                             f"{scope}/{name}: frontmatter name {meta.name!r} "
                             f"does not match the directory name"))
    return out


def _duplicate_issues(catalog: Catalog) -> List[RepoIssue]:
    out: List[RepoIssue] = []
    for scope, name in catalog:
        if scope in CONSUMERS and ("shared", name) in catalog:
            out.append(RepoIssue(scope, name, "duplicate-scope",
                                 f"{scope}/{name} duplicates shared/{name}; keep one "
                                 f"copy unless the bodies genuinely differ per tool"))
    return out


# ------------------------------------------------------------------- names


def is_valid_name(name: str) -> bool:
    """True for a single, visible path component usable as a skill name."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        return False
    if name.startswith(".") or "\0" in name:
        return False
    separators = {"/", os.sep}
    if os.altsep:
        separators.add(os.altsep)
    return not any(sep in name for sep in separators)


# --------------------------------------------------------------- installed


def scan_installed(paths: Paths) -> Installed:
    """Every entry of each scope's install dir. A missing dir yields no entries."""
    installed: Installed = {}
    for scope in SCOPES:
        install_dir = paths.install_dir(scope)
        if not os.path.isdir(install_dir):
            continue
        for name in sorted(os.listdir(install_dir)):
            entry = _inspect_entry(scope, name, os.path.join(install_dir, name))
            installed[entry.key] = entry
    return installed


def _ignored_reason(name: str) -> Optional[str]:
    if name in IGNORED_DIR_REASONS:
        return IGNORED_DIR_REASONS[name]
    if name.startswith("."):
        return _HIDDEN_REASON
    return None


def _classify(path: str) -> Tuple[str, Optional[str], Optional[str]]:
    """(kind, link_target, resolved) for one install-dir entry."""
    if os.path.islink(path):
        target = os.readlink(path)
        if os.path.exists(path):
            return "symlink", target, os.path.realpath(path)
        return "broken-symlink", target, None
    if os.path.isdir(path):
        return "dir", None, os.path.realpath(path)
    return "file", None, os.path.realpath(path)


def _inspect_entry(scope: str, name: str, path: str) -> InstalledSkill:
    kind, link_target, resolved = _classify(path)
    reason = _ignored_reason(name)
    base = dict(scope=scope, name=name, path=path, kind=kind,
                link_target=link_target, resolved=resolved)
    if reason is not None:
        return InstalledSkill(meta=None, digest=None, files=(), size_bytes=0,
                              ignored_reason=reason, **base)
    if kind == "file":
        return InstalledSkill(meta=None, digest=None, files=(),
                              size_bytes=_file_size(path), **base)
    if not os.path.isdir(path):  # broken link, or a symlink to a plain file
        return InstalledSkill(meta=None, digest=None, files=(), size_bytes=0, **base)
    return _with_content(base, path)


def _with_content(base: Dict[str, Optional[str]], path: str) -> InstalledSkill:
    try:
        files = list_files(path)
        content_digest: Optional[str] = _digest(path, files)
        size = _size(path, files)
    except OSError:
        files, content_digest, size = (), None, 0
    return InstalledSkill(meta=read_meta(path), digest=content_digest, files=files,
                          size_bytes=size, **base)


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
