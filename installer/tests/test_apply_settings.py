"""Tests for installer.core.apply_settings: planning, applying and the pair of helper rules."""

from __future__ import annotations

import contextlib
import difflib
import glob
import json
import os
import re
import shutil
import stat
import tempfile
import unittest
from typing import Any, List, Mapping, Optional, Tuple
from unittest import mock

from installer.core import apply_settings, codex_config
from installer.core.paths import Paths
from installer.tests import fixtures
from installer.tests.settings_support import (
    EXAMPLE_TOML, SAMPLE_SETTINGS, dump, make_config, read,
)

CODEX_ON = {"profile": {"codex": True}}
CODEX_OFF = {"profile": {"codex": False}}
TOML_KEY_LINE = re.compile(r"^(model|max_threads|max_depth)\s*=")
HAS_TOMLLIB = codex_config.check("a = =") is not None


def without_env(text: str) -> List[str]:
    """Every line outside the top-level "env" object of a 2-space-indented settings document."""
    kept, skipping = [], False
    for line in text.splitlines():
        if line.startswith('  "env"'):
            skipping = True
        elif skipping:
            skipping = not line.startswith("  }")
        else:
            kept.append(line)
    return kept


def changed_lines(old: str, new: str) -> Tuple[List[str], List[str]]:
    """(old lines, new lines) that differ between two texts."""
    a, b = old.splitlines(), new.splitlines()
    removed: List[str] = []
    added: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            removed += a[i1:i2]
            added += b[j1:j2]
    return removed, added


