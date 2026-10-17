"""Tests for installer.core.status.

Inputs are built by hand on top of the fixture directories: the dataclasses
below are constructed here (digests via hashlib) so this module never depends
on installer.core.skills.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import tempfile
import unittest
from typing import Dict, Optional, Tuple

from installer.core import status
from installer.core.paths import Paths
from installer.core.types import (
    CONSUMERS,
    IGNORED_DIR_NAMES,
    IGNORED_DIR_REASONS,
    IGNORED_FILE_NAMES,
    SCOPES,
    InstalledSkill,
    LinkState,
    RemoteChange,
    RepoIssue,
    SkillMeta,
    SkillSource,
    State,
)
from installer.tests.fixtures import FRONTMATTER, build, make_skill, write

Key = Tuple[str, str]

REPO_ISSUES = (
    RepoIssue("claude", "dup", "duplicate-scope", "dup exists in shared/skills and claude-code/skills"),
    RepoIssue("claude", "nometa", "missing-frontmatter", "SKILL.md has no name or description"),
    RepoIssue("codex", "badname", "name-mismatch", "frontmatter name 'other-name' != 'badname'"),
)


# ------------------------------------------------------------------ helpers


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _list_files(root: str, rel: str = "") -> Tuple[str, ...]:
    found = []
    with os.scandir(os.path.join(root, rel)) as it:
        for entry in sorted(it, key=lambda e: e.name):
            path = os.path.join(rel, entry.name) if rel else entry.name
            if entry.is_dir(follow_symlinks=False):
                if entry.name not in IGNORED_DIR_NAMES:
                    found.extend(_list_files(root, path))
            elif entry.name not in IGNORED_FILE_NAMES:
                found.append(path)
    return tuple(sorted(found))


def _digest(root: str) -> str:
    h = hashlib.sha256()
    for rel in _list_files(root):
        with open(os.path.join(root, rel), "rb") as fh:
            h.update(f"{rel}\0{_sha256(fh.read())}\n".encode("utf-8"))
    return h.hexdigest()


def _meta(skill_dir: str) -> Optional[SkillMeta]:
    try:
        with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return SkillMeta(None, None)
    fields: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return SkillMeta(fields.get("name"), fields.get("description"))


def _source(paths: Paths, scope: str, name: str) -> SkillSource:
    path = os.path.join(paths.source_dir(scope), name)
    files = _list_files(path)
    size = sum(os.path.getsize(os.path.join(path, f)) for f in files)
    return SkillSource(scope, name, path, _meta(path) or SkillMeta(None, None), _digest(path), files, size)


def _installed(paths: Paths, scope: str, name: str) -> InstalledSkill:
    path = os.path.join(paths.install_dir(scope), name)
    is_link = os.path.islink(path)
    if is_link:
        kind = "symlink" if os.path.exists(path) else "broken-symlink"
    else:
        kind = "dir" if os.path.isdir(path) else "file"
    ignored = IGNORED_DIR_REASONS.get(name) or ("hidden entry" if name.startswith(".") else None)
    readable = os.path.isdir(path) and ignored is None
    files = _list_files(path) if readable else ()
    return InstalledSkill(
        scope=scope, name=name, path=path, kind=kind,
        link_target=os.readlink(path) if is_link else None,
        resolved=os.path.realpath(path) if os.path.exists(path) else None,
        meta=_meta(path) if readable else None,
        digest=_digest(path) if readable else None,
        files=files,
        size_bytes=sum(os.path.getsize(os.path.join(path, f)) for f in files),
        ignored_reason=ignored,
    )


def _catalog(paths: Paths) -> Dict[Key, SkillSource]:
    out: Dict[Key, SkillSource] = {}
    for scope in SCOPES:
        root = paths.source_dir(scope)
        for name in sorted(os.listdir(root)):
            if name.startswith(".") or name in IGNORED_DIR_REASONS:
                continue
            if os.path.isfile(os.path.join(root, name, "SKILL.md")):
                out[(scope, name)] = _source(paths, scope, name)
    return out


def _installed_all(paths: Paths) -> Dict[Key, InstalledSkill]:
    out: Dict[Key, InstalledSkill] = {}
    for scope in SCOPES:
        root = paths.install_dir(scope)
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                out[(scope, name)] = _installed(paths, scope, name)
    return out


def _by_key(rows) -> Dict[Key, status.SkillStatus]:
    return {row.key: row for row in rows}


# -------------------------------------------------------------------- tests


class StatusTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.paths = build(self.root)
        self.agents = self.paths.install_dir("shared")
        self.claude = self.paths.consumer_dir("claude")
        self.codex = self.paths.consumer_dir("codex")

    def compute(self, remote=None, repo_issues=()) -> Dict[Key, status.SkillStatus]:
        rows = status.compute(_catalog(self.paths), _installed_all(self.paths), self.paths,
                              remote=remote, repo_issues=repo_issues)
        self.rows = rows
        return _by_key(rows)

    def links_of(self, rows, name: str) -> Dict[str, status.ConsumerLink]:
        return {link.consumer: link for link in rows[("shared", name)].links}


class StatusTests(StatusTestCase):
    def test_pristine_fixture_rows_states_links_issues_counts_and_remote(self):
        rows = self.compute()
        self.assertEqual([row.key for row in self.rows], [
            ("shared", "alpha"), ("shared", "beta"), ("shared", "dup"), ("shared", "foreign1"),
            ("claude", "dup"), ("claude", "gamma"), ("claude", "ghost"), ("claude", "learned"),
            ("claude", "nometa"), ("claude", "synced"),
            ("codex", ".system"), ("codex", "badname"), ("codex", "gamma"), ("codex", "stray.txt"),
        ])
        expected = {
            ("shared", "alpha"): State.INSTALLED,
            ("shared", "beta"): State.MODIFIED,
            ("shared", "dup"): State.NOT_INSTALLED,
            ("shared", "foreign1"): State.FOREIGN,
            ("claude", "gamma"): State.INSTALLED,
            ("claude", "ghost"): State.FOREIGN,
            ("claude", "synced"): State.IGNORED,
            ("codex", "gamma"): State.MODIFIED,
            ("codex", "stray.txt"): State.FOREIGN,
        }
        for key, state in expected.items():
            self.assertIs(rows[key].state, state, key)
        self.assertIsNotNone(rows[("shared", "alpha")].installed)
        self.assertIsNone(rows[("shared", "dup")].installed)
        self.assertIsNone(rows[("shared", "foreign1")].source)
        # consumer entries for shared names are described by the shared row's links, not a row
        for consumer in CONSUMERS:
            self.assertNotIn((consumer, "alpha"), rows)  # OK links
            self.assertNotIn((consumer, "beta"), rows)  # REAL_DIR / BROKEN
        self.assertNotIn(("claude", "foreign1"), rows)

        for key in (("claude", "synced"), ("claude", "learned"), ("codex", ".system")):
            row = rows[key]
            self.assertIs(row.state, State.IGNORED, key)
            self.assertIsNotNone(row.installed.ignored_reason)
            self.assertEqual(row.issues, ())
            self.assertFalse(row.has_problem)
        self.assertNotIn(("shared", "synced"), rows)
        catalog = _catalog(self.paths)  # IGNORED wins even when the name is somehow in the catalog
        catalog[("claude", "learned")] = catalog[("claude", "gamma")]
        ignored = _by_key(status.compute(catalog, _installed_all(self.paths), self.paths))
        self.assertIs(ignored[("claude", "learned")].state, State.IGNORED)
        self.assertIsNotNone(ignored[("claude", "learned")].source)

        alpha = self.links_of(rows, "alpha")
        self.assertIs(alpha["claude"].state, LinkState.OK)
        self.assertIs(alpha["codex"].state, LinkState.OK)  # absolute target still resolves
        self.assertEqual(alpha["claude"].target, os.path.join("..", "..", ".agents", "skills", "alpha"))
        self.assertEqual(alpha["claude"].expected, self.paths.expected_link_target("claude", "alpha"))
        self.assertEqual(alpha["claude"].path, os.path.join(self.claude, "alpha"))
        beta = self.links_of(rows, "beta")
        self.assertIs(beta["claude"].state, LinkState.REAL_DIR)
        self.assertIs(beta["codex"].state, LinkState.BROKEN)
        self.assertEqual(beta["codex"].target, "/nonexistent/target/beta")
        self.assertEqual({l.state for l in self.links_of(rows, "dup").values()}, {LinkState.MISSING})
        self.assertEqual(rows[("claude", "gamma")].links, ())

        # a real directory that differs from the shared copy is a duplicate and a link problem
        beta_row = rows[("shared", "beta")]
        self.assertEqual(len(beta_row.duplicates), 1)
        self.assertTrue(beta_row.duplicates[0].startswith("claude: real directory at "))
        self.assertIn(status.DIFFERENT_COPY, beta_row.duplicates[0])
        self.assertIn(beta_row.links[0], beta_row.link_problems)
        for consumer in CONSUMERS:  # gamma is a sanctioned claude/codex variant pair
            self.assertEqual(rows[(consumer, "gamma")].duplicates, (), consumer)
            self.assertFalse(rows[(consumer, "gamma")].has_problem, consumer)

        ghost = rows[("claude", "ghost")]
        self.assertEqual(len(ghost.issues), 1)
        self.assertTrue(ghost.issues[0].startswith("broken symlink -> "))
        self.assertEqual(rows[("codex", "stray.txt")].issues, ("plain file, not a skill directory",))
        self.assertEqual(rows[("shared", "foreign1")].issues, ())
        self.assertEqual(rows[("shared", "foreign1")].duplicates, ())

        rows = self.compute(repo_issues=REPO_ISSUES)  # repo-level issue strings
        note = "repo: dup exists in shared/skills and claude-code/skills"
        self.assertEqual(rows[("shared", "dup")].duplicates, (note,))
        self.assertEqual(rows[("shared", "dup")].issues, ())
        self.assertEqual(rows[("claude", "dup")].duplicates, (note,))
        self.assertEqual(rows[("claude", "dup")].issues, (note,))
        self.assertEqual(rows[("claude", "nometa")].issues, ("repo: SKILL.md has no name or description",))
        self.assertEqual(rows[("codex", "badname")].issues, ("repo: frontmatter name 'other-name' != 'badname'",))
        self.assertEqual(rows[("shared", "alpha")].issues, ())

        by_scope = {c.scope: c for c in status.counts(self.rows)}
        self.assertEqual([c.scope for c in status.counts(self.rows)], list(SCOPES))
        shared, claude, codex = by_scope["shared"], by_scope["claude"], by_scope["codex"]
        self.assertEqual((shared.available, shared.installed, shared.modified, shared.missing, shared.foreign),
                         (3, 1, 1, 1, 1))
        self.assertEqual(shared.problems, 2)  # beta (links), dup (repo duplicate)
        self.assertEqual((claude.available, claude.installed, claude.modified, claude.missing, claude.foreign),
                         (3, 1, 0, 2, 1))
        self.assertEqual(claude.problems, 3)  # dup, ghost, nometa (gamma is a sanctioned variant pair)
        self.assertEqual((codex.available, codex.installed, codex.modified, codex.missing, codex.foreign),
                         (2, 0, 1, 1, 1))
        self.assertEqual(codex.problems, 2)  # badname, stray.txt
        self.assertEqual((shared.remote_updates, claude.remote_updates, codex.remote_updates), (0, 0, 0))
        self.assertEqual([row.key for row in status.problems(self.rows)], [
            ("shared", "beta"), ("shared", "dup"), ("claude", "dup"),
            ("claude", "ghost"), ("claude", "nometa"), ("codex", "badname"),
            ("codex", "stray.txt"),
        ])
        self.assertNotIn(rows[("shared", "alpha")], status.problems(self.rows))
        self.assertEqual(status.problems(()), ())
        self.assertEqual(status.compute({}, {}, self.paths), ())

        change = RemoteChange("origin/main", ("shared/skills/alpha/SKILL.md",), ("abc1234 tweak alpha",))
        gamma = RemoteChange("origin/main", ("codex/skills/gamma/SKILL.md",), ("abc1234 x",))
        rows = self.compute(remote={("shared", "alpha"): change, ("codex", "gamma"): gamma})
        self.assertIs(rows[("shared", "alpha")].remote, change)
        self.assertTrue(rows[("shared", "alpha")].has_remote_update)
        self.assertIsNone(rows[("shared", "beta")].remote)
        self.assertEqual([c.remote_updates for c in status.counts(self.rows)], [1, 0, 1])

    def test_link_variants_and_installed_entry_issues(self):
        shared_repo = os.path.join(self.paths.repo_dir, "shared", "skills")
        make_skill(shared_repo, "delta")
        shutil.copytree(os.path.join(self.paths.source_dir("shared"), "delta"), os.path.join(self.agents, "delta"))
        os.symlink(os.path.join("..", "..", ".agents", "skills", "alpha"), os.path.join(self.codex, "delta"))
        write(os.path.join(self.claude, "delta"), "not a link\n")
        make_skill(shared_repo, "epsilon")
        os.symlink(os.path.join("..", "..", ".agents", "skills", "epsilon"), os.path.join(self.claude, "epsilon"))
        rows = self.compute()
        links = self.links_of(rows, "delta")
        self.assertIs(links["codex"].state, LinkState.WRONG_TARGET)
        self.assertIs(links["claude"].state, LinkState.FILE)
        self.assertIs(rows[("shared", "delta")].state, State.INSTALLED)
        issues = rows[("shared", "delta")].issues
        self.assertEqual(len(issues), 2)
        self.assertTrue(any(i.startswith("codex: symlink points to") for i in issues))
        self.assertTrue(any(i.startswith("claude: plain file") for i in issues))
        self.assertNotIn(("claude", "delta"), rows)
        self.assertNotIn(("codex", "delta"), rows)
        row = rows[("shared", "epsilon")]  # a dangling link is BROKEN even when the shared copy is absent
        self.assertIs(row.state, State.NOT_INSTALLED)
        self.assertIs(self.links_of(rows, "epsilon")["claude"].state, LinkState.BROKEN)
        self.assertIs(self.links_of(rows, "epsilon")["codex"].state, LinkState.MISSING)
        self.assertEqual(len(row.links), 2)
        self.assertNotIn(("claude", "epsilon"), rows)

        # installed entries with frontmatter problems, a stray symlink, a plain foreign directory
        make_skill(self.agents, "nofm", frontmatter="", body="# none\n")
        make_skill(self.agents, "wrongname", frontmatter=FRONTMATTER.format(name="other", description="x"))
        os.makedirs(os.path.join(self.codex, "empty"))
        os.symlink(os.path.join("..", "..", ".agents", "skills", "alpha"), os.path.join(self.codex, "stray-link"))
        make_skill(self.codex, "plain", "Plain")
        rows = self.compute()
        self.assertEqual(rows[("shared", "nofm")].issues, ("SKILL.md frontmatter is missing name or description",))
        self.assertEqual(rows[("shared", "wrongname")].issues,
                         ("frontmatter name 'other' does not match directory name 'wrongname'",))
        self.assertEqual(rows[("codex", "empty")].issues, ("no readable SKILL.md",))
        self.assertIs(rows[("codex", "stray-link")].state, State.FOREIGN)
        self.assertTrue(rows[("codex", "stray-link")].issues[0].startswith("symlink -> "))
        self.assertEqual(rows[("codex", "plain")].issues, ())

        # a name in the platform catalog gets a platform row whatever the entry's kind
        repo_claude = os.path.join(self.paths.repo_dir, "claude-code", "skills")
        make_skill(repo_claude, "zeta", "Zeta")
        make_skill(repo_claude, "eta", "Eta")
        os.symlink(os.path.join("..", "..", ".agents", "skills", "missing"), os.path.join(self.claude, "zeta"))
        shutil.copytree(os.path.join(repo_claude, "eta"), os.path.join(self.agents, "eta-copy"))
        os.symlink(os.path.join("..", "..", ".agents", "skills", "eta-copy"), os.path.join(self.claude, "eta"))
        rows = self.compute()
        zeta = rows[("claude", "zeta")]
        self.assertIs(zeta.state, State.MODIFIED)
        self.assertIsNotNone(zeta.source)
        self.assertTrue(zeta.issues[0].startswith("broken symlink -> "))
        eta = rows[("claude", "eta")]
        self.assertIs(eta.state, State.INSTALLED)
        self.assertTrue(eta.issues[0].startswith("symlink -> "))
        self.assertIn("expected a real directory", eta.issues[0])

    def test_duplicate_copies_and_candidates_for_shared(self):
        # an identical real-directory copy in the other consumer
        make_skill(self.agents, "theta", "Theta")
        shutil.copytree(os.path.join(self.agents, "theta"), os.path.join(self.codex, "theta"))
        rows = self.compute()
        theta = rows[("shared", "theta")]
        self.assertIs(theta.state, State.FOREIGN)
        self.assertIs(self.links_of(rows, "theta")["codex"].state, LinkState.REAL_DIR)
        self.assertEqual(len(theta.duplicates), 1)
        self.assertIn(status.IDENTICAL_COPY, theta.duplicates[0])
        self.assertTrue(theta.duplicates[0].startswith("codex: "))
        self.assertTrue(any("codex: real directory shadows" in i for i in theta.issues))
        # without a shared copy the real directory is compared to the repo copy
        make_skill(os.path.join(self.paths.repo_dir, "shared", "skills"), "iota")
        shutil.copytree(os.path.join(self.paths.source_dir("shared"), "iota"), os.path.join(self.claude, "iota"))
        note = self.compute()[("shared", "iota")].duplicates[0]
        self.assertIn("identical to the repo copy", note)
        self.assertIn("shared copy not installed", note)
        self.assertNotIn(status.IDENTICAL_COPY, note)

        # two foreign real dirs with the same name qualify, whatever their content
        make_skill(self.claude, "kappa", "Kappa", body="# one\n")
        make_skill(self.codex, "kappa", "Kappa", body="# two\n")
        rows = self.compute()
        for consumer in CONSUMERS:
            self.assertIs(rows[(consumer, "kappa")].state, State.FOREIGN)
            self.assertEqual(rows[(consumer, "kappa")].duplicates, (status.CANDIDATE_FOR_SHARED,))
        # not when a shared copy exists: those are REAL_DIR duplicates on the shared row instead
        shutil.copytree(os.path.join(self.claude, "kappa"), os.path.join(self.agents, "kappa"))
        rows = self.compute()
        self.assertNotIn(("claude", "kappa"), rows)
        self.assertEqual(len(rows[("shared", "kappa")].duplicates), 2)
        self.assertIn(status.IDENTICAL_COPY, rows[("shared", "kappa")].duplicates[0])
        self.assertIn(status.DIFFERENT_COPY, rows[("shared", "kappa")].duplicates[1])
        self.assertEqual(rows[("claude", "ghost")].duplicates, ())  # and not when only one consumer has it

        # repo variants that converge: the installed copies are candidates unless one has no digest
        make_skill(os.path.join(self.paths.repo_dir, "claude-code", "skills"), "lam", "Lam", body="# claude\n")
        make_skill(os.path.join(self.paths.repo_dir, "codex", "skills"), "lam", "Lam", body="# codex\n")
        src = os.path.join(self.paths.source_dir("claude"), "lam")
        shutil.copytree(src, os.path.join(self.claude, "lam"))
        shutil.copytree(src, os.path.join(self.codex, "lam"))
        rows = self.compute()
        self.assertEqual((rows[("claude", "lam")].state, rows[("codex", "lam")].state),
                         (State.INSTALLED, State.MODIFIED))
        for consumer in CONSUMERS:
            self.assertEqual(rows[(consumer, "lam")].duplicates, (status.CANDIDATE_FOR_SHARED,))
        installed = _installed_all(self.paths)
        installed[("codex", "lam")] = dataclasses.replace(installed[("codex", "lam")], digest=None)
        rows = _by_key(status.compute(_catalog(self.paths), installed, self.paths))
        for consumer in CONSUMERS:
            self.assertEqual(rows[(consumer, "lam")].duplicates, (), consumer)
        # a single-platform skill installed for both tools is a candidate until the copies diverge
        make_skill(os.path.join(self.paths.repo_dir, "claude-code", "skills"), "mu", "Mu")
        src = os.path.join(self.paths.source_dir("claude"), "mu")
        shutil.copytree(src, os.path.join(self.claude, "mu"))
        shutil.copytree(src, os.path.join(self.codex, "mu"))
        rows = self.compute()
        self.assertEqual((rows[("claude", "mu")].state, rows[("codex", "mu")].state),
                         (State.INSTALLED, State.FOREIGN))
        for consumer in CONSUMERS:
            self.assertEqual(rows[(consumer, "mu")].duplicates, (status.CANDIDATE_FOR_SHARED,))
        write(os.path.join(self.codex, "mu", "extra.md"), "codex only\n")
        rows = self.compute()
        for consumer in CONSUMERS:
            self.assertEqual(rows[(consumer, "mu")].duplicates, (), consumer)

    def test_diff_text(self):
        text = status.diff_text(_source(self.paths, "shared", "beta"), _installed(self.paths, "shared", "beta"))
        lines = text.splitlines()
        self.assertEqual(lines[0], "--- repo/beta/SKILL.md")
        self.assertEqual(lines[1], "+++ installed/beta/SKILL.md")
        self.assertIn("+local edit", lines)
        self.assertEqual(lines[-1], "changed: SKILL.md")
        self.assertFalse(any(l.startswith("only") for l in lines))
        source = _source(self.paths, "shared", "alpha")
        self.assertEqual(status.diff_text(source, _installed(self.paths, "shared", "alpha")), "")
        notes = os.path.join(self.agents, "alpha", "references", "notes.md")
        with open(notes, encoding="utf-8") as fh:
            original = fh.read()
        write(notes, "edited notes\n")
        self.assertEqual(status.diff_text(source, _installed(self.paths, "shared", "alpha")),
                         "changed: references/notes.md\n")
        write(notes, original)

        text = status.diff_text(_source(self.paths, "codex", "gamma"), _installed(self.paths, "codex", "gamma"))
        self.assertEqual(text, "only installed: extra.md\n")
        partial = os.path.join(self.agents, "alpha-partial")
        os.makedirs(partial)
        shutil.copy(os.path.join(self.agents, "alpha", "SKILL.md"), partial)
        text = status.diff_text(source, _installed(self.paths, "shared", "alpha-partial"))
        self.assertEqual(text, "only in repo: references/notes.md\n")
        with open(os.path.join(self.agents, "alpha", "SKILL.md"), "ab") as fh:
            fh.write(b"\xff\xfe binary tail\n")
        text = status.diff_text(source, _installed(self.paths, "shared", "alpha"))
        self.assertIn("\ufffd", text)
        self.assertTrue(text.endswith("changed: SKILL.md\n"))
        os.makedirs(os.path.join(self.codex, "bare"))
        text = status.diff_text(source, _installed(self.paths, "codex", "bare"))
        self.assertIn("-# Body", text)
        self.assertIn("only in repo: SKILL.md\n", text)
        self.assertIn("only in repo: references/notes.md\n", text)


if __name__ == "__main__":
    unittest.main()
