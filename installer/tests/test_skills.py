"""Tests for installer.core.skills."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from installer.core.skills import (
    digest,
    is_valid_name,
    list_files,
    scan_catalog,
    scan_installed,
    size_of,
)
from installer.core.types import IGNORED_DIR_REASONS
from installer.tests import fixtures

EXPECTED_CATALOG_KEYS = {
    ("shared", "alpha"), ("shared", "beta"), ("shared", "dup"),
    ("claude", "gamma"), ("claude", "dup"), ("claude", "nometa"),
    ("codex", "gamma"), ("codex", "badname"),
}

# (scope, name) -> (kind, ignored?) for every entry fixtures.make_home creates
EXPECTED_INSTALLED = {
    ("shared", "alpha"): ("dir", False),
    ("shared", "beta"): ("dir", False),
    ("shared", "foreign1"): ("dir", False),
    ("claude", "alpha"): ("symlink", False),
    ("claude", "beta"): ("dir", False),
    ("claude", "gamma"): ("dir", False),
    ("claude", "ghost"): ("broken-symlink", False),
    ("claude", "synced"): ("dir", True),
    ("claude", "learned"): ("dir", True),
    ("codex", "alpha"): ("symlink", False),
    ("codex", "beta"): ("broken-symlink", False),
    ("codex", "gamma"): ("dir", False),
    ("codex", ".system"): ("dir", True),
    ("codex", "stray.txt"): ("file", False),
}


def _sha256_file(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = fixtures.build(self.tmp.name)

    def repo_skill(self, scope: str, name: str) -> str:
        return os.path.join(self.paths.source_dir(scope), name)

    def installed_skill(self, scope: str, name: str) -> str:
        return os.path.join(self.paths.install_dir(scope), name)

    def scratch_dir(self, name: str) -> str:
        path = os.path.join(self.tmp.name, "scratch", name)
        os.makedirs(path, exist_ok=True)
        return path


class SkillsTests(FixtureCase):
    def test_list_files_digest_size_and_names(self) -> None:
        alpha = self.repo_skill("shared", "alpha")
        self.assertEqual(list_files(alpha), ("SKILL.md", "references/notes.md"))
        self.assertEqual(list_files(self.scratch_dir("empty")), ())
        root = self.scratch_dir("ignored")  # sorted posix paths, ignored names skipped
        for rel in ("SKILL.md", ".DS_Store", "Thumbs.db", "sub/.gitkeep", "sub/keep.md", "__pycache__/m.pyc",
                    ".git/HEAD", "node_modules/pkg/index.js", ".hidden/file"):
            fixtures.write(os.path.join(root, *rel.split("/")), "x")
        self.assertEqual(list_files(root), (".hidden/file", "SKILL.md", "sub/keep.md"))
        order = self.scratch_dir("order")  # sorted globally, not per directory
        for rel in ("a/b", "a-b", "a.txt"):
            fixtures.write(os.path.join(order, *rel.split("/")), "x")
        self.assertEqual(list_files(order), tuple(sorted(("a/b", "a-b", "a.txt"))))

        links = self.scratch_dir("links")  # a symlinked subdirectory is one entry; a root symlink is followed
        fixtures.write(os.path.join(links, "SKILL.md"), "x")
        os.symlink(alpha, os.path.join(links, "linked"))
        os.symlink("nowhere", os.path.join(links, "dangling"))
        self.assertEqual(list_files(links), ("SKILL.md", "dangling", "linked"))
        root_link = os.path.join(self.scratch_dir("rootlink"), "alpha-link")
        os.symlink(alpha, root_link)
        self.assertEqual(list_files(root_link), ("SKILL.md", "references/notes.md"))
        with self.assertRaises(OSError):
            list_files(os.path.join(self.tmp.name, "absent"))
        with self.assertRaises(OSError):
            list_files(self.installed_skill("codex", "stray.txt"))

        expected = hashlib.sha256()  # the documented digest formula
        for rel in ("SKILL.md", "references/notes.md"):
            content_hash = _sha256_file(os.path.join(alpha, *rel.split("/")))
            expected.update((rel + "\0" + content_hash + "\n").encode("utf-8"))
        self.assertEqual(digest(alpha), expected.hexdigest())
        self.assertEqual(digest(alpha), digest(self.installed_skill("shared", "alpha")))
        self.assertEqual(digest(self.repo_skill("shared", "beta")), digest(self.installed_skill("claude", "beta")))
        self.assertNotEqual(digest(self.repo_skill("shared", "beta")),
                            digest(self.installed_skill("shared", "beta")))
        total = sum(os.path.getsize(os.path.join(alpha, *rel.split("/"))) for rel in list_files(alpha))
        self.assertGreater(total, 0)
        self.assertEqual(size_of(alpha), total)

        one, two = self.scratch_dir("one"), self.scratch_dir("two")
        fixtures.write(os.path.join(one, "a.md"), "same")
        fixtures.write(os.path.join(two, "b.md"), "same")
        self.assertNotEqual(digest(one), digest(two))  # a rename changes it
        noisy = self.scratch_dir("noise")
        fixtures.write(os.path.join(noisy, "SKILL.md"), "x")
        before = digest(noisy)
        fixtures.write(os.path.join(noisy, ".DS_Store"), "junk")
        fixtures.write(os.path.join(noisy, "__pycache__", "x.pyc"), "junk")
        self.assertEqual(digest(noisy), before)  # ignored files do not
        l1, l2, l3 = (self.scratch_dir(n) for n in ("l1", "l2", "l3"))
        os.symlink("target-a", os.path.join(l1, "link"))
        os.symlink("target-b", os.path.join(l2, "link"))
        os.symlink("target-a", os.path.join(l3, "link"))
        self.assertNotEqual(digest(l1), digest(l2))  # symlinks hash their target string
        self.assertEqual(digest(l1), digest(l3))

        for bad in ("", ".", "..", "a/b", ".hidden", "a\0b", "/abs", "trailing/", "a" + os.sep + "b"):
            self.assertFalse(is_valid_name(bad), bad)
        for good in ("lambda-gpu-training", "alpha", "x", "name.with.dots", "under_score"):
            self.assertTrue(is_valid_name(good), good)

    def test_scan_catalog_keys_sources_and_repo_issues(self) -> None:
        catalog, issues = scan_catalog(self.paths)
        self.assertEqual(set(catalog), EXPECTED_CATALOG_KEYS)  # duplicates keep both entries
        for key, source in catalog.items():
            self.assertEqual(source.key, key)
            self.assertEqual(source.path, self.repo_skill(*key))
        kinds = {(issue.scope, issue.name, issue.kind) for issue in issues}
        self.assertEqual(kinds, {
            ("claude", "dup", "duplicate-scope"),
            ("claude", "nometa", "missing-frontmatter"),
            ("codex", "badname", "name-mismatch"),
        })
        self.assertFalse([issue for issue in issues if issue.name == "learned"])
        for issue in issues:
            self.assertTrue(issue.message)
        alpha = catalog[("shared", "alpha")]
        self.assertEqual(alpha.files, ("SKILL.md", "references/notes.md"))
        self.assertEqual(alpha.digest, digest(alpha.path))
        self.assertEqual(alpha.size_bytes, size_of(alpha.path))
        self.assertEqual(alpha.meta.name, "alpha")
        self.assertTrue(alpha.meta.valid)
        nometa = catalog[("claude", "nometa")]  # invalid frontmatter is still catalogued
        self.assertIsNone(nometa.meta.name)
        self.assertIsNone(nometa.meta.description)
        self.assertEqual(catalog[("codex", "badname")].meta.name, "other-name")

        # a directory without SKILL.md is an issue, except hidden, tool-managed and plain files
        shared = self.paths.source_dir("shared")
        os.makedirs(os.path.join(shared, "empty-dir"))
        os.makedirs(os.path.join(shared, ".hidden-dir"))
        fixtures.write(os.path.join(shared, "README.md"), "stray file\n")
        for managed in IGNORED_DIR_REASONS:
            fixtures.make_skill(shared, managed, "would be a skill")
        catalog, issues = scan_catalog(self.paths)
        self.assertEqual(set(catalog), EXPECTED_CATALOG_KEYS)
        self.assertEqual([(i.scope, i.name) for i in issues if i.kind == "missing-skill-md"],
                         [("shared", "empty-dir")])
        names = {issue.name for issue in issues}
        self.assertFalse(names & set(IGNORED_DIR_REASONS))
        self.assertNotIn(".hidden-dir", names)
        self.assertNotIn("README.md", names)
        bare = os.path.join(self.tmp.name, "bare-repo")
        os.makedirs(bare)
        self.assertEqual(scan_catalog(fixtures.paths_for(self.tmp.name, repo=bare)), ({}, ()))

    def test_scan_installed_kinds_ignored_symlinks_dirs_and_files(self) -> None:
        installed = scan_installed(self.paths)
        catalog, _ = scan_catalog(self.paths)
        self.assertEqual(set(installed), set(EXPECTED_INSTALLED))
        for key, (kind, ignored) in EXPECTED_INSTALLED.items():
            with self.subTest(key=key):
                entry = installed[key]
                self.assertEqual(entry.key, key)
                self.assertEqual(entry.kind, kind)
                self.assertEqual(entry.path, self.installed_skill(*key))
                self.assertEqual(entry.ignored_reason is not None, ignored)
        for key in (("claude", "synced"), ("claude", "learned"), ("codex", ".system")):
            entry = installed[key]
            self.assertEqual(entry.ignored_reason, IGNORED_DIR_REASONS[key[1]])
            self.assertIsNone(entry.digest)
            self.assertIsNone(entry.meta)
            self.assertEqual(entry.files, ())
            self.assertEqual(entry.size_bytes, 0)

        shared_alpha = os.path.realpath(self.installed_skill("shared", "alpha"))
        for consumer in ("claude", "codex"):  # digest/meta are computed through the link
            entry = installed[(consumer, "alpha")]
            self.assertEqual(entry.digest, catalog[("shared", "alpha")].digest)
            self.assertEqual(entry.files, ("SKILL.md", "references/notes.md"))
            assert entry.meta is not None
            self.assertEqual(entry.meta.name, "alpha")
            self.assertEqual(entry.resolved, shared_alpha)
        claude_alpha = installed[("claude", "alpha")]
        self.assertEqual(claude_alpha.link_target, os.readlink(claude_alpha.path))
        self.assertFalse(os.path.isabs(claude_alpha.link_target or ""))
        self.assertTrue(os.path.isabs(installed[("codex", "alpha")].link_target or ""))
        for key in (("claude", "ghost"), ("codex", "beta")):
            with self.subTest(key=key):
                entry = installed[key]
                self.assertEqual(entry.kind, "broken-symlink")
                self.assertEqual(entry.link_target, os.readlink(entry.path))
                self.assertIsNone(entry.resolved)
                self.assertIsNone(entry.digest)
                self.assertIsNone(entry.meta)
                self.assertEqual(entry.files, ())

        alpha, beta = installed[("shared", "alpha")], installed[("shared", "beta")]
        self.assertEqual(alpha.digest, catalog[("shared", "alpha")].digest)
        self.assertIsNotNone(beta.digest)
        self.assertNotEqual(beta.digest, catalog[("shared", "beta")].digest)
        claude_beta = installed[("claude", "beta")]
        self.assertEqual(claude_beta.digest, catalog[("shared", "beta")].digest)
        self.assertEqual(claude_beta.resolved, os.path.realpath(claude_beta.path))
        codex_gamma = installed[("codex", "gamma")]
        self.assertEqual(codex_gamma.files, ("SKILL.md", "extra.md"))
        self.assertNotEqual(codex_gamma.digest, catalog[("codex", "gamma")].digest)
        self.assertGreater(codex_gamma.size_bytes, 0)
        foreign = installed[("shared", "foreign1")]
        assert foreign.meta is not None
        self.assertEqual(foreign.meta.name, "foreign1")
        stray = installed[("codex", "stray.txt")]
        self.assertEqual(stray.kind, "file")
        self.assertIsNone(stray.link_target)
        self.assertIsNone(stray.digest)
        self.assertIsNone(stray.meta)
        self.assertEqual(stray.size_bytes, os.path.getsize(stray.path))

    def test_scan_installed_ordering_file_symlinks_and_missing_install_dirs(self) -> None:
        fixtures.make_skill(self.paths.install_dir("shared"), ".secret", "hidden")
        file_link = os.path.join(self.paths.install_dir("shared"), "filelink")
        os.symlink(self.installed_skill("codex", "stray.txt"), file_link)
        installed = scan_installed(self.paths)
        keys = list(installed)
        self.assertIsNotNone(installed[("shared", ".secret")].ignored_reason)
        self.assertIsNone(installed[("shared", ".secret")].digest)
        scope_rank = {"shared": 0, "claude": 1, "codex": 2}  # sorted by scope, then name
        self.assertEqual(keys, sorted(keys, key=lambda k: (scope_rank[k[0]], k[1])))
        link = installed[("shared", "filelink")]  # a symlink to a plain file is not a skill directory
        self.assertEqual(link.kind, "symlink")
        self.assertIsNone(link.digest)
        self.assertEqual(link.files, ())

        paths = fixtures.paths_for(self.tmp.name, home=os.path.join(self.tmp.name, "nohome"))
        self.assertEqual(scan_installed(paths), {})
        partial = fixtures.paths_for(self.tmp.name)
        os.rename(partial.install_dir("codex"), partial.install_dir("codex") + ".moved")
        self.assertEqual({scope for scope, _ in scan_installed(partial)}, {"shared", "claude"})


if __name__ == "__main__":
    unittest.main()
