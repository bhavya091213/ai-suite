"""Tests for the Workflows tab: the list and the skill picker, plus the case the editors build on.

Screens are driven through ``App.handle_key`` on a real ``App`` whose ``stdscr`` is None, over the
fixture repo and home, so the screen stack, ``editing()`` and the pop results behave as in the real
program while curses never starts. Prompts are patched; ``App.confirm`` is replaced by a recorder
except in the end-to-end tests that run the real confirm dialog. The editor and phase editor are in
``test_screens_workflow_edit``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from typing import List
from unittest import mock

from installer.core import workflows
from installer.core.workflows import Phase, WorkflowDef
from installer.tests.tui_support import ENTER, ESC, PROMPT, AppCase, FakeWin
from installer.tui.screens import help as help_screen
from installer.tui.screens.confirm import ConfirmScreen
from installer.tui.screens.skill_picker import SkillPickerScreen, skill_choices
from installer.tui.screens.viewer import TextScreen
from installer.tui.screens.workflows import blank_definition


def demo_def(**changes) -> WorkflowDef:
    base = WorkflowDef(
        name="demo-flow", description="Demo workflow for the tests.", triggers=("run the demo",),
        phases=(Phase("Plan", "Decide.", ("alpha", "beta"), (), ("plan.md",), gate=True),
                Phase("Do", "Do it.", ("alpha", "not-installed-anywhere"), ("Run it.",))))
    return WorkflowDef(**{**base.__dict__, **changes})


class WorkflowCase(AppCase):
    """The fixture home with the Workflows tab open and ``App.confirm`` recording its plans."""

    def setUp(self) -> None:
        super().setUp()
        stage_root = os.path.join(self.root, "stage")
        os.makedirs(stage_root)
        real_mkdtemp = tempfile.mkdtemp
        fake_tempfile = SimpleNamespace(mkdtemp=lambda prefix="": real_mkdtemp(prefix=prefix, dir=stage_root))
        patcher = mock.patch("installer.tui.screens.workflow_edit.tempfile", fake_tempfile)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.confirms: List[tuple] = []
        self.app.rescan()
        self.app.goto_tab(10)
        self.list = self.app.top()
        self.app.confirm = lambda ops, title, on_done=None, backup_root=None: self.confirms.append(
            (tuple(ops), title, on_done))

    def key(self, *keys):
        out = None
        for key in keys:
            out = self.app.handle_key(key if isinstance(key, int) else ord(key))
        return out

    def prompt(self, answer, *keys):
        with mock.patch(PROMPT, return_value=answer):
            return self.key(*keys)

    def install_workflow(self, wf: WorkflowDef = None) -> str:
        wf = wf or demo_def()
        dest = os.path.join(self.paths.install_dir("shared"), wf.name)
        shutil.copytree(workflows.stage(wf, os.path.join(self.root, "staged")), dest)
        self.app.rescan()
        return dest

    def names(self, screen) -> List[str]:
        return [row.wf.name for row in screen.model.items]

    def tick(self, *names: str) -> None:
        """In the skill picker on top of the stack: tick each skill by name."""
        picker = self.app.top()
        for name in names:
            self.key("g")
            for _ in range(100):
                if picker.model.current().name == name:
                    break
                self.key("j")
            self.assertEqual(picker.model.current().name, name)
            self.key(" ")

    def drawn(self, screen, rows: int = 30, cols: int = 100) -> str:
        win = FakeWin(rows, cols)
        screen.draw(win, self.app)
        return win.text()


class ListTests(WorkflowCase):
    def test_retire_plans_a_move_to_a_backup_and_applies_it_only_after_a_yes(self) -> None:
        dest = self.install_workflow()
        self.key("p")  # push asks first too, and an identical copy in the repo is refused
        (ops, title, _), = self.confirms
        self.assertEqual((ops[-1].kind, ops[-1].dst), ("copytree", os.path.join(self.paths.source_dir("shared"), "demo-flow")))
        self.assertIn("Push", title)
        self.confirms.clear()
        self.key("r")
        (ops, title, _), = self.confirms
        self.assertEqual([op.kind for op in ops], ["backup"])
        self.assertEqual(ops[0].src, dest)
        self.assertIn(os.path.join("backups", "retired-skills-"), ops[0].dst)
        self.assertIn("demo-flow", title)
        del self.app.confirm
        self.key("r")
        self.assertIsInstance(self.app.top(), ConfirmScreen)
        self.assertTrue(os.path.exists(dest))  # nothing moves until the y
        self.key("y", " ")
        self.assertIs(self.app.top(), self.list)
        self.assertFalse(os.path.exists(dest))
        self.assertEqual(self.names(self.list), [])
        walked = os.walk(os.path.join(self.paths.agents_home, "backups"))
        self.assertTrue(any("demo-flow" in dirs for _, dirs, _ in walked))

    def test_view_and_the_editor_keys_open_screens_and_a_failing_action_reports(self) -> None:
        dest = self.install_workflow()
        self.assertIn("demo-flow", self.drawn(self.list))
        self.key("v")
        top = self.app.top()
        self.assertIsInstance(top, TextScreen)
        self.assertEqual(top.title, "SKILL.md - demo-flow")
        self.assertEqual(top.pane.lines, tuple(workflows.render_skill_md(demo_def()).splitlines()))
        self.assertIn(workflows.MARKER, top.pane.lines)
        self.assertIn("## Phase 2 - Do", top.pane.lines)
        self.key(ESC)
        self.assertIs(self.app.top(), self.list)
        self.key(ENTER)
        editor = self.app.top()
        self.assertEqual((editor.wf, editor.skill_dir, editor.dirty), (demo_def(), dest, False))
        self.key("q", "n")
        self.assertEqual(self.app.top().wf, blank_definition())
        self.assertEqual(len(blank_definition().phases), 1)
        self.key("q", "N")
        self.assertEqual(self.app.top().wf, workflows.example())
        self.assertEqual(self.app.active_tab, 10)
        self.key("q")
        with mock.patch("installer.core.actions.plan_retire", side_effect=RuntimeError("boom")):
            self.assertIsNone(self.key("r"))
        self.assertIn("boom", self.app.message)


class PickerTests(WorkflowCase):
    def test_toggle_filter_accept_cancel_and_the_global_keys_that_do_not_leave(self) -> None:
        got = []
        picker = SkillPickerScreen(skill_choices(self.app.statuses), ("beta",), got.append)
        self.app.push(picker)
        self.assertEqual([c.name for c in picker.model.selected_items()], ["beta"])
        self.key("/", *"gam")
        self.assertEqual([c.name for _, c in picker.model.filtered()], ["gamma"])
        self.key(ENTER, " ", ESC)
        self.assertEqual((picker.model.query, picker.model.selected_count), ("", 2))
        self.key("n")
        self.tick("dup", "alpha")
        self.key("/", "?")  # ? inside a filter is text, not help
        self.assertEqual(picker.model.query, "?")
        self.key(ESC, "?")
        self.assertIsInstance(self.app.top(), help_screen.HelpScreen)
        self.key("q")
        self.assertIs(self.app.top(), picker)
        self.assertIsNone(self.key(ENTER))
        self.assertEqual(got, [("alpha", "dup")])
        self.assertIs(self.app.top(), self.list)
        cancelled = []
        self.app.push(SkillPickerScreen(skill_choices(self.app.statuses), (), cancelled.append))
        self.assertIsNone(self.key("Q"))
        self.key("3")
        self.assertIsInstance(self.app.top(), SkillPickerScreen)
        self.key(" ", "q")
        self.assertEqual(cancelled, [])
        self.assertIs(self.app.top(), self.list)


if __name__ == "__main__":
    unittest.main()
