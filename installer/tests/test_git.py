"""Tests for installer.core.git.

Stub tests replace ``run`` (and put a never-executed fake ``git`` on PATH) so they do
not depend on a real git. One real-git test builds a bare origin and two clones inside
a TemporaryDirectory and is skipped when git is not installed.
"""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Any, Dict, List, Optional, Tuple

from installer.core import git
from installer.core.paths import Paths
from installer.core.types import RemoteChange, SkillMeta, SkillSource
from installer.tests import fixtures

HAVE_GIT = shutil.which("git") is not None
ALPHA_MD = "shared/skills/alpha/SKILL.md"
ZETA_MD = "shared/skills/zeta/SKILL.md"
CAFE = "caf\u00e9"  # a name git C-quotes under the default core.quotePath
CAFE_MD = f"shared/skills/{CAFE}/SKILL.md"
MISSING_DIR = "repo directory does not exist"
Reply = Tuple[int, str, str]

# canned replies for a healthy checkout 3 commits behind origin/main, keyed by the git
# arguments after "git" (longest-prefix match; anything else answers (0, "", ""))
HEALTHY: Dict[Tuple[str, ...], Reply] = {
    ("--version",): (0, "git version 2.40.0", ""),
    ("rev-parse", "--is-inside-work-tree"): (0, "true", ""),
    ("rev-parse", "--abbrev-ref", "HEAD"): (0, "main", ""),
    ("rev-parse", "--short"): (0, "abc1234", ""),
    ("rev-parse", "--abbrev-ref", "@{u}"): (0, "origin/main", ""),
    ("rev-parse", "--git-dir"): (0, ".git", ""),
    ("rev-list",): (0, "0\t3", ""),
    ("remote",): (0, "https://example.test/me/repo.git", ""),
}


