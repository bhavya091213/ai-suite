"""Tests for installer.cli: extras, apply, tui, pull, git-backed updates and helpers."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from installer import cli, cli_io
from installer.core import git
from installer.core.types import GitInfo
from installer.tests import fixtures
from installer.tests.test_cli import CliTestCase, FakeStdin


class ExtrasCommandTests(CliTestCase):
    def write_catalog(self, command: str) -> None:
        catalog = {"extras": {"demo": {
            "title": "Demo tool", "category": "test", "url": "https://example.invalid/demo",
            "tools": ["claude", "codex"], "install": [command],
            "after_install": {"claude": "run it in a project"},
            "detect": {"any_paths": ["~/.claude/skills/demo-extra"]},
        }}}
        fixtures.write(os.path.join(self.paths.repo_dir, "shared", "extras.json"), json.dumps(catalog))

    def check_list_and_show_work_with_and_without_a_catalog(self) -> None:
        code, out, _ = self.run_cli("extras", "list")
        self.assertEqual(code, 0)
        self.assertIn("No extras defined", out)
        self.assertEqual(self.json_of("extras", "list", "--json"), [])
        self.write_catalog("true")
        code, out, _ = self.run_cli("extras", "list")
        self.assertEqual(code, 0)
        self.assertIn("demo", out)
        rows = self.json_of("extras", "list", "--json")
        self.assertEqual(rows[0]["installed"], {"claude": False, "codex": None})
        code, out, _ = self.run_cli("extras", "show", "demo")
        self.assertEqual(code, 0)
        self.assertIn("install: true", out)
        self.assertEqual(self.run_cli("extras", "show", "nothere")[0], 2)

    def check_install_warns_and_asks_first_then_runs_the_shared_command_once_for_all_tools(self) -> None:
        marker = os.path.join(self.root, "ran.txt")
        self.write_catalog(f'{sys.executable} -c "open(r\'{marker}\', \'a\').write(\'x\')"')
        self.run_cli("config", "set", "tools.claude", "on", "--yes")  # codex stays on auto: detected
        code, out, _ = self.run_cli("extras", "install", "demo")
        self.assertEqual(code, 2, out)
        self.assertIn("third-party code", out)
        code, out, _ = self.run_cli("extras", "install", "demo", "--tool", "claude", stdin="n\n", tty=True)
        self.assertEqual(code, 1)
        self.assertIn("Run? [y/N]", out)
        self.assertFalse(os.path.exists(marker))
        code, out, err = self.run_cli("extras", "install", "demo", "--yes")
        self.assertEqual(code, 0, err)
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "x")  # one shared command, deduplicated across tools
        self.assertIn("next (claude): run it in a project", out)

    def check_install_dry_run_runs_nothing_and_failures_are_reported(self) -> None:
        marker = os.path.join(self.root, "ran.txt")
        self.write_catalog(f'{sys.executable} -c "open(r\'{marker}\', \'w\').close()"')
        code, out, _ = self.run_cli("extras", "install", "demo", "--tool", "claude", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Dry run only", out)
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(self.run_cli("extras", "install", "nothere", "--yes")[0], 2)
        self.write_catalog(f'{sys.executable} -c "raise SystemExit(3)"')
        code, _, err = self.run_cli("extras", "install", "demo", "--tool", "claude", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("status 3", err)
        self.write_catalog("definitely-not-a-real-binary-xyz --flag")
        code, _, err = self.run_cli("extras", "install", "demo", "--tool", "claude", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("cannot run", err)
        solo = {"extras": {"solo": {"title": "Solo", "category": "t", "url": "https://example.invalid",
                                    "tools": ["codex"], "install": ["true"]}}}
        fixtures.write(os.path.join(self.paths.repo_dir, "shared", "extras.json"), json.dumps(solo))
        self.assertEqual(self.run_cli("extras", "install", "solo", "--tool", "claude", "--yes")[0], 2)

    def test_extras_commands(self) -> None:
        self.run_scenarios(
            self.check_list_and_show_work_with_and_without_a_catalog,
            self.check_install_warns_and_asks_first_then_runs_the_shared_command_once_for_all_tools,
            self.check_install_dry_run_runs_nothing_and_failures_are_reported)


class ApplyAndTuiTests(CliTestCase):
    def write_script(self, body: str, mode: int = 0o755) -> str:
        path = fixtures.write(os.path.join(self.paths.repo_dir, "install.sh"), "#!/bin/sh\n" + body)
        os.chmod(path, mode)
        return path

    def check_apply_runs_the_script_streams_its_output_and_passes_dry_run_through(self) -> None:
        self.write_script('echo "install.sh $*"\n')
        code, out, err = self.run_cli("apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("install.sh --headless --auto", out)
        self.assertNotIn("--dry-run\n", out.split("Plan:")[1].split("\n", 1)[1])
        code, out, _ = self.run_cli("apply", "--dry-run")  # no prompt, flag forwarded
        self.assertEqual(code, 0)
        self.assertIn("install.sh --headless --auto --dry-run", out)

    def check_apply_reports_a_failing_script_even_without_the_executable_bit(self) -> None:
        self.write_script("echo boom\nexit 7\n", mode=0o644)  # falls back to running it through bash
        code, out, _ = self.run_cli("apply", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("boom", out)
        self.assertIn("exited with status 7", out)

    def check_apply_needs_yes_without_a_terminal_and_fails_without_a_script(self) -> None:
        code, _, err = self.run_cli("apply", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)
        marker = os.path.join(self.root, "ran.txt")
        self.write_script(f'touch "{marker}"\n')
        code, out, err = self.run_cli("apply")
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertIn("Plan:", out)
        self.assertFalse(os.path.exists(marker))

    def check_tui_runs_the_lazily_imported_entry_point_and_a_bare_invocation_picks_by_terminal(self) -> None:
        calls = []
        stub = types.SimpleNamespace(run=lambda paths, start_screen="overview": calls.append(paths) or 0)
        with mock.patch.dict(sys.modules, {"installer.tui": stub}):
            code, _, _ = self.run_cli("tui")
            self.assertEqual(code, 0)
            self.assertEqual(calls[0].repo_dir, self.paths.repo_dir)
            code, out, _ = self.run_cli(tty=True)  # no command on a terminal: the TUI
            self.assertEqual((code, out, len(calls)), (0, "", 2))
        code, out, _ = self.run_cli()  # no command and no terminal: status
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)

    def check_tui_failures_print_why_and_exit_1(self) -> None:
        def boom(paths, start_screen="overview"):
            raise RuntimeError("no terminal")
        for stub, message in ((types.SimpleNamespace(), "cannot start the interactive installer"),
                              (types.SimpleNamespace(run=boom), "no terminal")):
            with self.subTest(message=message), mock.patch.dict(sys.modules, {"installer.tui": stub}):
                code, _, err = self.run_cli("tui")
                self.assertEqual(code, 1)
                self.assertIn(message, err)

    def test_apply_command(self) -> None:
        self.run_scenarios(
            self.check_apply_runs_the_script_streams_its_output_and_passes_dry_run_through,
            self.check_apply_reports_a_failing_script_even_without_the_executable_bit,
            self.check_apply_needs_yes_without_a_terminal_and_fails_without_a_script)

    def test_tui_command(self) -> None:
        self.run_scenarios(
            self.check_tui_runs_the_lazily_imported_entry_point_and_a_bare_invocation_picks_by_terminal,
            self.check_tui_failures_print_why_and_exit_1)


class PullTests(CliTestCase):
    @staticmethod
    def checkout() -> GitInfo:
        return GitInfo(available=True, version="2", is_repo=True, branch="main", head="abc",
                       upstream="origin/main", ahead=0, behind=1, dirty=False, last_fetch=None,
                       remote_url=None, message="1 commit behind origin/main")

    def check_pull_on_a_non_checkout_fails_with_the_reason(self) -> None:
        code, _, err = self.run_cli("pull", "--yes")
        self.assertEqual(code, 1)
        self.assertTrue(err.strip())

    def check_pull_needs_yes_asks_before_running_and_dry_run_never_pulls(self) -> None:
        with mock.patch.object(git, "detect", return_value=self.checkout()), \
                mock.patch.object(git, "pull_ff", return_value=(True, "Fast-forward")) as pull:
            code, _, err = self.run_cli("pull")
            self.assertEqual((code, pull.call_count), (2, 0))
            self.assertIn("--yes", err)
            self.assertEqual((self.run_cli("pull", "--dry-run")[0], pull.call_count), (0, 0))
            self.assertEqual((self.run_cli("pull", stdin="n\n", tty=True)[0], pull.call_count), (1, 0))
            code, out, _ = self.run_cli("pull", "--yes")
            self.assertEqual((code, pull.call_count), (0, 1))
            self.assertIn("Fast-forward", out)

    def test_pull_command(self) -> None:
        self.run_scenarios(
            self.check_pull_on_a_non_checkout_fails_with_the_reason,
            self.check_pull_needs_yes_asks_before_running_and_dry_run_never_pulls)


def run_git(cwd: str, *args: str) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    subprocess.run(["git"] + list(args), cwd=cwd, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitBackedTests(CliTestCase):
    """`updates`, `status` and `pull` against a real clone whose origin gained a commit.

    The origin, bare repo and clone are built once; tests only read the clone, or pull in a copy."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        origin = fixtures.make_repo(os.path.join(tmp.name, "origin"))
        run_git(origin, "init", "-q", "-b", "main")
        run_git(origin, "add", "-A")
        run_git(origin, "commit", "-q", "-m", "initial")
        bare = os.path.join(tmp.name, "bare.git")
        run_git(tmp.name, "clone", "-q", "--bare", origin, bare)
        cls.clone = os.path.join(tmp.name, "clone")
        run_git(tmp.name, "clone", "-q", bare, cls.clone)
        fixtures.write(os.path.join(origin, "shared", "skills", "alpha", "SKILL.md"),
                       fixtures.FRONTMATTER.format(name="alpha", description="Alpha v2") + "# v2\n")
        run_git(origin, "commit", "-q", "-am", "alpha v2")
        run_git(origin, "push", "-q", bare, "HEAD:main")

    def test_a_clone_behind_its_origin_reports_the_commit_and_the_changed_skill(self) -> None:
        code, out, err = self.run_cli("updates", "--fetch", repo=self.clone)
        self.assertEqual(code, 0, err)
        with self.subTest("text report"):
            self.assertIn("Commits behind origin/main (1):", out)
            self.assertIn("alpha v2", out)
            self.assertIn("shared/alpha  (1 file(s))", out)
        with self.subTest("updates --json"):
            code, out, err = self.run_cli("updates", "--json", repo=self.clone)
            self.assertEqual(code, 0, err)
            data = json.loads(out)  # stdout is pure JSON
            banner = data["git"]
            self.assertEqual((banner["branch"], banner["upstream"], banner["ahead"], banner["behind"]),
                             ("main", "origin/main", 0, 1))
            self.assertIsInstance(banner["last_fetch"], float)
            self.assertTrue(banner["message"])
            self.assertEqual(len(data["commits"]), 1)
            self.assertRegex(data["commits"][0], r"^[0-9a-f]{7,} alpha v2$")
            self.assertEqual(data["changed"], [
                {"scope": "shared", "name": "alpha", "files": ["shared/skills/alpha/SKILL.md"]}])
        with self.subTest("status marks the skill with upstream changes"):
            code, out, _ = self.run_cli("status", "--scope", "shared", repo=self.clone)
            self.assertEqual(code, 0)
            rows = {line.split()[2]: line for line in out.splitlines() if line.strip().startswith(("+", "~"))}
            self.assertIn("1 file(s) upstream", rows["alpha"])
            self.assertNotIn("upstream", rows["beta"])

    def test_pull_fast_forwards_a_copy_of_the_clone_after_confirmation(self) -> None:
        copy = os.path.join(self.root, "clone-copy")
        shutil.copytree(self.clone, copy, symlinks=True)
        code, out, err = self.run_cli("pull", "--yes", repo=copy)
        self.assertEqual(code, 0, err + out)
        with open(os.path.join(copy, "shared", "skills", "alpha", "SKILL.md"), encoding="utf-8") as fh:
            self.assertIn("# v2", fh.read())


