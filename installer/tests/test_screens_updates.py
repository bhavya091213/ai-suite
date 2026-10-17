"""Key handling and drawing of the Updates screen (tab 5).

Same harness as test_screens_skills.py: the App runs with ``stdscr=None`` on the fixture repo and
home, git state is faked, and keys go straight into ``handle_key``.
"""

from __future__ import annotations

import unittest
from unittest import mock

from installer.core.types import RemoteChange
from installer.tests.test_screens_skills import SkillScreenCase
from installer.tests.tui_support import make_git
from installer.tui.screens import updates as updates_mod
from installer.tui.screens.updates import UpdatesScreen


class UpdatesTests(SkillScreenCase):
    def setUp(self):
        super().setUp()
        change = RemoteChange("origin/main", ("shared/skills/alpha/SKILL.md",), ("abc1234 tweak alpha",))
        self.app.remote = {("shared", "alpha"): change}
        self.app.git = make_git(behind=2, message="2 commits behind origin/main")
        self.app.rescan()
        patcher = mock.patch.object(updates_mod.git_mod, "commits_behind",
                                    return_value=("abc1234 tweak alpha", "def5678 other"))
        self.commits_behind = patcher.start()
        self.addCleanup(patcher.stop)
        self.screen = self.open(UpdatesScreen())

    def test_lists_come_from_git_and_the_remote_changes_and_draw_banner_and_both_lists(self):
        self.assertEqual(self.screen.commits.items, ("abc1234 tweak alpha", "def5678 other"))
        self.assertEqual([s.key for s in self.screen.skills.items], [("shared", "alpha")])
        shown = self.render(self.screen)
        for words in ("Git: 2 commits behind", "Commits behind origin/main (2)", "Skills changed upstream (1)",
                      "def5678 other", "shared alpha", "never fetched"):
            self.assertIn(words, shown)
        self.commits_behind.reset_mock()  # up to date: no git lookup at all
        self.app.git = make_git()
        self.screen.reload(self.app)
        self.commits_behind.assert_not_called()
        self.assertEqual(self.screen.commits.count, 0)

    def test_pull_needs_p_then_y_and_any_other_key_cancels(self):
        with mock.patch.object(self.app, "pull", return_value=(True, "ok")) as pull, \
                mock.patch.object(self.app, "rescan") as rescan:
            self.press(self.screen, "P", "n", "y")
            pull.assert_not_called()
            self.assertEqual(self.app.message, "pull cancelled")
            self.press(self.screen, "P")
            self.assertTrue(self.screen.pull_armed)
            self.assertIn("y = pull", self.render(self.screen))
            pull.assert_not_called()
            self.press(self.screen, "y")
            pull.assert_called_once_with()
            rescan.assert_called_once_with()
            self.assertFalse(self.screen.pull_armed)
        for info, words in ((make_git(), "already up to date"), (make_git(ahead=1, behind=2), "diverged"),
                            (make_git(upstream=None), "no upstream")):
            self.app.git = info
            self.press(self.screen, "P")
            self.assertFalse(self.screen.pull_armed)
            self.assertIn(words, self.app.message)


if __name__ == "__main__":
    unittest.main()
