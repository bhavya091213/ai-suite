"""Tests for the configuration screens: Settings, ListEdit, Files and Full install.
The Extras screen is tested in test_screens_extras.py.

Screens are driven through ``handle_key`` on a real ``App`` whose ``stdscr`` is None, over a fixture
repo and home; curses never starts. Prompts are patched and ``App.run_command`` is replaced by a
recorder.

``$HOME`` is pointed at the fixture home for every test, which is the ordinary "not relocated"
session; the relocated-``--home`` tests move ``$HOME`` somewhere else on purpose.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, List
from unittest import mock

from installer.core import config as cfg
from installer.tests import fixtures
from installer.tests.tui_support import ENTER, ESC, PROMPT, AppCase
from installer.tui.screens.files import FilesScreen
from installer.tui.screens.fullinstall import FullInstallScreen, build_argv
from installer.tui.screens.listedit import ListEditScreen
from installer.tui.screens.settings import SettingsScreen


class SettingsTests(AppCase):
    def screen(self, **kwargs) -> SettingsScreen:
        screen = SettingsScreen(**kwargs)
        self.app.push(screen)
        return screen

    def at(self, screen, key: str) -> None:
        self.goto(screen, lambda row: row.setting is not None and row.setting.key == key)

    @staticmethod
    def value(screen, key: str) -> Any:
        return cfg.get(screen.pending, key)

    def apply_argv(self, *extra: str) -> List[str]:
        """What A starts: the installer's own `apply` (install.sh, then the settings sync), not install.sh alone."""
        return [sys.executable, "-m", "installer", "apply", "--yes", "--repo", self.paths.repo_dir, *extra]

    def test_save_writes_config_and_apply_needs_that_file_and_a_yes(self) -> None:
        screen = self.screen()
        self.press(screen, "A")  # nothing edited, nothing saved: apply would only install the example defaults
        self.assertEqual((screen.editing(), "save" in self.app.message, list(self.run)), (False, True, []))
        self.at(screen, "guardrails.never_delete")
        self.app.set_message("")
        self.press(screen, " ", "A")  # unsaved edits
        self.assertEqual((screen.editing(), "save" in self.app.message), (False, True))
        path = os.path.join(self.paths.agents_home, "config.json")
        self.assertFalse(os.path.exists(path))
        self.press(screen, "s")
        with open(path, encoding="utf-8") as fh:
            self.assertFalse(json.load(fh)["guardrails"]["never_delete"])
        self.assertEqual((self.app.config.exists, screen.dirty()), (True, False))
        self.assertFalse(cfg.get(self.app.config, "guardrails.never_delete"))
        self.assertIn("saved", self.app.message)
        self.press(screen, "A")
        self.assertTrue(screen.editing())
        self.press(screen, "x")
        self.assertEqual((screen.editing(), list(self.run)), (False, []))
        self.press(screen, "A", "y")
        self.assertEqual(self.run[0]["argv"], self.apply_argv())
        self.assertEqual(self.run[0]["cwd"], self.paths.repo_dir)


class ListEditTests(AppCase):
    def make(self, key: str, items, finder=lambda: ()) -> ListEditScreen:
        self.changes: List[Any] = []
        screen = ListEditScreen(cfg.setting_for(key), items, self.changes.append, finder)
        self.app.push(screen)
        return screen

    def test_add_remove_make_default_and_import_for_vaults_only(self) -> None:
        screen = self.make("guardrails.disabled_hooks", ("a",))
        with mock.patch(PROMPT, return_value="b, a, c"):
            self.press(screen, "a")
        self.assertEqual((screen.items, self.changes[-1]), (("a", "b", "c"),) * 2)
        self.press(screen, "j", "x")
        self.assertEqual(screen.items, ("a", "c"))
        self.press(screen, "j", "d")
        self.assertEqual(self.changes[-1], ("c", "a"))
        self.press(screen, "d")
        self.assertEqual(self.app.message, "already the default")
        self.assertEqual((screen.handle_key(ESC, self.app), screen.handle_key(ENTER, self.app)), ("pop", "pop"))
        other = self.make("guardrails.disabled_hooks", ("a",), lambda: ("x",))
        self.press(other, "o")
        self.assertEqual(other.items, ("a",))
        vaults = self.make("paths.obsidian_vaults", ("/v/one",), lambda: ("/v/one", "/v/two"))
        self.press(vaults, "o")
        self.assertEqual(vaults.items, ("/v/one", "/v/two"))
        self.assertIn("(default)", self.render(vaults))
        self.press(vaults, "o")
        self.assertIn("already", self.app.message)