class HelperTests(unittest.TestCase):
    def check_to_jsonable_handles_dataclasses_enums_and_read_only_mappings(self) -> None:
        from types import MappingProxyType
        from installer.core.types import SkillMeta, State
        meta = SkillMeta("n", "d", MappingProxyType({"k": "v"}))
        data = cli_io.to_jsonable({"meta": meta, "state": State.MODIFIED, "t": (1, 2), "none": None})
        self.assertEqual(data, {"meta": {"name": "n", "description": "d", "fields": {"k": "v"}},
                                "state": "modified", "t": [1, 2], "none": None})
        json.dumps(data)

    def check_table_truncate_and_glyph_helpers(self) -> None:
        self.assertEqual(cli_io.format_table(("A", "BB"), [("xxx", "y"), ("z", "")]),
                         ["A    BB", "xxx  y", "z"])
        self.assertEqual(cli_io.truncate("short", 10), "short")
        self.assertEqual(cli_io.truncate("a" * 20, 10), "a" * 7 + "...")
        utf8, ascii_out = mock.Mock(encoding="UTF-8"), mock.Mock(encoding="ascii")
        with mock.patch.object(sys, "stdout", utf8):  # unicode glyphs only for a UTF-8 stdout
            self.assertEqual(cli_io.glyph("installed"), "\u2713")
            with mock.patch.dict(os.environ, {"INSTALLER_ASCII": "1"}):
                self.assertEqual(cli_io.glyph("installed"), "+")
        with mock.patch.object(sys, "stdout", ascii_out):
            self.assertEqual(cli_io.glyph("installed"), "+")
            self.assertEqual(cli_io.glyph("nonexistent"), "?")

    def check_unexpected_exceptions_are_reported_not_raised(self) -> None:
        err = io.StringIO()
        with mock.patch("installer.cli_commands.load_world", side_effect=RuntimeError("kaboom")), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(sys, "stdin", FakeStdin()):
            code = cli.main(["status"])
        self.assertEqual(code, 1)
        self.assertIn("RuntimeError: kaboom", err.getvalue())

    def test_cli_io_helpers_and_error_reporting(self) -> None:
        for check in (self.check_to_jsonable_handles_dataclasses_enums_and_read_only_mappings,
                      self.check_table_truncate_and_glyph_helpers,
                      self.check_unexpected_exceptions_are_reported_not_raised):
            with self.subTest(check.__name__):
                check()


if __name__ == "__main__":
    unittest.main()
