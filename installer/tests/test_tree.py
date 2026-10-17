"""Tests for installer.core.tree: build_tree ordering/skipping, flatten, render."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import List, Set

from installer.core.skills import list_files
from installer.core.tree import (
    ASCII_GUIDES,
    UNICODE_GUIDES,
    Row,
    TreeNode,
    build_tree,
    count_files,
    flatten,
    is_ignored_name,
    label,
    render,
)
from installer.core.types import IGNORED_DIR_NAMES, IGNORED_FILE_NAMES
from installer.tests.fixtures import write

BRANCH, LAST = UNICODE_GUIDES[1], UNICODE_GUIDES[2]
STEM = UNICODE_GUIDES[0]

# Children of the fixture root in display order: directories first, sorted
# case-insensitively (so ".hidden" precedes "Alpha"), then files. The symlinked
# directory "linked" counts as a directory.
TOP_LEVEL = [".hidden", "Alpha", "beta", "linked", "Bravo.txt", "SKILL.md", "zeta.txt"]

EXPECTED_UNICODE = (
    "root/",
    "├── .hidden/",
    "│   └── x.txt",
    "├── Alpha/",
    "│   └── deep/",
    "│       └── deeper/",
    "│           └── leaf.txt",
    "├── beta/",
    "│   └── b.md",
    "├── linked/",
    "├── Bravo.txt",
    "├── SKILL.md",
    "└── zeta.txt",
)

EXPECTED_ASCII = (
    "root/",
    "|-- .hidden/",
    "|   `-- x.txt",
    "|-- Alpha/",
    "|   `-- deep/",
    "|       `-- deeper/",
    "|           `-- leaf.txt",
    "|-- beta/",
    "|   `-- b.md",
    "|-- linked/",
    "|-- Bravo.txt",
    "|-- SKILL.md",
    "`-- zeta.txt",
)

# Regular files the tree must show. The dot-prefixed directory is ordinary
# skill content (think `.claude/` or `.github/`) and must stay visible, exactly
# as `skills.list_files` reports it.
FILES = {
    "SKILL.md": "# skill\n",
    "zeta.txt": "zz\n",
    "Bravo.txt": "bravo\n",
    os.path.join("Alpha", "deep", "deeper", "leaf.txt"): "leaf\n",
    os.path.join("beta", "b.md"): "b\n",
    os.path.join(".hidden", "x.txt"): "hidden\n",
}

# Entries that never count as skill content (IGNORED_FILE_NAMES / IGNORED_DIR_NAMES).
IGNORED = {
    ".DS_Store": "junk",
    os.path.join("__pycache__", "x.pyc"): "cache\n",
}


def make_tree(tmp: str) -> str:
    """Nested dirs, a symlinked dir, a dot-dir, plus a .DS_Store and __pycache__."""
    root = os.path.join(tmp, "root")
    for rel, text in FILES.items():
        write(os.path.join(root, rel), text)
    for rel, text in IGNORED.items():
        write(os.path.join(root, rel), text)
    os.symlink("Alpha", os.path.join(root, "linked"))
    return root


def names(node: TreeNode) -> List[str]:
    return [child.name for child in node.children]


def child(node: TreeNode, name: str) -> TreeNode:
    for item in node.children:
        if item.name == name:
            return item
    raise AssertionError(f"no child named {name!r} under {node.path}")


def leaf_paths(node: TreeNode) -> Set[str]:
    """Relative POSIX paths of every entry the tree lists as a file or an
    un-entered symlink: the same shape `skills.list_files` returns."""
    found: Set[str] = set()

    def walk(entry: TreeNode, rel: str) -> None:
        if not entry.is_dir or entry.is_link:
            found.add(rel)
            return
        for grandchild in entry.children:
            walk(grandchild, rel + "/" + grandchild.name)

    for item in node.children:
        walk(item, item.name)
    return found


def posix(rel: str) -> str:
    return rel.replace(os.sep, "/")


@unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported on this platform")
class TreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_tree(self.tmp.name)
        self.tree = build_tree(self.root)

    def test_build_tree_ordering_ignored_names_symlinks_depth_and_leaf_roots(self):
        tree, root = self.tree, self.root
        # directories first, then files, case-insensitively
        self.assertEqual(names(tree), TOP_LEVEL)
        self.assertEqual(tree.name, "root")
        self.assertTrue(tree.is_dir)
        self.assertFalse(tree.is_link)
        # ignored names are skipped but dot-prefixed content stays, and the tree lists
        # exactly what skills.list_files reports
        self.assertNotIn(".DS_Store", names(tree))
        self.assertNotIn("__pycache__", names(tree))
        hidden = child(tree, ".hidden")
        self.assertTrue(hidden.is_dir)
        self.assertEqual(names(hidden), ["x.txt"])
        listed = list_files(root)
        self.assertEqual(leaf_paths(tree), set(listed))
        self.assertIn(".hidden/x.txt", listed)
        self.assertEqual(count_files(tree), len(FILES))
        self.assertEqual(child(tree, "SKILL.md").size, len("# skill\n"))  # sizes roll up from the files
        self.assertEqual(child(tree, "Alpha").size, len("leaf\n"))
        self.assertEqual(hidden.size, len("hidden\n"))
        self.assertEqual(tree.size, sum(len(text) for text in FILES.values()))

        # a symlinked directory is marked and not entered; a root symlink is followed
        linked = child(tree, "linked")
        self.assertTrue(linked.is_link)
        self.assertTrue(linked.is_dir)
        self.assertEqual(linked.children, ())
        self.assertEqual(linked.size, 0)
        alpha = child(tree, "Alpha")
        self.assertFalse(alpha.is_link)
        self.assertEqual(names(alpha), ["deep"])
        followed = build_tree(os.path.join(root, "linked"))
        self.assertTrue(followed.is_link)
        self.assertEqual(names(followed), ["deep"])

        # max_depth, a file as root, a missing root, frozen nodes
        self.assertEqual(build_tree(root, max_depth=0).children, ())
        self.assertEqual(child(build_tree(root, max_depth=1), "Alpha").children, ())
        depth2 = build_tree(root, max_depth=2)
        self.assertEqual(names(child(depth2, "Alpha")), ["deep"])
        self.assertEqual(child(child(depth2, "Alpha"), "deep").children, ())
        leaf = build_tree(os.path.join(root, "SKILL.md"))
        self.assertFalse(leaf.is_dir)
        self.assertEqual(leaf.size, len("# skill\n"))
        self.assertEqual(leaf.children, ())
        missing = build_tree(os.path.join(self.tmp.name, "missing"))
        self.assertFalse(missing.is_dir)
        self.assertEqual(missing.size, 0)
        with self.assertRaises(AttributeError):
            leaf.name = "y"  # type: ignore[misc]

        # dot-prefixed files and dirs inside a skill are content; junk never is
        shown = (".gitignore", ".env.example", os.path.join(".claude", "settings.json"),
                 os.path.join(".github", "workflows", "ci.yml"), os.path.join("docs", "guide.md"))
        junk = (".DS_Store", ".gitkeep", "Thumbs.db", os.path.join(".git", "HEAD"),
                os.path.join("node_modules", "pkg", "index.js"), os.path.join("docs", ".DS_Store"),
                os.path.join("docs", "__pycache__", "m.pyc"))
        skill = os.path.join(self.tmp.name, "skill")
        for rel in shown + junk:
            write(os.path.join(skill, rel), "x\n")
        skill_tree = build_tree(skill)
        self.assertEqual(leaf_paths(skill_tree), {posix(rel) for rel in shown})
        self.assertEqual(leaf_paths(skill_tree), set(list_files(skill)))
        self.assertEqual(names(skill_tree), [".claude", ".github", "docs", ".env.example", ".gitignore"])
        self.assertEqual(names(child(skill_tree, "docs")), ["guide.md"])
        self.assertEqual(count_files(skill_tree), len(shown))
        for name in IGNORED_FILE_NAMES + IGNORED_DIR_NAMES:  # is_ignored_name matches the skills walker
            self.assertTrue(is_ignored_name(name), name)
        for name in (".gitignore", ".env.example", ".claude", ".github", ".hidden", "SKILL.md"):
            self.assertFalse(is_ignored_name(name), name)

    def test_flatten_and_render(self):
        tree = self.tree
        self.assertEqual(flatten(tree, frozenset()), (Row(depth=0, node=tree, prefix=""),))
        rows = flatten(tree, frozenset({tree.path}))
        self.assertEqual([r.node.name for r in rows[1:]], TOP_LEVEL)
        self.assertEqual([r.depth for r in rows[1:]], [1] * len(TOP_LEVEL))
        self.assertEqual([r.prefix for r in rows[1:]], [BRANCH] * (len(TOP_LEVEL) - 1) + [LAST])
        rows = flatten(tree, frozenset({tree.path}), ascii_only=True)
        self.assertEqual([r.prefix for r in rows[1:]],
                         [ASCII_GUIDES[1]] * (len(TOP_LEVEL) - 1) + [ASCII_GUIDES[2]])

        alpha, beta, linked = child(tree, "Alpha"), child(tree, "beta"), child(tree, "linked")
        rows = flatten(tree, frozenset({tree.path, alpha.path, beta.path}))  # nested: only where requested
        self.assertEqual([r.node.name for r in rows],
                         ["root", ".hidden", "Alpha", "deep", "beta", "b.md", "linked",
                          "Bravo.txt", "SKILL.md", "zeta.txt"])
        self.assertEqual((rows[3].node.name, rows[3].depth, rows[3].prefix), ("deep", 2, STEM + LAST))
        self.assertEqual((rows[5].node.name, rows[5].prefix), ("b.md", STEM + LAST))
        self.assertNotIn("deeper", [r.node.name for r in rows])
        self.assertNotIn("x.txt", [r.node.name for r in rows])
        rows = flatten(tree, frozenset({tree.path, linked.path, "not-a-path"}))  # a link or unknown path: no-op
        self.assertEqual(len(rows), 1 + len(TOP_LEVEL))

        self.assertEqual(render(tree), EXPECTED_UNICODE)
        self.assertEqual(render(tree, ascii_only=True), EXPECTED_ASCII)
        shallow = build_tree(self.root, max_depth=1)
        expected = EXPECTED_ASCII[:1] + ("|-- .hidden/", "|-- Alpha/", "|-- beta/") + EXPECTED_ASCII[9:]
        self.assertEqual(render(shallow, ascii_only=True), expected)
        self.assertEqual(label(TreeNode("d", "d", True, 0)), "d/")
        self.assertEqual(label(TreeNode("f", "f", False, 0)), "f")
        self.assertEqual(render(TreeNode("f.txt", "f.txt", False, 3)), ("f.txt",))


if __name__ == "__main__":
    unittest.main()
