"""Directory trees for the viewer screen and the `tree` command.

`build_tree` walks a directory once and returns an immutable `TreeNode`.
`flatten` and `render` turn that node into rows / lines without touching the
filesystem again. Nothing here prints, reads stdin or deletes anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import FrozenSet, Iterator, Tuple

from installer.core.types import IGNORED_DIR_NAMES, IGNORED_FILE_NAMES

# (continuation stem, branch connector, last-branch connector, blank stem)
Guides = Tuple[str, str, str, str]
UNICODE_GUIDES: Guides = ("│   ", "├── ", "└── ", "    ")
ASCII_GUIDES: Guides = ("|   ", "|-- ", "`-- ", "    ")

DEFAULT_MAX_DEPTH = 8
DIR_SUFFIX = "/"


@dataclass(frozen=True)
class TreeNode:
    """One directory entry. Directories carry their sorted children.

    A symlinked directory is reported with `is_dir=True`, `is_link=True` and
    no children: the walk never descends through a link.
    """

    name: str
    path: str
    is_dir: bool
    size: int
    children: Tuple["TreeNode", ...] = ()
    is_link: bool = False


@dataclass(frozen=True)
class Row:
    """A visible line of a (partially expanded) tree.

    `prefix` is the complete guide string drawn before the name, e.g.
    "│   └── ". The root row has depth 0 and an empty prefix.
    """

    depth: int
    node: TreeNode
    prefix: str


# ------------------------------------------------------------------ building


def is_ignored_name(name: str) -> bool:
    """True for the names that never count as skill content.

    This is exactly the rule `skills.list_files` applies (`IGNORED_FILE_NAMES`
    and `IGNORED_DIR_NAMES`), so the tree shows every entry that is part of a
    skill's digest. Dot-prefixed entries inside a skill (`.gitignore`,
    `.env.example`, `.claude/`) are content and stay visible; the dot-prefix
    rule for tool-managed directories applies to the entries of a *skills*
    directory and lives in `skills.scan_installed`, not here.
    """
    return name in IGNORED_FILE_NAMES or name in IGNORED_DIR_NAMES


def _file_size(path: str) -> int:
    try:
        return os.stat(path).st_size
    except OSError:  # broken symlink, permission problem: size unknown
        return 0


def _entries(path: str) -> Tuple[str, ...]:
    try:
        names = os.listdir(path)
    except OSError:  # unreadable directory: show it as empty
        return ()
    return tuple(name for name in names if not is_ignored_name(name))


def _sort_key(node: TreeNode) -> Tuple[bool, str, str]:
    return (not node.is_dir, node.name.lower(), node.name)


def _build(path: str, name: str, depth: int, max_depth: int, follow_link: bool) -> TreeNode:
    is_link = os.path.islink(path)
    if not os.path.isdir(path):
        return TreeNode(name=name, path=path, is_dir=False, size=_file_size(path), is_link=is_link)
    if (is_link and not follow_link) or depth >= max_depth:
        return TreeNode(name=name, path=path, is_dir=True, size=0, is_link=is_link)
    children = tuple(
        sorted(
            (_build(os.path.join(path, entry), entry, depth + 1, max_depth, False)
             for entry in _entries(path)),
            key=_sort_key,
        )
    )
    size = sum(child.size for child in children)
    return TreeNode(name=name, path=path, is_dir=True, size=size, children=children,
                    is_link=is_link)


def build_tree(root: str, max_depth: int = DEFAULT_MAX_DEPTH) -> TreeNode:
    """Walk `root` (depth 0) down to `max_depth` levels of descendants.

    Directories sort before files, each group case-insensitively by name.
    Ignored names (`IGNORED_FILE_NAMES`, `IGNORED_DIR_NAMES`) are skipped at
    every level and nothing else is, so the tree lists exactly the entries
    `skills.list_files` reports. The root itself is followed when it is a
    symlink; symlinked subdirectories are listed but not entered. A missing
    or unreadable root yields a childless node rather than an exception.
    """
    name = os.path.basename(root.rstrip(os.sep)) or root
    return _build(root, name, 0, max(0, max_depth), True)


# ---------------------------------------------------------------- flattening


def _rows(node: TreeNode, expanded: FrozenSet[str], guides: Guides, stem: str, depth: int,
          show_all: bool) -> Iterator[Row]:
    if not node.children or not (show_all or node.path in expanded):
        return
    stem_more, branch, last_branch, stem_blank = guides
    last = len(node.children) - 1
    for index, child in enumerate(node.children):
        is_last = index == last
        yield Row(depth=depth, node=child, prefix=stem + (last_branch if is_last else branch))
        yield from _rows(child, expanded, guides, stem + (stem_blank if is_last else stem_more),
                         depth + 1, show_all)


def flatten(node: TreeNode, expanded: FrozenSet[str], ascii_only: bool = False) -> Tuple[Row, ...]:
    """Rows for the root and every visible descendant.

    A directory's children are visible only when its `path` is in `expanded`
    (the root included). `ascii_only` swaps the box-drawing guides for the
    ASCII set used by `render`.
    """
    guides = ASCII_GUIDES if ascii_only else UNICODE_GUIDES
    root = Row(depth=0, node=node, prefix="")
    return (root,) + tuple(_rows(node, expanded, guides, "", 1, False))


def label(node: TreeNode) -> str:
    """Display name: directories get a trailing "/"."""
    return node.name + DIR_SUFFIX if node.is_dir else node.name


def render(node: TreeNode, ascii_only: bool = False) -> Tuple[str, ...]:
    """Classic `tree`-style lines for the fully expanded tree."""
    guides = ASCII_GUIDES if ascii_only else UNICODE_GUIDES
    rows = _rows(node, frozenset(), guides, "", 1, True)
    body = tuple(row.prefix + label(row.node) for row in rows)
    return (label(node),) + body


def count_files(node: TreeNode) -> int:
    """Number of non-directory entries reachable from `node` (itself included)."""
    if not node.is_dir:
        return 1
    return sum(count_files(child) for child in node.children)
