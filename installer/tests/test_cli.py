"""In-process tests for installer.cli: main([...]) against the fixture repo and home."""

from __future__ import annotations

import contextlib
import glob
import io
import json
import os
import sys
import tempfile
import unittest
from typing import Mapping, Optional, Tuple
from unittest import mock

from installer import cli
from installer.core import capabilities
from installer.tests import fixtures

PATH_ENV_KEYS = ("AGENTS_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "INSTALLER_ASCII", "INSTALLER_DEBUG")
PROBED = ("git", "python", "claude", "codex")


class FakeStdin(io.StringIO):
    """A stdin that can pretend to be a terminal."""

    def __init__(self, text: str = "", tty: bool = False) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def canned_probe(*args, **kwargs):
    """Every probed tool present, without spawning `git --version` and friends."""
    names = kwargs.get("only") or PROBED
    return capabilities.Capabilities(items={
        n: capabilities.Capability(n, True, "1.0", "/usr/bin/" + n, "") for n in names})


def narrow_probe(real_probe):
    """Wrap capabilities.probe so tests only run a handful of cheap probes."""
    def probe(*args, **kwargs):
        kwargs["only"] = PROBED
        return real_probe(*args, **kwargs)
    return probe


class CliTestCase(unittest.TestCase):
    real_probe = False  # True: probe the machine (narrowed to PROBED) instead of the canned result

    def setUp(self) -> None:
        self.fresh()
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in PATH_ENV_KEYS:
            os.environ.pop(key, None)
        probe = mock.patch.object(capabilities, "probe",
                                  narrow_probe(capabilities.probe) if self.real_probe else canned_probe)
        probe.start()
        self.addCleanup(probe.stop)

    def fresh(self) -> None:
        """Build a new fixture repo and home in a new temp dir (the old one is cleaned up at the end)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.paths = fixtures.build(self.root)
        self.home = os.path.join(self.root, "home")

    def run_scenarios(self, *scenarios) -> None:
        """Run each scenario in its own subTest, on a fresh fixture and with the environment restored."""
        cwd = os.getcwd()
        for scenario in scenarios:
            with self.subTest(scenario.__name__), mock.patch.dict(os.environ):
                self.fresh()
                try:
                    scenario()
                finally:
                    os.chdir(cwd)

    # ---------------------------------------------------------------- helpers

    def run_raw(self, *argv: str, stdin: str = "", tty: bool = False,
                env: Optional[Mapping[str, str]] = None) -> Tuple[int, str, str]:
        """Run cli.main with exactly `argv` (no implicit --repo / --home)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sys, "stdin", FakeStdin(stdin, tty)):
            code = cli.main(list(argv), env=env)
        return code, out.getvalue(), err.getvalue()

    def run_cli(self, *argv: str, stdin: str = "", tty: bool = False,
                repo: Optional[str] = None) -> Tuple[int, str, str]:
        full = ["--repo", repo or self.paths.repo_dir, "--home", self.home] + list(argv)
        return self.run_raw(*full, stdin=stdin, tty=tty)

    def agents(self, *parts: str) -> str:
        return os.path.join(self.home, ".agents", *parts)

    def consumer(self, tool: str, *parts: str) -> str:
        return os.path.join(self.home, "." + tool, "skills", *parts)

    def backups(self, pattern: str) -> list:
        return glob.glob(os.path.join(self.home, ".agents", "backups", pattern))

    def json_of(self, *argv: str):
        code, out, err = self.run_cli(*argv)
        self.assertEqual(code, 0, err)
        return json.loads(out)


