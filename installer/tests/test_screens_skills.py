"""Key handling and drawing of the skill screens (Skills, Installed, Issues, viewer).
The Updates screen is tested in test_screens_updates.py, on top of the SkillScreenCase below.

No terminal is started: the App runs with ``stdscr=None`` on the fixture repo and home, keys go
straight into ``handle_key``, drawing goes to tui_support's FakeWindow, and mutating keys are checked
through the ConfirmScreen they push (one test applies a plan for real).
"""

from __future__ import annotations

import curses
import os
import tempfile
import unittest
from unittest import mock

from installer.core import actions
from installer.core.types import State
from installer.tests import fixtures
from installer.tests.tui_support import ENTER, ESC, FakeWindow, make_caps
from installer.tui import draw
from installer.tui.app import App
from installer.tui.base import POP
from installer.tui.screens.browse import BrowseScreen
from installer.tui.screens.confirm import ConfirmScreen
from installer.tui.screens.installed import InstalledScreen
from installer.tui.screens.issues import IssuesScreen
from installer.tui.screens.viewer import TextScreen, ViewerScreen
from installer.tui.screens.viewer_panes import TextPane, place


class SkillScreenCase(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.dict(os.environ, {"INSTALLER_ASCII": "1"}),
                        mock.patch.object(curses, "has_colors", return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: draw._STATE.update(colors=False))
        draw.init_colors()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = fixtures.build(tmp.name)
        self.app = App(self.paths, stdscr=None, caps=make_caps())
        self.app.rescan()

    def open(self, screen):
        self.app.push(screen)
        return screen

    def press(self, screen, *keys):
        for key in keys:
            for code in ([ord(c) for c in key] if isinstance(key, str) else [key]):
                screen.handle_key(code, self.app)

    def focus(self, screen, scope, name):
        names = [(item.scope, item.name) for _, item in screen.model.filtered()]
        screen.model = place(screen.model, names.index((scope, name)), 40)

    def status(self, scope, name):
        return next(s for s in self.app.statuses if s.key == (scope, name))

    def take_confirm(self):
        top = self.app.top()
        self.assertIsInstance(top, ConfirmScreen, f"no dialog; message: {self.app.message!r}")
        self.app.pop()
        return top

    def kinds_after(self, screen, scope, name, key):
        self.focus(screen, scope, name)
        self.press(screen, key)
        return tuple(op.kind for op in self.take_confirm().ops)

    def render(self, screen, rows=24, cols=80) -> str:
        win = FakeWindow(rows, cols)
        screen.draw(win, self.app)
        return "\n".join(win.row(y) for y in range(rows))


class BrowseTests(SkillScreenCase):
    def setUp(self):
        super().setUp()
        self.screen = self.open(BrowseScreen())

    def test_install_and_update_build_plans_and_skip_what_cannot_run(self):
        self.assertIn("shared alpha", self.render(self.screen))
        self.focus(self.screen, "shared", "alpha")
        self.press(self.screen, ENTER)
        self.assertIsInstance(self.app.top(), ViewerScreen)
        self.app.pop()
        self.press(self.screen, "/", "dup", ENTER)
        self.focus(self.screen, "shared", "dup")
        self.press(self.screen, "i")
        dialog = self.take_confirm()
        self.assertEqual([op.kind for op in dialog.ops],
                         ["mkdir", "copytree", "mkdir", "symlink", "mkdir", "symlink"])
        self.assertEqual(dialog.title, "Install shared/dup")
        self.assertEqual(self.kinds_after(self.screen, "claude", "dup", "i"), ("mkdir", "copytree"))  # alone: no clash
        self.press(self.screen, ESC, "n")
        self.focus(self.screen, "shared", "alpha")
        self.press(self.screen, " ")
        self.focus(self.screen, "claude", "dup")
        self.press(self.screen, " ", "i")
        self.assertEqual([op.kind for op in self.take_confirm().ops], ["mkdir", "copytree"])
        self.assertIn("skipped 1: alpha (already installed)", self.app.message)
        self.press(self.screen, "n")
        self.assertEqual(self.kinds_after(self.screen, "shared", "beta", "u"), ("backup", "mkdir", "copytree"))
        self.focus(self.screen, "shared", "alpha")
        self.press(self.screen, "n")
        for key, words in (("u", "already up to date"), ("i", "already installed")):
            self.press(self.screen, key)
            self.assertIs(self.app.top(), self.screen)
            self.assertIn(words, self.app.message)
        with mock.patch.object(actions, "plan_install", side_effect=RuntimeError("boom")):
            self.press(self.screen, "i")
        self.assertIn("error: RuntimeError: boom", self.app.message)

    def test_colliding_rows_are_dropped_and_named_and_the_plan_applies_end_to_end(self):
        # shared/dup links itself into ~/.claude/skills/dup, exactly where claude/dup would be copied
        self.press(self.screen, "/", "dup", ENTER, "a", "i")
        dialog = self.app.top()
        self.assertIsInstance(dialog, ConfirmScreen)
        self.assertEqual([op.kind for op in dialog.ops], ["mkdir", "copytree", "mkdir", "symlink", "mkdir", "symlink"])
        self.assertEqual(dialog.title, "Install shared/dup")
        self.assertIn("skipped 1: dup (same path as shared/dup", self.app.message)
        self.assertIn(os.path.join(".claude", "skills", "dup"), self.app.message)
        self.app.handle_key(ord("y"))
        self.assertEqual(len(dialog.results), 6)
        self.assertEqual([r.message for r in dialog.results if not r.ok], [])  # every operation succeeded
        self.app.handle_key(ord(" "))
        self.assertIs(self.app.top(), self.screen)
        self.assertEqual(self.screen.model.selected_count, 0)
        self.assertEqual(self.status("shared", "dup").state, State.INSTALLED)
        self.assertTrue(os.path.islink(os.path.join(self.paths.consumer_dir("codex"), "dup")))
        self.assertTrue(os.path.islink(os.path.join(self.paths.consumer_dir("claude"), "dup")))


class InstalledTests(SkillScreenCase):
    def setUp(self):
        super().setUp()
        self.screen = self.open(InstalledScreen())

    def test_plan_keys_build_the_expected_operations_and_retire_uses_the_retired_skills_backup(self):
        cases = (("shared", "alpha", "r", ("backup", "unlink-to-backup", "unlink-to-backup")),
                 ("shared", "alpha", "x", ("unlink-to-backup", "unlink-to-backup")),
                 ("shared", "beta", "l", ("unlink-to-backup", "mkdir", "symlink")),
                 ("shared", "beta", "p", ("backup", "mkdir", "copytree")),
                 ("shared", "foreign1", "p", ("mkdir", "copytree")),
                 ("codex", "gamma", "u", ("backup", "mkdir", "copytree")))
        for scope, name, key, kinds in cases:
            with self.subTest(scope=scope, name=name, key=key):
                self.assertEqual(self.kinds_after(self.screen, scope, name, key), kinds)
        self.focus(self.screen, "shared", "alpha")
        self.press(self.screen, "x")
        dialog = self.take_confirm()
        self.assertIn("retired-skills-", dialog.backup_root)
        self.assertEqual(dialog.title, "Unlink shared/alpha from the tools")
        self.assertIn("shared alpha", self.render(self.screen))
        self.focus(self.screen, "shared", "beta")
        self.press(self.screen, "d")
        self.assertEqual(self.app.top().pane.kind, "diff")


class IssuesTests(SkillScreenCase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.paths.source_dir("shared"), "hollow"))  # no SKILL.md
        self.app.rescan()
        self.screen = self.open(IssuesScreen())

    def test_relink_and_retire_plans_and_the_filter_matches_the_issue_text(self):
        self.assertEqual(self.kinds_after(self.screen, "shared", "beta", "l"), ("unlink-to-backup", "mkdir", "symlink"))
        self.assertEqual(self.kinds_after(self.screen, "claude", "ghost", "r"), ("unlink-to-backup",))
        self.press(self.screen, "/", "broken symlink", ENTER)
        self.assertEqual({r.name for _, r in self.screen.model.filtered()}, {"beta", "ghost"})
        self.assertIn("claude ghost", self.render(self.screen))
        self.focus(self.screen, "shared", "beta")
        self.press(self.screen, ENTER)
        self.assertIn("Fix: l relinks", "\n".join(self.app.top().pane.lines))
        self.app.pop()
        self.press(self.screen, ESC)  # clear the filter
        self.focus(self.screen, "shared", "hollow")
        self.press(self.screen, "l")
        self.assertIn("repo issues can only be fixed in the repo", self.app.message)