class RecordingRun:
    """subprocess.run stand-in: records every call, returns a canned result or raises."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "",
                 raises: Optional[BaseException] = None,
                 script: Optional[Dict[Tuple[str, ...], Reply]] = None) -> None:
        self.default: Reply = (returncode, stdout, stderr)
        self.raises = raises
        self.script = script or {}
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(dict(kwargs, args=args))
        if self.raises is not None:
            raise self.raises
        rest = tuple(args[1:])
        matches = [k for k in self.script if rest[:len(k)] == k]
        code, out, err = self.script[max(matches, key=len)] if matches else self.default
        return subprocess.CompletedProcess(args, code, out, err)


def healthy(**overrides: Reply) -> RecordingRun:
    """A RecordingRun for HEALTHY with replies replaced; keys use ``/`` between arguments."""
    script = dict(HEALTHY)
    for key, reply in overrides.items():
        script[tuple(key.split("/"))] = reply
    return RecordingRun(script=script)


def fake_git_env(tmp: str) -> Dict[str, str]:
    """An env whose PATH holds a (never executed) ``git`` so shutil.which succeeds."""
    bin_dir = os.path.join(tmp, "bin")
    script = fixtures.write(os.path.join(bin_dir, "git"), "#!/bin/sh\nexit 0\n")
    os.chmod(script, 0o755)
    return {"PATH": bin_dir}


def source_for(scope: str, name: str, repo: str) -> SkillSource:
    return SkillSource(scope=scope, name=name, path=os.path.join(repo, scope, name),
                       meta=SkillMeta(name, f"{name} skill"), digest="0" * 64,
                       files=("SKILL.md",), size_bytes=0)


class StubbedRunTests(unittest.TestCase):
    """Behaviour with ``run`` replaced; the only PATH entry is a fake git."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = fixtures.build(self.tmp.name)
        self.env = fake_git_env(self.tmp.name)

    def test_missing_git_not_a_repo_and_missing_dir_messages_and_hints(self) -> None:
        # install_hint: per-platform commands, always the PATH / re-check sentence
        for platform, commands in (("darwin", ("xcode-select --install", "brew install git")),
                                   ("linux", ("sudo apt install git", "sudo dnf install git")),
                                   ("win32", ("winget install Git.Git",))):
            for command in commands:
                self.assertIn(command, git.install_hint(platform), platform)
        for platform in ("darwin", "linux", "win32", "freebsd13", ""):
            hint = git.install_hint(platform)
            self.assertTrue(hint.endswith("press R to re-check"), platform)
            self.assertIn("~/.local/bin", hint)
        self.assertEqual(git.install_hint(), git.install_hint(sys.platform))

        # git itself is missing: nothing on PATH, or the exec fails
        for label, env, stub in (("empty PATH", {"PATH": ""}, RecordingRun()),
                                 ("exec fails", self.env, RecordingRun(raises=FileNotFoundError("git")))):
            with self.subTest(label):
                info = git.detect(self.paths, env=env, run=stub)
                self.assertFalse(info.available)
                self.assertFalse(info.is_repo)
                self.assertEqual(info.message, "git not found on PATH")
                self.assertEqual(info.hint, git.install_hint())
                if label == "empty PATH":
                    self.assertEqual(stub.calls, [])  # nothing is spawned without a git on PATH

        # not a git checkout: git answers, the folder is not a repo
        fixtures.write(os.path.join(self.paths.repo_dir, "README.md"),
                       "Setup:\n\n    git clone https://example.test/me/repo.git\n")
        for label, stub, error_is_none in (
                ("plain folder", healthy(**{"rev-parse/--is-inside-work-tree":
                                           (128, "", "fatal: not a git repository")}), True),
                ("every call fails", RecordingRun(returncode=128, stderr="fatal: not a git repository"), False)):
            with self.subTest(label):
                info = git.detect(self.paths, env=self.env, run=stub)
                self.assertTrue(info.available)
                self.assertFalse(info.is_repo)
                self.assertEqual(info.message, "not a git checkout")
                self.assertIn("git clone https://example.test/me/repo.git", info.hint)
                self.assertIn("not a git checkout", info.hint)
                self.assertEqual(info.error is None, error_is_none)
                self.assertEqual(info.version is None, not error_is_none)
        self.assertIn(f"git clone {git.FALLBACK_CLONE_URL}", git.clone_hint(None))

        # missing repo directory is never reported as missing git
        paths = fixtures.paths_for(self.tmp.name, repo=os.path.join(self.tmp.name, "does-not-exist"))
        stub = RecordingRun(stdout="true")
        info = git.detect(paths, env=self.env, run=stub)
        self.assertTrue(info.available)
        self.assertFalse(info.is_repo)
        self.assertEqual(info.message, f"{MISSING_DIR}: {paths.display(paths.repo_dir)}")
        self.assertEqual(info.error, f"{MISSING_DIR}: {paths.repo_dir}")
        self.assertNotIn("install git", info.hint)
        self.assertIn("--repo", info.hint)
        self.assertIn(f"git clone {git.FALLBACK_CLONE_URL}", info.hint)
        ok, message = git.pull_ff(paths, run=stub, env=self.env)
        self.assertFalse(ok)
        self.assertIn(MISSING_DIR, message)
        self.assertEqual(git.changed_paths(paths, run=stub, env=self.env), ())
        self.assertEqual(git.commits_behind(paths, run=stub, env=self.env), ())
        self.assertEqual(git.remote_changes(paths, {("shared", "alpha"): None}, run=stub,
                                            env=self.env), {})
        fetched = git.fetch(paths, run=stub, env=self.env)
        self.assertTrue(fetched.available)
        self.assertIn("fetch failed", fetched.error or "")
        self.assertIn(paths.repo_dir, fetched.error or "")
        self.assertEqual(stub.calls, [])  # nothing is spawned in a directory that is not there

        # subprocess raises FileNotFoundError(filename=cwd) when chdir fails; only a
        # failed exec of the binary means git is missing
        vanished = RecordingRun(raises=FileNotFoundError(errno.ENOENT, "No such file or directory",
                                                         self.paths.repo_dir))
        info = git.detect(self.paths, env=self.env, run=vanished)
        self.assertTrue(info.available)
        self.assertFalse(info.is_repo)
        self.assertTrue(info.message.startswith(MISSING_DIR), info.message)
        self.assertNotEqual(info.hint, git.install_hint())
        self.assertEqual(len(vanished.calls), 1)

    def test_degraded_states_and_failures_become_data_and_never_escape(self) -> None:
        # healthy baseline, then one degraded reply at a time
        for label, stub, expect in (
                ("behind", healthy(), dict(dirty=False, ahead=0, behind=3, error=None,
                                           message="3 commits behind origin/main", hint="git pull --ff-only")),
                ("dirty", healthy(**{"status": (0, "?? scratch.txt", "")}),
                 dict(dirty=True, behind=3, error=None)),
                ("no upstream", healthy(**{"rev-parse/--abbrev-ref/HEAD": (0, "feature", ""),
                                           "rev-parse/--abbrev-ref/@{u}": (128, "", "fatal: no upstream")}),
                 dict(upstream=None, ahead=0, behind=0, message="no upstream configured",
                      hint="--set-upstream-to=origin/feature")),
                ("ahead and behind", healthy(**{"rev-list": (0, "2\t3", "")}),
                 dict(ahead=2, behind=3, message="(2 commits ahead)")),
                ("unparsable counts", healthy(**{"rev-list": (0, "garbage", "")}), dict(ahead=0, behind=0)),
                ("rev-list fails", healthy(**{"rev-list": (1, "", "bad revision")}),
                 dict(behind=0, error="bad revision")),
                ("status fails", healthy(**{"status": (1, "", "index locked")}),
                 dict(dirty=False, error="index locked"))):
            with self.subTest(label):
                info = git.detect(self.paths, env=self.env, run=stub)
                self.assertTrue(info.is_repo)
                for field, value in expect.items():
                    actual = getattr(info, field)
                    if field in ("message", "hint", "error") and value is not None:
                        self.assertIn(value, actual or "")
                    else:
                        self.assertEqual(actual, value, field)
                if label == "no upstream":  # nothing to compare against: empty answers
                    self.assertEqual(git.changed_paths(self.paths, run=stub, env=self.env), ())
                    self.assertEqual(git.commits_behind(self.paths, run=stub, env=self.env), ())
                    self.assertEqual(git.remote_changes(self.paths, {("shared", "a"): None},
                                                        run=stub, env=self.env), {})

        self.assertEqual(git.remote_changes(self.paths, {("shared", "a"): None}, run=healthy(),
                                            env=self.env), {})  # upstream known, nothing changed

        # timeouts, unexpected exceptions and non-zero exits: error text, empty results
        timeout = subprocess.TimeoutExpired(["git"], 1)
        for label, stub, needle in (("timeout", RecordingRun(raises=timeout), "timed out"),
                                    ("exception", RecordingRun(raises=RuntimeError("boom")), "boom")):
            with self.subTest(label):
                info = git.detect(self.paths, env=self.env, run=stub)
                self.assertTrue(info.available)
                self.assertFalse(info.is_repo)
                self.assertIn(needle, info.error or "")
                self.assertFalse(git.pull_ff(self.paths, run=stub, env=self.env)[0])
                self.assertEqual(git.changed_paths(self.paths, run=stub, env=self.env), ())
                self.assertEqual(git.commits_behind(self.paths, run=stub, env=self.env), ())
                self.assertEqual(git.remote_changes(self.paths, {}, run=stub, env=self.env), {})
        failed = git.fetch(self.paths, env=self.env, run=healthy(
            fetch=(1, "", "could not resolve host")))
        self.assertIn("fetch failed", failed.error or "")
        self.assertIn("could not resolve host", failed.error or "")
        ok, message = git.pull_ff(self.paths, env=self.env, run=RecordingRun(
            returncode=128, stderr="fatal: Not possible to fast-forward"))
        self.assertFalse(ok)
        self.assertIn("fast-forward", message)

        # every call is an argument list run in the repo, never through a shell, without prompts
        stub = healthy()
        git.fetch(self.paths, run=stub, env=self.env)
        self.assertGreater(len(stub.calls), 3)
        for call in stub.calls:
            self.assertIsInstance(call["args"], list)
            self.assertEqual(call["args"][0], "git")
            self.assertEqual(call["cwd"], self.paths.repo_dir)
            self.assertTrue(call["capture_output"])
            self.assertTrue(call["text"])
            self.assertFalse(call["check"])
            self.assertGreater(call["timeout"], 0)
            self.assertEqual(call["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(call["env"]["PATH"], self.env["PATH"])
        self.assertEqual(stub.calls[0]["args"], ["git", "fetch", "--prune"])


# ------------------------------------------------------------------ real git


def run_git(env: Dict[str, str], cwd: str, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                          text=True, check=False, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def isolated_env(root: str) -> Dict[str, str]:
    """An env whose only git config is ``<root>/gitconfig`` (identity, no signing)."""
    config = fixtures.write(os.path.join(root, "gitconfig"),
                            "[user]\n\tname = Installer Test\n\temail = installer@example.test\n"
                            "[commit]\n\tgpgsign = false\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    env.update({
        "HOME": root,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": config,
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env


@unittest.skipUnless(HAVE_GIT, "git is not installed")
class RealGitTests(unittest.TestCase):
    """One bare origin + clone1 (never touched) + clone2 (pushed an edit and two new skills)."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.root = tmp.name
        cls.env = isolated_env(cls.root)
        origin, cls.clone1 = (os.path.join(cls.root, n) for n in ("origin", "clone1"))
        clone2 = os.path.join(cls.root, "clone2")

        def sh(cwd: str, *args: str) -> str:
            return run_git(cls.env, cwd, *args)

        sh(cls.root, "init", "--bare", "--quiet", origin)
        sh(cls.root, "clone", "--quiet", origin, cls.clone1)
        fixtures.make_skill(os.path.join(cls.clone1, "shared", "skills"), "alpha", "Alpha")
        sh(cls.clone1, "add", "-A")
        sh(cls.clone1, "commit", "--quiet", "-m", "add alpha")
        cls.branch = sh(cls.clone1, "rev-parse", "--abbrev-ref", "HEAD")
        sh(cls.clone1, "push", "--quiet", "-u", "origin", cls.branch)
        sh(origin, "symbolic-ref", "HEAD", f"refs/heads/{cls.branch}")

        sh(cls.root, "clone", "--quiet", origin, clone2)
        fixtures.write(os.path.join(clone2, ALPHA_MD),
                       fixtures.FRONTMATTER.format(name="alpha", description="Alpha v2") + "# v2\n")
        sh(clone2, "commit", "--quiet", "-a", "-m", "change alpha")
        for name in ("zeta", CAFE):
            fixtures.make_skill(os.path.join(clone2, "shared", "skills"), name, f"{name} skill")
        sh(clone2, "add", "-A")
        sh(clone2, "commit", "--quiet", "-m", "add zeta and cafe")
        sh(clone2, "push", "--quiet", "origin", cls.branch)
        cls.paths = fixtures.paths_for(cls.root, repo=cls.clone1)

    @classmethod
    def copy_of(cls, repo: str) -> Paths:
        parent = tempfile.mkdtemp(dir=cls.root)
        target = os.path.join(parent, "checkout")
        shutil.copytree(repo, target, symlinks=True)
        return fixtures.paths_for(cls.root, repo=target)

    def test_fetch_commits_behind_remote_changes_and_fast_forward_pull(self) -> None:
        env, branch, behind = self.env, self.branch, 2  # "change alpha", "add zeta and cafe"
        info = git.detect(self.paths, env=env)  # before any fetch
        self.assertTrue(info.available and info.is_repo)
        self.assertIsNone(info.error)
        self.assertRegex(info.version or "", r"^\d+\.\d+")
        self.assertEqual((info.branch, info.upstream), (branch, f"origin/{branch}"))
        self.assertRegex(info.head or "", r"^[0-9a-f]{7,}$")
        self.assertEqual((info.ahead, info.behind, info.dirty), (0, 0, False))
        self.assertIsNone(info.last_fetch)
        self.assertTrue((info.remote_url or "").endswith("origin"))
        self.assertEqual(info.message, f"up to date with origin/{branch} - never fetched")
        self.assertEqual(git.changed_paths(self.paths, env=env), ())
        self.assertEqual(git.commits_behind(self.paths, env=env), ())

        fetched = self.copy_of(self.clone1)
        info = git.fetch(fetched, env=env)
        self.assertIsNone(info.error)
        self.assertEqual((info.ahead, info.behind), (0, behind))
        self.assertIsNotNone(info.last_fetch)
        self.assertEqual(info.message, f"{behind} commits behind origin/{branch} - updates available")
        self.assertIn("git pull --ff-only", info.hint)

        changed = git.changed_paths(fetched, env=env)  # NUL-separated: literal, never C-quoted
        self.assertEqual(len(changed), 3)
        for path in (ALPHA_MD, ZETA_MD, CAFE_MD):
            self.assertIn(path, changed)
        commits = git.commits_behind(fetched, env=env)
        self.assertEqual(len(commits), behind)
        self.assertIn("add zeta and cafe", commits[0])  # newest first
        self.assertIn("change alpha", commits[-1])
        self.assertEqual(len(git.commits_behind(fetched, env=env, limit=1)), 1)

        catalog = {(scope, name): source_for(scope, name, self.clone1)
                   for scope, name in (("shared", "alpha"), ("shared", CAFE), ("shared", "beta"),
                                       ("claude", "alpha"))}
        changes = git.remote_changes(fetched, catalog, env=env)
        self.assertEqual(set(changes), {("shared", "alpha"), ("shared", CAFE)})
        change = changes[("shared", "alpha")]
        self.assertIsInstance(change, RemoteChange)
        self.assertEqual((change.upstream, change.files), (f"origin/{branch}", (ALPHA_MD,)))
        self.assertEqual(len(change.commits), 1)
        self.assertIn("change alpha", change.commits[0])
        self.assertEqual(changes[("shared", CAFE)].files, (CAFE_MD,))
        self.assertEqual(git.skill_prefix("claude", "x"), "claude-code/skills/x/")
        self.assertIsNone(git.skill_prefix("nope", "x"))

        pulled = self.copy_of(fetched.repo_dir)  # fast-forward pull on a fresh copy
        ok, message = git.pull_ff(pulled, env=env)
        self.assertTrue(ok, message)
        self.assertTrue(os.path.isfile(os.path.join(pulled.repo_dir, ZETA_MD)))
        self.assertEqual(git.changed_paths(pulled, env=env), ())
        self.assertEqual(git.commits_behind(pulled, env=env), ())

        diverged = self.copy_of(self.clone1)  # a local commit: pull refuses, nothing is lost
        local = os.path.join(diverged.repo_dir, ALPHA_MD)
        fixtures.write(local, "---\nname: alpha\n---\nlocal\n")
        run_git(env, diverged.repo_dir, "commit", "--quiet", "-am", "local edit")
        ok, message = git.pull_ff(diverged, env=env)
        self.assertFalse(ok)
        self.assertTrue(message)
        with open(local, encoding="utf-8") as fh:
            self.assertIn("local", fh.read())


if __name__ == "__main__":
    unittest.main()