class FilesTests(AppCase):
    def screen(self, label: str = "~/.claude/CLAUDE.md") -> FilesScreen:
        screen = FilesScreen()
        self.app.push(screen)
        self.goto(screen, lambda row: row.spec.label == label)
        return screen

    @property
    def claude_md(self) -> str:
        return os.path.join(self.paths.claude_home, "CLAUDE.md")

    def read(self, path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_create_copies_the_example_and_never_overwrites_and_missing_files_are_explained(self) -> None:
        self.write_repo("claude-code/CLAUDE.md", "# Example\n@~/.agents/RULES.md\n")
        screen = self.screen()
        self.press(screen, "c")
        self.assertEqual(self.read(self.claude_md), "# Example\n@~/.agents/RULES.md\n")
        self.assertTrue(screen.model.current().exists)
        fixtures.write(self.claude_md, "my own\n")
        self.press(screen, "c")
        self.assertEqual(self.read(self.claude_md), "my own\n")
        self.assertIn("never overwritten", self.app.message)
        local = self.screen("~/.agents/LOCAL.md")  # no example to copy and nothing on disk
        self.press(local, "c")
        self.assertIn("cannot create", self.app.message)
        self.assertFalse(os.path.exists(os.path.join(self.paths.agents_home, "LOCAL.md")))
        for key in ("e", "v", "d"):
            self.press(local, key)
            self.assertIn("does not exist", self.app.message)
        self.assertIs(self.app.top(), local)


class FullInstallTests(AppCase):
    def screen(self) -> FullInstallScreen:
        screen = FullInstallScreen()
        self.app.push(screen)
        return screen

    @property
    def install_sh(self) -> str:
        return os.path.join(self.paths.repo_dir, "install.sh")

    def test_dry_run_and_apply_commands_confirm_first_and_follow_the_relocated_home(self) -> None:
        empty = self.screen()
        self.press(empty, "s", "c", "D", "A")  # nothing selected: nothing runs, no dialog
        self.assertEqual((list(self.run), empty.editing()), ([], False))
        self.app.pop()
        screen = self.screen()
        self.assertNotIn("runs with HOME", self.render(screen))
        self.press(screen, "D")
        self.assertEqual(self.run[0]["argv"], [self.install_sh, "--headless", "--shared", "--claude", "--dry-run"])
        self.assertEqual((self.run[0]["cwd"], "Dry run" in self.run[0]["title"]), (self.paths.repo_dir, True))
        self.assertFalse(self.run[0]["title"].endswith("]"))
        self.press(screen, "A")
        self.assertTrue(screen.editing())
        self.press(screen, "n")
        self.assertEqual((screen.editing(), len(self.run)), (False, 1))
        self.press(screen, "A", "y")
        self.assertEqual(self.run[1]["argv"], [self.install_sh, "--headless", "--shared", "--claude"])
        self.assertEqual(build_argv(self.paths, ("codex", "shared"), True),
                         (self.install_sh, "--headless", "--shared", "--codex", "--dry-run"))
        self.relocate()
        del self.run[:]
        screen = self.screen()
        self.assertIn(f"runs with HOME={self.home}", self.render(screen))
        self.press(screen, "D", "A", "y")
        prefix = ["env", f"HOME={self.home}"]
        self.assertEqual(self.run[0]["argv"], prefix + [self.install_sh, "--headless", "--shared", "--claude", "--dry-run"])
        self.assertEqual(self.run[1]["argv"], prefix + [self.install_sh, "--headless", "--shared", "--claude"])
        self.assertTrue(all(call["title"].endswith(f"[HOME={self.home}]") for call in self.run))
        self.assertTrue(all("env HOME" not in call["title"] for call in self.run))
        self.assertTrue(all(call["cwd"] == self.paths.repo_dir for call in self.run))


if __name__ == "__main__":
    unittest.main()