class SettingsFiles(unittest.TestCase):
    """A temp home with ~/.claude/settings.json and ~/.codex/config.toml (the repo's example)."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.home = os.path.join(self.root, "home")
        self.paths: Paths = fixtures.paths_for(self.root)
        self.settings_path = os.path.join(self.paths.claude_home, "settings.json")
        self.toml_path = os.path.join(self.paths.codex_home, "config.toml")
        self.backup_root = os.path.join(self.root, "backups", "run")
        os.makedirs(self.paths.claude_home)
        os.makedirs(self.paths.codex_home)

    def put_settings(self, obj: Optional[Mapping[str, Any]] = None, indent: int = 2) -> str:
        text = dump(SAMPLE_SETTINGS if obj is None else obj, indent)
        fixtures.write(self.settings_path, text)
        return text

    def put_toml(self) -> str:
        shutil.copyfile(EXAMPLE_TOML, self.toml_path)
        return read(self.toml_path)

    def plan(self, values: Optional[Mapping[str, Any]] = None, context: Mapping = CODEX_ON):
        return apply_settings.plan(make_config(values), context, self.paths)

    def paths_of(self, plan: apply_settings.SettingsPlan) -> List[str]:
        return [os.path.basename(change[0]) for change in plan.changes]

    @staticmethod
    def parser(available: bool):
        """A context in which tomllib is (or, as on Python 3.9 / 3.10, is not) there to validate TOML."""
        return contextlib.nullcontext() if available else mock.patch.object(codex_config, "check", return_value=None)



class PlanClaudeTests(SettingsFiles):
    def test_the_env_block_is_added_edited_or_created_without_reformatting(self) -> None:
        old = self.put_settings()
        result = self.plan()
        self.assertEqual((self.paths_of(result), result.problems), (["settings.json"], ()))
        path, before, after = result.changes[0]
        self.assertEqual((path, before), (self.settings_path, old))
        env = json.loads(after)["env"]
        self.assertEqual((env["ECC_HOOK_PROFILE"], env["ANTHROPIC_BASE_URL"]), ("standard", "http://127.0.0.1:8787"))
        self.assertNotIn("ECC_DISABLED_HOOKS", env)
        self.assertEqual(without_env(old), without_env(after))

        env = dict(SAMPLE_SETTINGS["env"], ECC_HOOK_PROFILE="standard")  # a changed value edits only its line
        old = self.put_settings(dict(SAMPLE_SETTINGS, env=env))
        _, _, after = self.plan({"guardrails.hook_profile": "strict"}).changes[0]
        self.assertEqual(changed_lines(old, after),
                         (['    "ECC_HOOK_PROFILE": "standard"'], ['    "ECC_HOOK_PROFILE": "strict"']))

        self.put_settings(dict(SAMPLE_SETTINGS, env=env), indent=4)  # already matching: not reformatted
        self.assertEqual(self.plan(), apply_settings.SettingsPlan((), ()))

        bare = {k: v for k, v in SAMPLE_SETTINGS.items() if k != "env"}  # no env: one is added last
        self.put_settings(bare)
        _, _, after = self.plan({"guardrails.disabled_hooks": ["a:b"]}).changes[0]
        data = json.loads(after)
        self.assertEqual(list(data), list(bare) + ["env"])
        self.assertEqual(data["env"], {"ECC_HOOK_PROFILE": "standard", "ECC_DISABLED_HOOKS": "a:b"})

class PlanCodexTests(SettingsFiles):
    def test_model_and_agent_limits_reach_the_toml_keeping_line_endings(self) -> None:
        old = self.put_toml()
        self.assertEqual(self.plan(), apply_settings.SettingsPlan((), ()))  # the example is the default config
        values = {"subagents.codex.model": "gpt-test", "subagents.codex.max_threads": 3,
                  "subagents.codex.max_depth": 2}
        result = self.plan(values)
        self.assertEqual(self.paths_of(result), ["config.toml"])
        change = result.changes[0]
        self.assertEqual(change[1], old)
        removed, added = changed_lines(old, change[2])
        self.assertEqual(sorted(removed), ['max_depth = 1', 'max_threads = 6', 'model = "gpt-5.6-sol"'])
        self.assertEqual(sorted(added), ['max_depth = 2', 'max_threads = 3', 'model = "gpt-test"'])
        self.assertTrue(all(TOML_KEY_LINE.match(line) for line in removed))
        self.assertIsNone(codex_config.check(change[2]))
        lines = apply_settings.diff_lines(change, "~/.codex/config.toml")
        self.assertIn("-max_depth = 1", lines)
        self.assertIn("+max_depth = 2", lines)
        self.assertTrue(lines[0].startswith("--- ~/.codex/config.toml"))

        with open(self.toml_path, "wb") as handle:
            handle.write(old.replace("\n", "\r\n").encode("utf-8"))
        after = self.plan({"subagents.codex.max_threads": 4}).changes[0][2]
        self.assertEqual(after.count("\n"), after.count("\r\n"))
        self.assertIn("max_threads = 4\r\n", after)

class PlanSkipDefaultsTests(SettingsFiles):
    """plan(..., skip_defaults=True) pushes only the values that differ from the documented defaults."""

    HAND_TOML = ('model = "mine"\n\n[agents]\nmax_threads = 9  # mine\nmax_depth = 3\n\n'
                 '[agents.reviewer]\nmax_depth = 7\n')

    def changed(self, values: Optional[Mapping[str, Any]] = None, context: Mapping = CODEX_ON):
        return apply_settings.plan(make_config(values), context, self.paths, skip_defaults=True)

    def hand_set_settings(self) -> None:
        env = dict(SAMPLE_SETTINGS["env"], ECC_HOOK_PROFILE="strict", ECC_DISABLED_HOOKS="a:b")
        self.put_settings(dict(SAMPLE_SETTINGS, env=env))

    def test_only_the_values_that_differ_from_the_defaults_are_pushed(self) -> None:
        for check in (self.check_a_config_of_defaults_pushes_nothing, self.check_only_the_changed_settings_reach_settings_json,
                      self.check_only_the_changed_settings_reach_the_toml):
            with self.subTest(check.__name__):
                check()

    def check_a_config_of_defaults_pushes_nothing(self) -> None:
        self.hand_set_settings()
        fixtures.write(self.toml_path, self.HAND_TOML)
        self.assertEqual(self.changed(), apply_settings.SettingsPlan((), ()))
        self.assertEqual(sorted(self.paths_of(self.plan())), ["config.toml", "settings.json"])  # the full plan would
        self.put_settings({k: v for k, v in SAMPLE_SETTINGS.items() if k != "env"})  # no env block is invented
        self.assertEqual(self.changed(), apply_settings.SettingsPlan((), ()))

    def check_only_the_changed_settings_reach_settings_json(self) -> None:
        self.hand_set_settings()
        env = json.loads(self.changed({"guardrails.hook_profile": "minimal"}).changes[0][2])["env"]
        self.assertEqual((env["ECC_HOOK_PROFILE"], env["ECC_DISABLED_HOOKS"]), ("minimal", "a:b"))
        env = json.loads(self.changed({"guardrails.disabled_hooks": ["c:d"]}).changes[0][2])["env"]
        self.assertEqual((env["ECC_HOOK_PROFILE"], env["ECC_DISABLED_HOOKS"]), ("strict", "c:d"))
        result = apply_settings.plan({"guardrails": {"hook_profile": "loud"}}, CODEX_OFF, self.paths,
                                     skip_defaults=True)  # an invalid value is still reported
        self.assertEqual((result.changes, result.problems[0][0]), ((), "skip"))
        self.assertIn("hook_profile", result.problems[0][1])

    def check_only_the_changed_settings_reach_the_toml(self) -> None:
        fixtures.write(self.toml_path, self.HAND_TOML)
        _, before, after = self.changed({"subagents.codex.model": "gpt-test"}).changes[0]
        self.assertEqual(after, before.replace('model = "mine"', 'model = "gpt-test"'))
        _, before, after = self.changed({"subagents.codex.max_threads": 2}).changes[0]
        self.assertEqual(after, before.replace("max_threads = 9", "max_threads = 2"))  # not the reviewer's 7
        _, before, after = self.changed({"subagents.codex.max_depth": 2}).changes[0]
        reviewer = "\n\n[agents.reviewer]"
        self.assertEqual(after, before.replace("max_depth = 3" + reviewer, "max_depth = 2" + reviewer))
        if HAS_TOMLLIB:
            self.assertIsNone(codex_config.check(after))

class ApplyTests(SettingsFiles):
    def planned(self, values: Optional[Mapping[str, Any]] = None):
        return self.plan(values or {"guardrails.hook_profile": "strict"}).changes

    def assert_refused(self, changes, fragment: str, backup_root: Optional[str] = None) -> None:
        """apply() reports a failure, names the reason, and leaves the file and the backup root untouched."""
        path = changes[0][0]
        before = read(path)
        outcome = apply_settings.apply(changes, self.backup_root if backup_root is None else backup_root)[0]
        self.assertFalse(outcome.ok)
        self.assertIn(fragment, outcome.message)
        self.assertEqual(read(path), before)
        self.assertFalse(os.path.exists(self.backup_root))

    def test_apply_backs_up_before_replacing_refuses_what_it_cannot_verify_and_never_deletes(self) -> None:
        for check in (self.check_apply_refuses_what_it_cannot_verify, self.check_apply_writes_the_new_text_and_backs_up_the_old,
                      self.check_a_second_backup_never_overwrites_the_first, self.check_a_failed_replace_keeps_the_temp_file):
            with self.subTest(check.__name__):
                self.backup_root = os.path.join(self.root, "backups", check.__name__)  # a fresh root per case
                check()

    def check_apply_writes_the_new_text_and_backs_up_the_old(self) -> None:
        old = self.put_settings()
        os.chmod(self.settings_path, 0o600)
        changes = self.planned()
        outcome = apply_settings.apply(changes, self.backup_root, home=self.home)[0]
        self.assertEqual((outcome.ok, outcome.message), (True, "updated"))
        self.assertEqual(read(self.settings_path), changes[0][2])
        backup = os.path.join(self.backup_root, ".claude", "settings.json")
        self.assertEqual((outcome.backup, read(backup)), (backup, old))
        self.assertEqual(without_env(old), without_env(read(self.settings_path)))
        self.assertEqual(stat.S_IMODE(os.stat(self.settings_path).st_mode), 0o600)  # mode kept
        self.assertEqual(os.listdir(self.paths.claude_home), ["settings.json"])  # no temp file left

        old = self.put_toml()  # the toml: only the edited lines change; no home given
        changes = self.plan({"subagents.codex.model": "gpt-test", "subagents.codex.max_threads": 2}).changes
        self.assertTrue(apply_settings.apply(changes, self.backup_root + "2")[0].ok)
        removed, added = changed_lines(old, read(self.toml_path))
        self.assertEqual((len(removed), len(added)), (2, 2))
        self.assertTrue(all(TOML_KEY_LINE.match(line) for line in removed + added))
        self.assertEqual(read(os.path.join(self.backup_root + "2", ".codex", "config.toml")), old)

    def check_apply_refuses_what_it_cannot_verify(self) -> None:
        old_json, old_toml = self.put_settings(), self.put_toml()
        stale_plan = self.planned()
        refusals = [("invalid JSON", ((self.settings_path, old_json, '{"env": '),), "invalid JSON", None),
                    ("no backup root", self.planned(), "", ""),
                    ("agents beside dotted keys, no tomllib",
                     ((self.toml_path, old_toml, 'model = "x"\nagents.max_threads = 3\n\n[agents]\nmax_threads = 6\n'),),
                     "invalid TOML", None)]
        if HAS_TOMLLIB:
            refusals.append(("invalid TOML", ((self.toml_path, old_toml, 'model = "x"\n[agents\nmax_threads = 1\n'),),
                             "invalid TOML", None))
        for label, changes, fragment, root in refusals:
            with self.subTest(label), self.parser("no tomllib" not in label):
                self.assert_refused(changes, fragment, root)
        with self.subTest("file changed after the plan"):
            fixtures.write(self.settings_path, old_json.replace("opus", "sonnet"))
            self.assert_refused(stale_plan, "changed since")

    def check_a_second_backup_never_overwrites_the_first(self) -> None:
        first = self.put_settings()
        apply_settings.apply(self.planned(), self.backup_root, home=self.home)
        second = read(self.settings_path)
        apply_settings.apply(self.planned({"guardrails.hook_profile": "minimal"}), self.backup_root, home=self.home)
        folder = os.path.join(self.backup_root, ".claude")
        self.assertEqual(sorted(os.listdir(folder)), ["settings.1.json", "settings.json"])
        self.assertEqual(read(os.path.join(folder, "settings.json")), first)
        self.assertEqual(read(os.path.join(folder, "settings.1.json")), second)

    def check_a_failed_replace_keeps_the_temp_file(self) -> None:
        old = self.put_settings()
        changes = self.planned()
        real_replace = os.replace
        calls: List[int] = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("disk went away")
            return real_replace(src, dst)

        with mock.patch.object(apply_settings.os, "replace", flaky), \
                mock.patch.object(apply_settings.os, "remove", side_effect=AssertionError("remove")), \
                mock.patch.object(apply_settings.os, "unlink", side_effect=AssertionError("unlink")):
            outcome = apply_settings.apply(changes, self.backup_root)[0]
        self.assertFalse(outcome.ok)
        self.assertIn("disk went away", outcome.message)
        self.assertEqual(read(self.settings_path), old)
        self.assertEqual(os.listdir(self.paths.claude_home), ["settings.json"])
        leftovers = glob.glob(os.path.join(self.backup_root, ".settings.json.*.tmp"))
        self.assertEqual(len(leftovers), 1)
