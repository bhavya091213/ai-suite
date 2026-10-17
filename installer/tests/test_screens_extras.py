"""Tests for the Extras screen: the install confirmation and the chained install commands.

Driven through ``handle_key`` on the shared AppCase (fixture repo and home, no curses); run_command is a
recorder.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any, Dict

from installer.tests.tui_support import AppCase
from installer.tui.screens.extras import ExtrasScreen, InstallConfirmScreen

EXTRAS = {"extras": {
    "one": {"title": "One - first thing", "category": "design", "url": "https://example.test/one",
            "tools": ["claude", "codex"], "install": ["echo one"],
            "after_install": {"claude": "run it in claude", "codex": "run it in codex"},
            "detect": {"any_paths": ["~/.claude/skills/one"]},
            "note": "licence forbids redistribution, so it is never vendored into this repo"},
    "two": {"title": "Two - codex only", "category": "slides", "url": "https://example.test/two",
            "tools": ["codex"], "install_by_tool": {"codex": ["echo a b", "echo 'c d'"]},
            "detect": {"any_paths": ["~/.codex/skills/two"]}},
    "bad": {"title": "Bad quoting", "tools": ["claude"], "install": ["echo 'unterminated"]},
}}


class ExtrasTests(AppCase):
    def setUp(self) -> None:
        super().setUp()
        self.load(EXTRAS)

    def load(self, data: Dict[str, Any]) -> None:
        self.write_repo("shared/extras.json", json.dumps(data))
        self.app.rescan()

    def screen(self, key: str = "one") -> ExtrasScreen:
        screen = ExtrasScreen()
        self.app.push(screen)
        self.goto(screen, lambda status: status.extra.key == key)
        return screen

    def start_two(self) -> ExtrasScreen:
        """Codex on, cursor on the two-command extra, install confirmed."""
        self.use_caps("claude", "codex")
        self.app.rescan()
        screen = self.screen("two")
        self.press(screen, "i")
        self.app.handle_key(ord("y"))
        return screen

    def test_install_confirmation_names_commands_warns_and_can_cancel_and_bad_plans_are_messages(self) -> None:
        screen = self.screen()
        self.press(screen, "i")
        confirm = self.app.top()
        self.assertIsInstance(confirm, InstallConfirmScreen)
        self.assertTrue(confirm.editing())
        text = "\n".join(line for line, _ in confirm.lines())
        for expected in ("1. echo one", "third-party code", "Skipped codex"):
            self.assertIn(expected, text)
        self.app.handle_key(ord("n"))
        self.assertEqual((self.app.top() is screen, list(self.run)), (True, []))
        self.goto(screen, lambda status: status.extra.key == "two")
        self.press(screen, "i")
        self.assertIn("nothing to install", self.app.message)
        self.goto(screen, lambda status: status.extra.key == "bad")
        self.press(screen, "i")
        self.assertIn("cannot parse", self.app.message)
        self.assertEqual((self.app.top() is screen, list(self.run)), (True, []))
        os.makedirs(os.path.join(self.paths.claude_home, "skills", "one"))  # claude already has it, codex is off
        self.app.rescan()
        self.app.set_message("")
        self.goto(screen, lambda status: status.extra.key == "one")
        self.press(screen, "i")
        self.assertIn("nothing to install", self.app.message)

    def test_confirmed_install_chains_commands_from_the_home_and_a_failure_drops_the_rest(self) -> None:
        screen = self.start_two()
        self.assertIs(self.app.top(), screen)
        self.assertEqual([c["argv"] for c in self.run], [["echo", "a", "b"]])
        self.assertEqual(self.run[0]["cwd"], self.home)
        self.assertNotEqual(self.run[0]["cwd"], self.paths.repo_dir)
        self.run[0]["on_done"](0)
        screen.on_enter(self.app)
        self.assertEqual([c["argv"] for c in self.run], [["echo", "a", "b"], ["echo", "c d"]])
        self.run[1]["on_done"](0)
        screen.on_enter(self.app)
        self.assertEqual(len(self.run), 2)
        self.assertIn("install finished", self.app.message)
        screen = self.start_two()
        self.run[0]["on_done"](1)
        screen.on_enter(self.app)
        self.assertEqual(len(self.run), 1)
        self.assertIn("exited with 1; 1 remaining", self.app.message)


if __name__ == "__main__":
    unittest.main()
