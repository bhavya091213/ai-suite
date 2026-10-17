"""installer.core.actions: exact plans, real apply on a temp home, never a deletion."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Dict, Optional, Tuple

from installer.core import actions
from installer.core.paths import Paths
from installer.core.types import (
    ConsumerLink,
    InstalledSkill,
    LinkState,
    Operation,
    SkillMeta,
    SkillSource,
    SkillStatus,
    State,
)
from installer.tests import fixtures

TS = 1_700_000_000.0  # fixed stamp so backup roots are predictable
BROKEN_BETA = "/nonexistent/target/beta"  # as created by fixtures.make_home


def _meta(name: str) -> SkillMeta:
    return SkillMeta(name=name, description=f"{name} does things")


def _source(paths: Paths, scope: str, name: str) -> SkillSource:
    return SkillSource(scope=scope, name=name, path=os.path.join(paths.source_dir(scope), name),
                       meta=_meta(name), digest=f"repo-{name}", files=("SKILL.md",), size_bytes=1)


def _installed(paths: Paths, scope: str, name: str, kind: str = "dir", digest: Optional[str] = "disk",
               resolved: Optional[str] = None, ignored: Optional[str] = None) -> InstalledSkill:
    path = os.path.join(paths.install_dir(scope), name)
    if resolved is None and kind == "dir":
        resolved = path
    return InstalledSkill(scope=scope, name=name, path=path, kind=kind, link_target=None,
                          resolved=resolved, meta=_meta(name), digest=digest, files=("SKILL.md",),
                          size_bytes=1, ignored_reason=ignored)


def _status(paths: Paths, scope: str, name: str, state: State, *, source: bool = True,
            installed: Optional[InstalledSkill] = None, links: Tuple[ConsumerLink, ...] = (),
            duplicates: Tuple[str, ...] = ()) -> SkillStatus:
    return SkillStatus(scope=scope, name=name, state=state,
                       source=_source(paths, scope, name) if source else None,
                       installed=installed, links=links, duplicates=duplicates)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _count_entries(root: str) -> int:
    """Regular files plus symlinks (to anything) under root; links are not followed."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        total += len(filenames)
        total += sum(1 for d in dirnames if os.path.islink(os.path.join(dirpath, d)))
    return total


def _tree(root: str) -> Dict[str, str]:
    """relpath -> content of every regular file under root."""
    out: Dict[str, str] = {}
    for dirpath, _dirs, filenames in os.walk(root):
        for fname in filenames:
            full = os.path.join(dirpath, fname)
            out[os.path.relpath(full, root)] = _read(full)
    return out


def _kinds(ops: Tuple[Operation, ...]) -> Tuple[str, ...]:
    return tuple(op.kind for op in ops)


def _dsts(ops: Tuple[Operation, ...]) -> Tuple[str, ...]:
    return tuple(op.dst for op in ops)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = fixtures.build(tmp.name)
        self.home = os.path.join(tmp.name, "home")
        self.agents = self.paths.install_dir("shared")
        self.claude = self.paths.consumer_dir("claude")
        self.codex = self.paths.consumer_dir("codex")
        self.backup = self.paths.backup_root("installer", TS)
        self.retired = self.paths.backup_root("retired-skills", TS)

    def link(self, consumer: str, name: str, state: LinkState, target: Optional[str] = None) -> ConsumerLink:
        return ConsumerLink(consumer=consumer, path=os.path.join(self.paths.consumer_dir(consumer), name),
                            state=state, target=target,
                            expected=self.paths.expected_link_target(consumer, name))

    def status(self, scope: str, name: str, state: State, **kw) -> SkillStatus:
        return _status(self.paths, scope, name, state, **kw)

    def installed(self, scope: str, name: str, **kw) -> InstalledSkill:
        return _installed(self.paths, scope, name, **kw)

    def assert_all_ok(self, results, count: int) -> None:
        self.assertEqual(len(results), count)
        self.assertTrue(all(r.ok for r in results), [r.message for r in results])

    def assert_links_to_shared(self, path: str, name: str) -> None:
        self.assertTrue(os.path.islink(path), path)
        self.assertEqual(os.path.realpath(path), os.path.realpath(os.path.join(self.agents, name)))


