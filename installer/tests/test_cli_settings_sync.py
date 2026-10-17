"""The apply and settings-sync commands (installer.cli_system), run in-process against a temp home."""

from __future__ import annotations

import json
import os
import stat
from typing import Any, List, Optional, Tuple
from unittest import mock

from installer import cli_system
from installer.tests import fixtures
from installer.tests.settings_support import EXAMPLE_TOML, SAMPLE_SETTINGS, dump, read
from installer.tests.test_cli import CliTestCase


class FakeInstall:
    """Stands in for the install.sh subprocess `apply` spawns: streams one line, exits with `code`."""

    def __init__(self, argv: List[str], code: int) -> None:
        self.stdout = iter(["install.sh %s\n" % " ".join(argv[1:])])
        self._code = code

    def wait(self) -> int:
        return self._code


class SettingsCommandTests(CliTestCase):
    @property
    def settings(self) -> str:
        return os.path.join(self.home, ".claude", "settings.json")

    @property
    def toml(self) -> str:
        return os.path.join(self.home, ".codex", "config.toml")

    @property
    def marker(self) -> str:
        return os.path.join(self.root, "installed.txt")

    def setup_files(self, **values: str) -> None:
        fixtures.write(self.settings, dump(SAMPLE_SETTINGS))
        fixtures.write(self.toml, read(EXAMPLE_TOML))
        for key, value in (values or {"guardrails.hook_profile": "strict"}).items():
            self.assertEqual(self.run_cli("config", "set", key.replace("__", "."), value, "--yes")[0], 0)

    def write_script(self, body: str) -> None:
        path = fixtures.write(os.path.join(self.paths.repo_dir, "install.sh"), "#!/bin/sh\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def stub_install(self, code: int = 0) -> mock.Mock:
        """Replace the subprocess. Like the real install.sh it puts the default ~/.agents/config.json in
        place only when it is absent, and never on --dry-run."""
        def spawn(argv, script, cwd, env):
            if code == 0 and "--dry-run" not in argv and not os.path.exists(self.agents("config.json")):
                fixtures.write(self.agents("config.json"), '{"version": 1}\n')
            return FakeInstall(argv, code)
        fixtures.write(os.path.join(self.paths.repo_dir, "install.sh"), "#!/bin/sh\n")  # apply wants a script
        patcher = mock.patch.object(cli_system, "_spawn", side_effect=spawn)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def hand_set_files(self) -> Tuple[str, str]:
        env = dict(SAMPLE_SETTINGS["env"], ECC_HOOK_PROFILE="strict", ECC_DISABLED_HOOKS="pre:bash:tmux-reminder")
        fixtures.write(self.settings, dump(dict(SAMPLE_SETTINGS, env=env)))
        fixtures.write(self.toml, read(EXAMPLE_TOML).replace("max_threads = 6", "max_threads = 9"))
        return read(self.settings), read(self.toml)

    def profile(self) -> Optional[str]:
        return json.loads(read(self.settings)).get("env", {}).get("ECC_HOOK_PROFILE")

    def sync(self, *flags: str, **kwargs: Any):
        return self.run_cli("settings-sync", *flags, **kwargs)

    # ---------------------------------------------------------------- settings-sync

    def check_dry_run_prints_the_plan_changes_nothing_and_hides_secrets(self) -> None:
        self.setup_files()
        env = dict(SAMPLE_SETTINGS["env"], ANTHROPIC_AUTH_TOKEN="sk-fake-1")
        fixtures.write(self.settings, dump(dict(SAMPLE_SETTINGS, env=env)))
        before = read(self.settings)
        code, out, err = self.sync("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("Settings sync (1 file(s) to change)", out)
        self.assertIn('+    "ECC_HOOK_PROFILE": "strict"', out)
        self.assertIn("Dry run only", out)
        self.assertNotIn("sk-fake-1", out + err)
        self.assertEqual(read(self.settings), before)
        self.assertEqual(self.backups("settings-sync-*"), [])

    def check_yes_applies_to_both_files_backs_up_the_originals_and_a_second_run_does_nothing(self) -> None:
        self.setup_files(**{"guardrails__hook_profile": "strict", "subagents__codex__max_threads": "3"})
        old_settings, old_toml = read(self.settings), read(self.toml)
        code, out, err = self.sync("--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.profile(), "strict")
        self.assertIn("max_threads = 3", read(self.toml))
        self.assertIn("Backups went under", out)
        root = self.backups("settings-sync-*")[0]
        self.assertEqual(read(os.path.join(root, ".claude", "settings.json")), old_settings)
        self.assertEqual(read(os.path.join(root, ".codex", "config.toml")), old_toml)
        code, out, _ = self.sync("--yes")
        self.assertIn("nothing to do", out)
        self.assertEqual((code, len(self.backups("settings-sync-*"))), (0, 1))

    def check_without_a_terminal_it_asks_for_yes_and_the_prompt_decides(self) -> None:
        self.setup_files()
        code, _, err = self.sync()
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertIsNone(self.profile())
        code, out, _ = self.sync(stdin="n\n", tty=True)
        self.assertEqual((code, self.profile()), (1, None))
        self.assertIn("Aborted", out)
        code, _, _ = self.sync(stdin="y\n", tty=True)
        self.assertEqual((code, self.profile()), (0, "strict"))

    def check_codex_off_leaves_the_toml_alone(self) -> None:
        self.setup_files(**{"guardrails__hook_profile": "strict", "tools__codex": "off",
                            "subagents__codex__max_threads": "2"})
        old_toml = read(self.toml)
        code, out, _ = self.sync("--yes")
        self.assertEqual((code, read(self.toml), self.profile()), (0, old_toml, "strict"))
        self.assertNotIn("config.toml", out)

    def check_nothing_is_synced_without_a_saved_or_a_readable_config(self) -> None:
        fixtures.write(self.settings, dump(SAMPLE_SETTINGS))
        code, out, _ = self.sync("--yes")  # never saved: the defaults must not overwrite hand edits
        self.assertIn("nothing to do", out)
        self.assertEqual((code, self.profile()), (0, None))
        self.setup_files()
        fixtures.write(self.agents("config.json"), "{ nope")
        code, out, _ = self.sync("--yes")
        self.assertEqual((code, self.profile()), (0, None))
        self.assertIn("nothing was synced", out)

    def check_a_broken_settings_file_is_skipped_and_reported(self) -> None:
        self.setup_files(**{"subagents__codex__max_threads": "2"})
        fixtures.write(self.settings, "{ nope")
        code, out, _ = self.sync("--yes")
        self.assertEqual((code, read(self.settings)), (0, "{ nope"))
        self.assertIn("skip", out)
        self.assertIn("not valid JSON", out)
        self.assertIn("max_threads = 2", read(self.toml))

    # ---------------------------------------------------------------- apply

    def check_apply_runs_the_script_and_then_syncs(self) -> None:
        self.setup_files()
        self.write_script(f'echo "install.sh $*"\ntouch "{self.marker}"\n')
        code, out, err = self.run_cli("apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertLess(out.index("install.sh --headless --auto"), out.index("Settings sync"))
        self.assertNotIn("skipped", out)  # a config saved before the run is synced after it
        self.assertEqual(self.profile(), "strict")
        self.assertTrue(os.path.exists(self.marker))

    def check_apply_dry_run_declined_and_failing_script_sync_nothing(self) -> None:
        self.setup_files()
        spawn = self.stub_install()
        code, out, _ = self.run_cli("apply", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(spawn.call_args.args[0][1:], ["--headless", "--auto", "--dry-run"])
        self.assertIn('"ECC_HOOK_PROFILE": "strict"', out)  # the settings plan is shown, not written
        self.assertIsNone(self.profile())
        spawn.reset_mock()
        code, _, _ = self.run_cli("apply", stdin="n\n", tty=True)
        self.assertEqual((code, spawn.call_count, self.profile()), (1, 0, None))
        self.stub_install(code=5)
        code, out, _ = self.run_cli("apply", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("settings were not synced", out)
        self.assertIsNone(self.profile())

    def check_apply_without_a_saved_config_does_not_push_defaults_but_settings_sync_still_can(self) -> None:
        settings, toml = self.hand_set_files()
        self.stub_install()
        code, preview, _ = self.run_cli("apply", "--dry-run")  # the preview agrees with the real run
        self.assertEqual(code, 0)
        self.assertIn("Settings sync: skipped", preview)
        self.assertFalse(os.path.exists(self.agents("config.json")))
        code, out, err = self.run_cli("apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(self.agents("config.json")))  # install.sh did create it
        self.assertEqual((read(self.settings), read(self.toml)), (settings, toml))
        self.assertIn("Settings sync: skipped", out)
        self.assertEqual(self.backups("settings-sync-*"), [])
        code, _, err = self.sync("--yes")  # the explicit request, after reviewing the file
        self.assertEqual(code, 0, err)
        self.assertEqual(self.profile(), "standard")

    def check_a_second_apply_keeps_values_set_by_hand_and_says_so_even_on_a_dry_run(self) -> None:
        settings, toml = self.hand_set_files()
        self.stub_install()
        self.run_cli("apply", "--yes")  # run 1: install.sh seeds config.json with the defaults
        code, out, err = self.run_cli("apply", "--yes")  # run 2: that file still holds nothing but defaults
        self.assertEqual(code, 0, err)
        self.assertEqual((read(self.settings), read(self.toml)), (settings, toml))
        self.assertEqual(self.backups("settings-sync-*"), [])
        self.assertIn("Settings sync: nothing to do", out)
        kept = out.split("kept as they are")[1]
        self.assertIn("settings.json", kept)
        self.assertIn("config.toml", kept)
        self.assertIn("settings-sync", out)
        code, out, _ = self.run_cli("apply", "--dry-run")
        self.assertEqual((code, read(self.settings), read(self.toml)), (0, settings, toml))
        self.assertIn("kept as they are", out)

    def check_apply_pushes_what_was_changed_and_leaves_the_rest(self) -> None:
        settings, toml = self.hand_set_files()  # strict profile, a disabled hook, max_threads = 9
        self.assertEqual(self.run_cli("config", "set", "subagents.codex.max_depth", "2", "--yes")[0], 0)
        self.stub_install()
        code, out, err = self.run_cli("apply", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(read(self.settings), settings)
        self.assertEqual(read(self.toml), toml.replace("max_depth = 1", "max_depth = 2"))
        self.assertEqual(len(self.backups("settings-sync-*")), 1)
        self.assertIn("kept as they are", out)  # both files still hold a hand-set value of a defaulted setting

    def check_changing_a_setting_back_to_its_default_waits_for_settings_sync(self) -> None:
        self.setup_files()  # hook_profile = strict
        self.stub_install()
        self.run_cli("apply", "--yes")
        self.assertEqual(self.profile(), "strict")
        self.assertEqual(self.run_cli("config", "set", "guardrails.hook_profile", "standard", "--yes")[0], 0)
        code, out, _ = self.run_cli("apply", "--yes")
        self.assertEqual((code, self.profile()), (0, "strict"))  # a default is not a change for apply
        self.assertIn("settings-sync", out)
        self.assertEqual(self.sync("--yes")[0], 0)
        self.assertEqual(self.profile(), "standard")

    def test_settings_sync_command(self) -> None:
        self.run_scenarios(
            self.check_dry_run_prints_the_plan_changes_nothing_and_hides_secrets,
            self.check_yes_applies_to_both_files_backs_up_the_originals_and_a_second_run_does_nothing,
            self.check_without_a_terminal_it_asks_for_yes_and_the_prompt_decides,
            self.check_codex_off_leaves_the_toml_alone,
            self.check_nothing_is_synced_without_a_saved_or_a_readable_config,
            self.check_a_broken_settings_file_is_skipped_and_reported)

    def test_apply_runs_the_script_and_syncs_nothing_when_dry_run_declined_or_failed(self) -> None:
        self.run_scenarios(
            self.check_apply_runs_the_script_and_then_syncs,
            self.check_apply_dry_run_declined_and_failing_script_sync_nothing)

    def test_apply_pushes_only_what_differs_from_the_defaults(self) -> None:
        self.run_scenarios(
            self.check_apply_without_a_saved_config_does_not_push_defaults_but_settings_sync_still_can,
            self.check_a_second_apply_keeps_values_set_by_hand_and_says_so_even_on_a_dry_run,
            self.check_apply_pushes_what_was_changed_and_leaves_the_rest,
            self.check_changing_a_setting_back_to_its_default_waits_for_settings_sync)