class ViewerTests(SkillScreenCase):
    def make(self, scope="shared", name="alpha", **kwargs):
        return self.open(ViewerScreen(self.status(scope, name), **kwargs))

    def names(self, viewer):
        return [row.node.name for row in viewer.tree_model.items]

    def test_opens_on_skill_md_draws_and_the_tree_expands_opens_and_collapses(self):
        viewer = self.make()
        self.assertEqual(self.names(viewer), ["alpha", "references", "SKILL.md"])
        self.assertEqual(viewer.tree_model.current().node.name, "SKILL.md")
        self.assertEqual((viewer.pane.title, viewer.pane.lines[0]), ("SKILL.md", "---"))
        shown = self.render(viewer)
        for words in ("shared/alpha", "installed", "Alpha skill for testing", "SKILL.md", "name: alpha", "|"):
            self.assertIn(words, shown)
        self.press(viewer, "g", "j", ENTER)
        self.assertEqual(self.names(viewer), ["alpha", "references", "notes.md", "SKILL.md"])
        self.press(viewer, ENTER)
        self.assertEqual(len(self.names(viewer)), 3)
        self.press(viewer, "l", "l")  # the second l moves into the expanded directory
        self.assertEqual(viewer.tree_model.current().node.name, "notes.md")
        self.press(viewer, ENTER)
        self.assertEqual(viewer.pane.lines, ("alpha notes",))
        self.press(viewer, "h")  # on a file: jump to the parent
        self.assertEqual(viewer.tree_model.current().node.name, "references")
        self.press(viewer, "h", "g", "h", ENTER)  # collapse; the root never collapses
        self.assertEqual(len(self.names(viewer)), 3)


class TextScreenAndFileTests(SkillScreenCase):
    def test_text_screen_scrolls_pans_and_closes_and_the_pane_clamps(self):
        screen = self.open(TextScreen("long", [f"{n} " + "y" * 150 for n in range(60)]))
        self.render(screen)
        self.press(screen, "j", "j", "k", curses.KEY_NPAGE)
        self.assertGreater(screen.pane.top, 1)
        self.press(screen, "l", "l")
        self.assertEqual(screen.pane.left, 16)
        self.assertEqual(screen.handle_key(ESC, self.app), POP)
        pane = TextPane.make("t", ["a" * 100, "b", "c"])
        self.assertEqual((pane.scrolled(99, 2).top, pane.panned(500, 40).left), (1, 60))
        self.assertEqual(TextPane.make("d", ["+x"], kind="diff").visible(1)[0][1], draw.attr("ok"))


if __name__ == "__main__":
    unittest.main()