class ReadOnlyCommandTests(CliTestCase):
    def check_status_text_lists_every_state_and_filters_by_scope(self) -> None:
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        out.encode("ascii")  # stdout has no UTF-8 encoding here, so glyphs fall back to ASCII
        rows = {line.split()[1] + "/" + line.split()[2]: line for line in out.splitlines()
                if line.split()[:1] and line.split()[0] in ("+", "~", "-", "?", "o")}
        self.assertIn("installed", rows["shared/alpha"])
        self.assertIn("claude=ok codex=ok", rows["shared/alpha"])
        self.assertIn("modified", rows["shared/beta"])
        self.assertIn("claude=real-dir codex=broken", rows["shared/beta"])
        self.assertIn("foreign", rows["shared/foreign1"])
        self.assertIn("ignored", rows["claude/synced"])
        self.assertIn("shared: 3 in repo", out)
        code, out, _ = self.run_cli("status", "--scope", "codex")
        self.assertEqual(code, 0)
        self.assertIn("stray.txt", out)
        self.assertNotIn("alpha", out)

    def check_status_json_is_parseable_with_enum_values(self) -> None:
        rows = self.json_of("status", "--json")
        by_key = {(r["scope"], r["name"]): r for r in rows}
        self.assertEqual(by_key[("shared", "alpha")]["state"], "installed")
        self.assertEqual([l["state"] for l in by_key[("shared", "alpha")]["links"]], ["ok", "ok"])
        self.assertEqual(by_key[("codex", "gamma")]["state"], "modified")
        self.assertEqual(by_key[("claude", "ghost")]["state"], "foreign")

    def check_list_shows_the_catalog_only_and_issues_reports_the_problems(self) -> None:
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertNotIn("foreign1", out)
        rows = self.json_of("list", "--json")
        self.assertEqual(sorted(r["scope"] for r in rows if r["name"] == "dup"), ["claude", "shared"])
        self.assertEqual({r["name"]: r["installed"] for r in rows if r["scope"] == "shared"},
                         {"alpha": "yes", "beta": "modified", "dup": "no"})
        code, out, _ = self.run_cli("issues")
        self.assertEqual(code, 0)
        for needle in ("nometa", "badname", "ghost", "stray.txt", "duplicates shared/dup"):
            self.assertIn(needle, out)
        names = {(r["scope"], r["name"]) for r in self.json_of("issues", "--json")["problems"]}
        self.assertIn(("shared", "beta"), names)
        self.assertIn(("claude", "nometa"), names)

    def check_tree_and_show_print_skill_files_and_refuse_paths_outside_the_skill(self) -> None:
        code, out, _ = self.run_cli("tree", "alpha")
        self.assertEqual(code, 0)
        self.assertIn("SKILL.md", out)
        self.assertIn("notes.md", out)
        self.assertIn("shared/alpha", out.splitlines()[0])
        code, out, _ = self.run_cli("show", "alpha")
        self.assertEqual(code, 0)
        self.assertIn("name: alpha", out)
        self.assertEqual(self.run_cli("show", "alpha", "references/notes.md")[:2], (0, "alpha notes\n"))
        self.assertIn("local edit", self.run_cli("show", "beta")[1])  # the installed copy differs
        self.assertEqual(self.run_cli("show", "alpha", "../beta/SKILL.md")[0], 2)
        self.assertEqual(self.run_cli("show", "alpha", "/etc/hosts")[0], 2)
        code, _, err = self.run_cli("show", "alpha", "nope.md")
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)

    def check_updates_on_a_non_checkout_prints_a_banner_and_is_not_a_failure(self) -> None:
        code, out, _ = self.run_cli("updates")
        self.assertEqual(code, 0)
        self.assertTrue(out.strip())
        self.assertEqual(self.run_cli("updates", "--fetch")[0], 0)

    def test_updates_json_on_a_non_checkout_has_the_full_shape_and_no_changes(self) -> None:
        data = self.json_of("updates", "--json")
        self.assertEqual(set(data), {"git", "commits", "changed"})
        self.assertEqual(set(data["git"]), {"message", "hint", "branch", "upstream", "ahead", "behind",
                                            "last_fetch"})
        self.assertTrue(data["git"]["message"])
        self.assertIsNone(data["git"]["upstream"])
        self.assertEqual((data["commits"], data["changed"]), ([], []))

    def test_read_only_commands(self) -> None:
        self.run_scenarios(
            self.check_status_text_lists_every_state_and_filters_by_scope,
            self.check_status_json_is_parseable_with_enum_values,
            self.check_list_shows_the_catalog_only_and_issues_reports_the_problems,
            self.check_tree_and_show_print_skill_files_and_refuse_paths_outside_the_skill,
            self.check_updates_on_a_non_checkout_prints_a_banner_and_is_not_a_failure)