class ActionTests(_Base):
    def test_install_and_update_plans_apply_and_back_up_before_replacing(self) -> None:
        links = (self.link("claude", "dup", LinkState.MISSING), self.link("codex", "dup", LinkState.MISSING))
        st = self.status("shared", "dup", State.NOT_INSTALLED, links=links)
        ops = actions.plan_install(st, self.paths)
        self.assertEqual(_kinds(ops), ("mkdir", "copytree", "mkdir", "symlink", "mkdir", "symlink"))
        dup = os.path.join(self.agents, "dup")
        self.assertEqual(_dsts(ops), (self.agents, dup, self.claude, os.path.join(self.claude, "dup"),
                                      self.codex, os.path.join(self.codex, "dup")))
        self.assertEqual(ops[1].src, st.source.path)
        self.assertEqual(ops[3].src, self.paths.expected_link_target("claude", "dup"))
        before = _count_entries(self.home)
        self.assert_all_ok(actions.apply(ops), 6)
        self.assertTrue(os.path.isdir(dup) and not os.path.islink(dup))
        self.assertEqual(_tree(dup), _tree(st.source.path))
        for consumer in ("claude", "codex"):
            path = os.path.join(self.paths.consumer_dir(consumer), "dup")
            self.assertEqual(os.readlink(path), self.paths.expected_link_target(consumer, "dup"))
            self.assert_links_to_shared(path, "dup")
        self.assertEqual(_count_entries(self.home), before + 3)

        # only consumers whose link is MISSING are linked, and `consumers` narrows further
        mixed = (self.link("claude", "dup", LinkState.REAL_DIR), self.link("codex", "dup", LinkState.MISSING))
        ops = actions.plan_install(self.status("shared", "dup", State.NOT_INSTALLED, links=mixed), self.paths)
        self.assertEqual(_kinds(ops), ("mkdir", "copytree", "mkdir", "symlink"))
        self.assertEqual(ops[-1].dst, os.path.join(self.codex, "dup"))
        ops = actions.plan_install(st, self.paths, consumers=("claude",))
        self.assertEqual([op.dst for op in ops if op.kind == "symlink"], [os.path.join(self.claude, "dup")])

        # platform scope: a copy only, no links
        st = self.status("claude", "nometa", State.NOT_INSTALLED)
        ops = actions.plan_install(st, self.paths)
        dst = os.path.join(self.claude, "nometa")
        self.assertEqual((_kinds(ops), _dsts(ops)), (("mkdir", "copytree"), (self.claude, dst)))
        self.assert_all_ok(actions.apply(ops), 2)
        self.assertTrue(os.path.isdir(dst) and not os.path.islink(dst))
        self.assertEqual(_tree(dst), _tree(st.source.path))

        # update: the modified copy is moved aside first, then the repo copy is installed
        st = self.status("shared", "beta", State.MODIFIED, installed=self.installed("shared", "beta"))
        ops = actions.plan_update(st, self.paths, self.backup)
        beta, moved = os.path.join(self.agents, "beta"), os.path.join(self.backup, "shared", "beta")
        self.assertEqual(_kinds(ops), ("backup", "mkdir", "copytree"))
        self.assertEqual(_dsts(ops), (moved, self.agents, beta))
        self.assertEqual((ops[0].src, ops[2].src), (beta, st.source.path))
        edited = _tree(beta)
        self.assertIn("local edit", edited["SKILL.md"])
        self.assert_all_ok(actions.apply(ops), 3)
        self.assertEqual(_tree(moved), edited)
        self.assertEqual(_tree(beta), _tree(st.source.path))

    def test_retire_moves_to_backup_and_never_deletes(self) -> None:
        links = (self.link("claude", "alpha", LinkState.OK, "../../.agents/skills/alpha"),
                 self.link("codex", "alpha", LinkState.OK, os.path.join(self.agents, "alpha")))
        alpha = self.status("shared", "alpha", State.INSTALLED, installed=self.installed("shared", "alpha"),
                            links=links)
        ops = actions.plan_retire(alpha, self.paths, self.retired)
        self.assertEqual(_kinds(ops), ("backup", "unlink-to-backup", "unlink-to-backup"))
        self.assertEqual(_dsts(ops), tuple(os.path.join(self.retired, s, "alpha")
                                           for s in ("shared", "claude", "codex")))
        claude_target = os.readlink(os.path.join(self.claude, "alpha"))
        before = _count_entries(self.home)
        self.assert_all_ok(actions.apply(ops), 3)
        self.assertEqual(_count_entries(self.home), before)  # everything moved, nothing deleted
        for d in (self.agents, self.claude, self.codex):
            self.assertFalse(os.path.lexists(os.path.join(d, "alpha")))
        self.assertTrue(os.path.isfile(os.path.join(self.retired, "shared", "alpha", "SKILL.md")))
        moved_link = os.path.join(self.retired, "claude", "alpha")
        self.assertTrue(os.path.islink(moved_link))  # the symlink itself moved, as a symlink
        self.assertEqual(os.readlink(moved_link), claude_target)
        self.assertTrue(os.path.islink(os.path.join(self.retired, "codex", "alpha")))

        # consumers_only keeps the shared copy and follows only links that point at it
        broken = (self.link("claude", "alpha", LinkState.BROKEN, "../../.agents/skills/alpha"),
                  self.link("codex", "alpha", LinkState.BROKEN, "/elsewhere/alpha"))
        st = self.status("shared", "alpha", State.INSTALLED, installed=self.installed("shared", "alpha"),
                         links=broken)
        ops = actions.plan_retire(st, self.paths, self.retired, consumers_only=True)
        self.assertEqual(_dsts(ops), (os.path.join(self.retired, "claude", "alpha"),))
        for state in (LinkState.WRONG_TARGET, LinkState.REAL_DIR, LinkState.FILE, LinkState.MISSING):
            st = self.status("shared", "alpha", State.INSTALLED, installed=self.installed("shared", "alpha"),
                             links=(self.link("claude", "alpha", state, "x"),))
            self.assertEqual(actions.plan_retire(st, self.paths, self.retired, consumers_only=True), (), state)
        ops = actions.plan_retire(alpha, self.paths, self.retired, consumers_only=True)
        self.assertEqual(_kinds(ops), ("unlink-to-backup", "unlink-to-backup"))

        # a platform skill is a plain directory move
        st = self.status("codex", "gamma", State.MODIFIED, installed=self.installed("codex", "gamma"))
        ops = actions.plan_retire(st, self.paths, self.retired)
        moved = os.path.join(self.retired, "codex", "gamma")
        self.assertEqual((_kinds(ops), _dsts(ops)), (("backup",), (moved,)))
        self.assert_all_ok(actions.apply(ops), 1)
        self.assertTrue(os.path.isfile(os.path.join(moved, "extra.md")))
        self.assertFalse(os.path.lexists(os.path.join(self.codex, "gamma")))

    def test_relink_replaces_via_backup_and_keeps_differing_copies(self) -> None:
        def beta(claude_state: LinkState = LinkState.REAL_DIR, **kw) -> SkillStatus:
            links = (self.link("claude", "beta", claude_state),
                     self.link("codex", "beta", LinkState.BROKEN, BROKEN_BETA))
            return self.status("shared", "beta", State.MODIFIED,
                               installed=self.installed("shared", "beta", digest="same"), links=links, **kw)

        def index(digest: str) -> Dict[Tuple[str, str], InstalledSkill]:
            return {("claude", "beta"): self.installed("claude", "beta", digest=digest)}

        # a broken link and an identical real directory both become symlinks, old ones kept
        ops = actions.plan_relink(beta(), self.paths, self.backup, installed_index=index("same"))
        c_beta, x_beta = os.path.join(self.claude, "beta"), os.path.join(self.codex, "beta")
        c_bak, x_bak = os.path.join(self.backup, "claude", "beta"), os.path.join(self.backup, "codex", "beta")
        self.assertEqual(_kinds(ops), ("backup", "mkdir", "symlink", "unlink-to-backup", "mkdir", "symlink"))
        self.assertEqual(_dsts(ops), (c_bak, self.claude, c_beta, x_bak, self.codex, x_beta))
        original = _tree(c_beta)
        before = _count_entries(self.home)
        self.assert_all_ok(actions.apply(ops), 6)
        self.assert_links_to_shared(c_beta, "beta")
        self.assert_links_to_shared(x_beta, "beta")
        self.assertTrue(os.path.isdir(c_bak) and not os.path.islink(c_bak))
        self.assertEqual(_tree(c_bak), original)
        self.assertTrue(os.path.islink(x_bak))  # the broken symlink moved as a symlink
        self.assertEqual(os.readlink(x_bak), BROKEN_BETA)
        self.assertEqual(_count_entries(self.home), before + 2)

        # a real directory that differs is never converted; links that are fine are left alone
        marker = ("claude: real directory - identical copy - can be converted to a symlink",)
        ops = actions.plan_relink(beta(duplicates=marker), self.paths, self.backup)  # no index
        self.assertEqual(_kinds(ops)[:3], ("backup", "mkdir", "symlink"))
        for kwargs in (dict(duplicates=("claude: real directory - different content",)),
                       dict(installed_index=index("other"))):
            duplicates = kwargs.pop("duplicates", ())
            ops = actions.plan_relink(beta(duplicates=duplicates), self.paths, self.backup, **kwargs)
            self.assertEqual(_kinds(ops), ("unlink-to-backup", "mkdir", "symlink"))
        for state in (LinkState.OK, LinkState.FILE):
            ops = actions.plan_relink(beta(claude_state=state), self.paths, self.backup,
                                      installed_index=index("same"))
            self.assertEqual(_kinds(ops), ("unlink-to-backup", "mkdir", "symlink"), state)

        # a wrong-target link is replaced via backup and a missing one is created
        wrong = os.path.join("..", "..", ".agents", "skills", "alpha")
        x_f1 = os.path.join(self.codex, "foreign1")
        os.symlink(wrong, x_f1)
        links = (self.link("claude", "foreign1", LinkState.MISSING),
                 self.link("codex", "foreign1", LinkState.WRONG_TARGET, wrong))
        st = self.status("shared", "foreign1", State.FOREIGN, source=False,
                         installed=self.installed("shared", "foreign1"), links=links)
        ops = actions.plan_relink(st, self.paths, self.backup)
        c_f1, x_bak = os.path.join(self.claude, "foreign1"), os.path.join(self.backup, "codex", "foreign1")
        self.assertEqual(_kinds(ops), ("mkdir", "symlink", "unlink-to-backup", "mkdir", "symlink"))
        self.assertEqual(_dsts(ops), (self.claude, c_f1, x_bak, self.codex, x_f1))
        self.assert_all_ok(actions.apply(ops), 5)
        self.assert_links_to_shared(c_f1, "foreign1")
        self.assert_links_to_shared(x_f1, "foreign1")
        self.assertEqual(os.readlink(x_bak), wrong)

    def test_push_to_repo_backs_up_and_never_pushes_repo_onto_itself_or_plans_nothing(self) -> None:
        shared_src = self.paths.source_dir("shared")
        foreign = self.status("shared", "foreign1", State.FOREIGN, source=False,
                              installed=self.installed("shared", "foreign1"))
        ops = actions.plan_push_to_repo(foreign, self.paths, self.backup)
        dst = os.path.join(shared_src, "foreign1")
        self.assertEqual((_kinds(ops), _dsts(ops)), (("mkdir", "copytree"), (shared_src, dst)))
        self.assertEqual(ops[1].src, os.path.join(self.agents, "foreign1"))
        self.assert_all_ok(actions.apply(ops), 2)
        self.assertEqual(_tree(dst), _tree(os.path.join(self.agents, "foreign1")))

        modified = self.status("shared", "beta", State.MODIFIED, installed=self.installed("shared", "beta"))
        ops = actions.plan_push_to_repo(modified, self.paths, self.backup)
        repo_beta = os.path.join(shared_src, "beta")
        bak = os.path.join(self.backup, "repo", "shared", "beta")
        self.assertEqual(_kinds(ops), ("backup", "mkdir", "copytree"))
        self.assertEqual(_dsts(ops), (bak, shared_src, repo_beta))
        original = _tree(repo_beta)
        self.assert_all_ok(actions.apply(ops), 3)
        self.assertEqual(_tree(bak), original)  # the repo's old copy is kept
        self.assertEqual(_tree(repo_beta), _tree(os.path.join(self.agents, "beta")))
        self.assertIn("local edit", _read(os.path.join(repo_beta, "SKILL.md")))

        # a symlinked entry is pushed from where it resolves
        resolved = os.path.join(self.agents, "alpha")
        linked = self.status("codex", "alpha", State.FOREIGN, source=False,
                             installed=self.installed("codex", "alpha", kind="symlink", resolved=resolved))
        ops = actions.plan_push_to_repo(linked, self.paths, self.backup)
        self.assertEqual(_kinds(ops), ("mkdir", "copytree"))
        self.assertEqual((ops[1].src, ops[1].dst),
                         (resolved, os.path.join(self.paths.source_dir("codex"), "alpha")))

        # live editing: ~/.agents/skills/<name> links at the repo copy, so there is nothing to push
        repo_live = fixtures.make_skill(shared_src, "live", "Edited in place")
        link = os.path.join(self.agents, "live")
        os.symlink(repo_live, link)
        inst = self.installed("shared", "live", kind="symlink", resolved=os.path.realpath(link))
        st = self.status("shared", "live", State.INSTALLED, installed=inst)
        before = _count_entries(self.home)
        ops = actions.plan_push_to_repo(st, self.paths, self.backup)
        self.assertEqual(ops, ())
        self.assert_all_ok(actions.apply(ops), 0)
        self.assertTrue(os.path.isfile(os.path.join(repo_live, "SKILL.md")))
        self.assertEqual(_count_entries(self.home), before)
        repo_alpha = os.path.join(shared_src, "alpha")
        for target in (os.path.join(repo_alpha, "references"), shared_src):  # inside, or around, the repo copy
            inst = self.installed("shared", "alpha", kind="symlink", resolved=target)
            st = self.status("shared", "alpha", State.MODIFIED, installed=inst)
            self.assertEqual(actions.plan_push_to_repo(st, self.paths, self.backup), (), target)
        self.assertTrue(os.path.isfile(os.path.join(repo_alpha, "SKILL.md")))

        # no plan outside the expected state, or for entries that are not usable skills
        for state in (State.INSTALLED, State.MODIFIED, State.FOREIGN, State.IGNORED):
            st = self.status("shared", "alpha", state, installed=self.installed("shared", "alpha"))
            self.assertEqual(actions.plan_install(st, self.paths), (), state)
        for state in (State.INSTALLED, State.NOT_INSTALLED, State.FOREIGN):
            st = self.status("shared", "beta", state, installed=self.installed("shared", "beta"))
            self.assertEqual(actions.plan_update(st, self.paths, self.backup), (), state)
        ignored = self.installed("claude", "synced", ignored="managed")
        self.assertEqual(actions.plan_retire(self.status("claude", "synced", State.IGNORED, installed=ignored),
                                             self.paths, self.retired), ())
        st = self.status("claude", "gamma", State.INSTALLED, installed=self.installed("claude", "gamma"))
        self.assertEqual(actions.plan_relink(st, self.paths, self.backup), ())
        for entry in (None, self.installed("codex", "beta", kind="broken-symlink", digest=None),
                      self.installed("codex", "stray.txt", kind="file", digest=None),
                      self.installed("codex", ".system", ignored="system")):
            st = self.status("codex", "x", State.FOREIGN, source=False, installed=entry)
            self.assertEqual(actions.plan_push_to_repo(st, self.paths, self.backup), (), entry)

    def test_apply_dry_run_failures_and_symlink_moves_change_nothing_destructive(self) -> None:
        links = (self.link("claude", "dup", LinkState.MISSING), self.link("codex", "dup", LinkState.MISSING))
        ops = actions.plan_install(self.status("shared", "dup", State.NOT_INSTALLED, links=links), self.paths)
        before = _count_entries(self.home)
        results = actions.apply(ops, dry_run=True)
        self.assertEqual(len(results), len(ops))
        self.assertTrue(all(r.ok and r.message == "(dry run)" for r in results))
        self.assertEqual(_count_entries(self.home), before)
        self.assertFalse(os.path.lexists(os.path.join(self.agents, "dup")))

        # install onto a directory that is already there: stop, touch nothing
        links = (self.link("claude", "beta", LinkState.MISSING), self.link("codex", "beta", LinkState.MISSING))
        ops = actions.plan_install(self.status("shared", "beta", State.NOT_INSTALLED, links=links), self.paths)
        skill_md = os.path.join(self.agents, "beta", "SKILL.md")
        original = _read(skill_md)
        results = actions.apply(ops)
        self.assertEqual(len(results), 2)  # mkdir ok, copytree refused, the rest never ran
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertEqual(results[1].op.kind, "copytree")
        self.assertEqual(_read(skill_md), original)
        self.assertEqual(os.readlink(os.path.join(self.codex, "beta")), BROKEN_BETA)

        # a failure stops later ops; backup refuses an existing destination; there is no delete kind
        newdir = os.path.join(self.home, "newdir")
        alpha, beta = os.path.join(self.agents, "alpha"), os.path.join(self.agents, "beta")
        copy = Operation(kind="copytree", dst=alpha, src=os.path.join(self.paths.source_dir("shared"), "alpha"))
        results = actions.apply((copy, Operation(kind="mkdir", dst=newdir)))
        self.assertEqual([r.ok for r in results], [False])
        self.assertTrue(results[0].message)
        self.assertFalse(os.path.exists(newdir))
        results = actions.apply((Operation(kind="backup", dst=beta, src=alpha),))
        self.assertFalse(results[0].ok)
        self.assertTrue(os.path.isdir(alpha))
        self.assertIn("local edit", _read(os.path.join(beta, "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(beta, "alpha")))
        self.assertEqual([r.ok for r in actions.apply((Operation(kind="delete", dst=self.home),))], [False])
        self.assertTrue(os.path.isdir(self.home))
        results = actions.apply((Operation(kind="copytree", dst=os.path.join(self.home, "x")),))  # no source
        self.assertEqual([r.ok for r in results], [False])
        self.assertFalse(os.path.exists(os.path.join(self.home, "x")))

        # unlink-to-backup takes the symlink itself, never what it points at
        link, dst = os.path.join(self.claude, "alpha"), os.path.join(self.backup, "claude", "alpha")
        target = os.readlink(link)
        self.assert_all_ok(actions.apply((Operation(kind="unlink-to-backup", dst=dst, src=link),)), 1)
        self.assertTrue(os.path.islink(dst))
        self.assertEqual(os.readlink(dst), target)
        self.assertTrue(os.path.isfile(os.path.join(self.agents, "alpha", "SKILL.md")))
        self.assertFalse(os.path.lexists(link))

        # copytree leaves OS and cache junk behind
        src = os.path.join(self.paths.source_dir("shared"), "alpha")
        fixtures.write(os.path.join(src, ".DS_Store"), "junk")
        fixtures.write(os.path.join(src, "__pycache__", "x.pyc"), "junk")
        copied = os.path.join(self.home, "copy")
        self.assert_all_ok(actions.apply((Operation(kind="copytree", dst=copied, src=src),)), 1)
        self.assertEqual(sorted(_tree(copied)), ["SKILL.md", os.path.join("references", "notes.md")])

    def test_describe_shortens_home_and_shows_symlink_targets_verbatim(self) -> None:
        home = os.path.expanduser("~")
        paths = Paths(repo_dir=os.path.join(home, "x", "repo"), agents_home=os.path.join(home, "x", ".agents"),
                      claude_home=os.path.join(home, "x", ".claude"), codex_home=os.path.join(home, "x", ".codex"))
        copy = Operation(kind="copytree", dst=os.path.join(paths.install_dir("shared"), "alpha"),
                         src=os.path.join(paths.source_dir("shared"), "alpha"), note="install shared/alpha")
        self.assertEqual(actions.describe(copy, paths),
                         "copytree  ~/x/repo/shared/skills/alpha -> ~/x/.agents/skills/alpha  (install shared/alpha)")
        link = Operation(kind="symlink", dst=os.path.join(paths.consumer_dir("claude"), "alpha"),
                         src="../../.agents/skills/alpha")
        self.assertEqual(actions.describe(link, paths),
                         "symlink  ../../.agents/skills/alpha -> ~/x/.claude/skills/alpha")
        self.assertEqual(actions.describe(Operation(kind="mkdir", dst=paths.install_dir("shared")), paths),
                         "mkdir  ~/x/.agents/skills")


if __name__ == "__main__":
    unittest.main()