class UsageErrorTests(CliTestCase):
    def check_bad_commands_and_names_exit_2_with_a_reason(self) -> None:
        code, _, err = self.run_cli("frobnicate")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)
        for command in ("install", "update", "retire", "push", "tree", "show"):
            with self.subTest(unknown=command):
                extra = ["--yes"] if command in ("install", "update", "retire", "push") else []
                code, _, err = self.run_cli(command, "nothere", *extra)
                self.assertEqual(code, 2)
                self.assertIn("unknown skill", err)
        for bad in ("../x", "a/b", ".hidden", ".."):
            with self.subTest(invalid=bad):
                code, _, err = self.run_cli("install", bad, "--yes")
                self.assertEqual(code, 2)
                self.assertIn("invalid skill name", err)
        code, _, err = self.run_cli("install", "dup", "--yes")  # in two scopes: ask which
        self.assertEqual(code, 2)
        self.assertIn("--scope shared", err)
        self.assertIn("--scope claude", err)
        self.assertFalse(os.path.exists(self.agents("skills", "dup")))

    def check_help_and_version_exit_0(self) -> None:
        for flag in ("--help", "--version"):
            with self.subTest(flag=flag), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main([flag]), 0)

    def check_mutating_commands_need_yes_without_a_terminal(self) -> None:
        for argv in (("retire", "foreign1"), ("update", "beta"), ("relink",),
                     ("install", "dup", "--scope", "shared"), ("config", "set", "tools.claude", "off")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn("--yes", err)
        self.assertTrue(os.path.isdir(self.agents("skills", "foreign1")))
        self.assertFalse(os.path.exists(self.agents("config.json")))

    def test_usage_errors_exit_2_and_help_exits_0(self) -> None:
        self.run_scenarios(
            self.check_bad_commands_and_names_exit_2_with_a_reason,
            self.check_help_and_version_exit_0,
            self.check_mutating_commands_need_yes_without_a_terminal)


class HomeOptionTests(CliTestCase):
    """--home is a sandbox: exported tool-home variables must not leak through it."""

    def decoy_env(self) -> dict:
        decoy = os.path.join(self.root, "decoy")
        return {"AGENTS_HOME": os.path.join(decoy, "agents"),
                "CLAUDE_CONFIG_DIR": os.path.join(decoy, "claude"),
                "CODEX_HOME": os.path.join(decoy, "codex")}

    def check_home_wins_over_exported_tool_home_variables(self) -> None:
        with mock.patch.dict(os.environ, self.decoy_env()):  # exported in the process
            code, _, err = self.run_cli("install", "dup", "--scope", "shared", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.agents("skills", "dup", "SKILL.md")))
        self.assertTrue(os.path.islink(self.consumer("claude", "dup")))
        self.assertTrue(os.path.islink(self.consumer("codex", "dup")))
        code, _, err = self.run_raw("--repo", self.paths.repo_dir, "--home", self.home,  # passed as env=
                                    "config", "set", "tools.claude", "off", "--yes", env=self.decoy_env())
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.agents("config.json")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "decoy")))

    def check_the_variables_still_apply_without_home(self) -> None:
        env = {"AGENTS_HOME": self.agents(),
               "CLAUDE_CONFIG_DIR": os.path.join(self.home, ".claude"),
               "CODEX_HOME": os.path.join(self.home, ".codex")}
        with mock.patch.dict(os.environ, env):
            code, out, err = self.run_raw("--repo", self.paths.repo_dir, "list", "--json")
        self.assertEqual(code, 0, err)
        rows = json.loads(out)
        self.assertEqual({r["name"]: r["installed"] for r in rows if r["scope"] == "shared"},
                         {"alpha": "yes", "beta": "modified", "dup": "no"})


    # --repo / --home work before the command, after it, and after a nested action.

    LEAVES = (("config", "list"), ("config", "get", "tools.claude"), ("config", "path"),
              ("config", "edit"), ("config", "set", "tools.claude", "off"),
              ("config", "reset", "tools.claude"), ("extras", "list"), ("extras", "show", "x"),
              ("extras", "install", "x"))

    def check_every_nested_action_parser_accepts_repo_and_home_without_overwriting_earlier_ones(self) -> None:
        parser = cli.build_parser()
        for leaf in self.LEAVES:
            with self.subTest(leaf=leaf):
                args = parser.parse_args(list(leaf) + ["--home", "H", "--repo", "R"])
                self.assertEqual((args.home, args.repo), ("H", "R"))
        for argv in (["--home", "H", "--repo", "R", "config", "get", "tools.claude"],
                     ["config", "--home", "H", "--repo", "R", "get", "tools.claude"],
                     ["config", "get", "--home", "H", "--repo", "R", "tools.claude"]):
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertEqual((args.home, args.repo), ("H", "R"))

    def check_commands_run_with_the_options_after_the_command_or_action(self) -> None:
        for argv in (("status",), ("config", "get", "tools.claude"), ("config", "list", "--json"),
                     ("config", "path"), ("extras", "list", "--json"), ("workflow", "list")):
            with self.subTest(argv=argv):
                code, _, err = self.run_raw(*argv, "--repo", self.paths.repo_dir, "--home", self.home)
                self.assertEqual(code, 0, err)
        code, out, _ = self.run_raw("config", "path", "--home", self.home)
        self.assertEqual(code, 0)
        self.assertIn(os.path.join(self.home, ".agents"), out)

    def test_global_options_and_the_home_sandbox(self) -> None:
        self.run_scenarios(
            self.check_every_nested_action_parser_accepts_repo_and_home_without_overwriting_earlier_ones,
            self.check_commands_run_with_the_options_after_the_command_or_action,
            self.check_home_wins_over_exported_tool_home_variables,
            self.check_the_variables_still_apply_without_home)


class InstallUpdateRetireTests(CliTestCase):
    def check_install_writes_nothing_on_a_dry_run_or_a_declined_prompt(self) -> None:
        code, out, _ = self.run_cli("install", "dup", "--scope", "shared", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Plan (6 step(s))", out)
        self.assertIn("Dry run only", out)
        self.assertFalse(os.path.exists(self.agents("skills", "dup")))
        code, out, _ = self.run_cli("install", "dup", "--scope", "shared", stdin="n\n", tty=True)
        self.assertEqual(code, 1)
        self.assertIn("Proceed? [y/N]", out)
        self.assertIn("Aborted.", out)
        self.assertFalse(os.path.exists(self.agents("skills", "dup")))

    def check_install_with_scope_creates_the_copy_and_both_links_after_a_yes_at_the_prompt(self) -> None:
        code, out, err = self.run_cli("install", "dup", "--scope", "shared", stdin="y\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(self.agents("skills", "dup", "SKILL.md")))
        for tool in ("claude", "codex"):
            link = self.consumer(tool, "dup")
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.path.realpath(link), os.path.realpath(self.agents("skills", "dup")))
        self.assertIn("copytree", out)
        self.assertIn("Done.", out)

    def check_install_skips_an_installed_skill_and_gives_a_platform_skill_no_links(self) -> None:
        before = sorted(os.listdir(self.agents("skills")))
        code, out, _ = self.run_cli("install", "alpha", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("skipped - already installed", out)
        self.assertIn("Nothing to do.", out)
        self.assertEqual(sorted(os.listdir(self.agents("skills"))), before)
        code, _, err = self.run_cli("install", "nometa", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(self.consumer("claude", "nometa")))
        self.assertFalse(os.path.islink(self.consumer("claude", "nometa")))

    def check_update_skips_an_unmodified_skill_and_backs_up_a_modified_one_before_restoring_it(self) -> None:
        code, out, _ = self.run_cli("update", "alpha", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("skipped", out)
        self.assertEqual(self.backups("installer-*"), [])
        code, out, err = self.run_cli("update", "beta", "--yes")
        self.assertEqual(code, 0, err)
        saved = self.backups("installer-*/shared/beta/SKILL.md")
        self.assertEqual(len(saved), 1)
        with open(saved[0], encoding="utf-8") as fh:
            self.assertIn("local edit", fh.read())
        with open(self.agents("skills", "beta", "SKILL.md"), encoding="utf-8") as fh:
            self.assertNotIn("local edit", fh.read())
        self.assertIn("Backups went under:", out)

    def check_retire_moves_the_skill_and_its_links_under_the_retired_skills_root(self) -> None:
        code, out, err = self.run_cli("retire", "foreign1", "--yes")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.exists(self.agents("skills", "foreign1")))
        self.assertEqual(len(self.backups("retired-skills-*/shared/foreign1/SKILL.md")), 1)
        self.assertIn("Backups went under:", out)
        code, _, err = self.run_cli("retire", "alpha", "--yes")
        self.assertEqual(code, 0, err)
        for tool in ("claude", "codex"):
            self.assertFalse(os.path.lexists(self.consumer(tool, "alpha")))
            self.assertEqual(len(self.backups(f"retired-skills-*/{tool}/alpha")), 1)

    def check_retire_consumers_only_keeps_the_shared_copy(self) -> None:
        code, _, err = self.run_cli("retire", "alpha", "--consumers-only", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isdir(self.agents("skills", "alpha")))
        self.assertFalse(os.path.lexists(self.consumer("claude", "alpha")))

    def check_relink_by_name_touches_only_that_skill_and_a_full_relink_fixes_broken_links(self) -> None:
        code, _, err = self.run_cli("relink", "foreign1", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.islink(self.consumer("claude", "foreign1")))
        self.assertEqual(os.readlink(self.consumer("codex", "beta")), "/nonexistent/target/beta")
        ghost = self.consumer("claude", "ghost")
        ghost_target = os.readlink(ghost)
        code, out, err = self.run_cli("relink", "--yes")
        self.assertEqual(code, 0, err)
        fixed = self.consumer("codex", "beta")
        self.assertTrue(os.path.islink(fixed))
        self.assertEqual(os.path.realpath(fixed), os.path.realpath(self.agents("skills", "beta")))
        self.assertEqual(os.readlink(ghost), ghost_target)  # foreign entries are left alone
        self.assertTrue(os.path.isdir(self.consumer("claude", "beta")))
        self.assertFalse(os.path.islink(self.consumer("claude", "beta")))
        self.assertIn("claude is real-dir; not changed", out)
        self.assertEqual(len(self.backups("installer-*/codex/beta")), 1)

    def check_push_copies_a_foreign_skill_into_the_repo_and_backs_up_an_existing_repo_copy(self) -> None:
        fixtures.make_skill(self.agents("skills"), "freshy", "A brand new skill")
        code, _, err = self.run_cli("push", "freshy", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(self.paths.repo_dir, "shared", "skills", "freshy",
                                                    "SKILL.md")))
        self.assertTrue(os.path.isdir(self.agents("skills", "freshy")))
        code, _, err = self.run_cli("push", "beta", "--yes")
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.paths.repo_dir, "shared", "skills", "beta", "SKILL.md"),
                  encoding="utf-8") as fh:
            self.assertIn("local edit", fh.read())
        self.assertEqual(len(self.backups("installer-*/repo/shared/beta")), 1)

    def test_install_update_and_relink(self) -> None:
        self.run_scenarios(
            self.check_install_writes_nothing_on_a_dry_run_or_a_declined_prompt,
            self.check_install_with_scope_creates_the_copy_and_both_links_after_a_yes_at_the_prompt,
            self.check_install_skips_an_installed_skill_and_gives_a_platform_skill_no_links,
            self.check_update_skips_an_unmodified_skill_and_backs_up_a_modified_one_before_restoring_it,
            self.check_relink_by_name_touches_only_that_skill_and_a_full_relink_fixes_broken_links)

    def test_retire_and_push(self) -> None:
        self.run_scenarios(
            self.check_retire_moves_the_skill_and_its_links_under_the_retired_skills_root,
            self.check_retire_consumers_only_keeps_the_shared_copy,
            self.check_push_copies_a_foreign_skill_into_the_repo_and_backs_up_an_existing_repo_copy)


if __name__ == "__main__":
    unittest.main()
