"""Tests for the workflow editor (with its phase editor and skill picker) and what a save keeps.

Driven like ``test_screens_workflows``, whose ``WorkflowCase`` supplies the fixture home with the Workflows
tab open and ``App.confirm`` recording its plans (``del self.app.confirm`` runs the real dialog).
"""

from __future__ import annotations

import os
import unittest

from installer.core import actions, workflows
from installer.tests.test_screens_workflows import WorkflowCase, demo_def
from installer.tests.tui_support import ENTER
from installer.tui.base import POP, QUIT
from installer.tui.screens.skill_picker import SkillPickerScreen
from installer.tui.screens.workflow_edit import PhaseEditScreen, WorkflowEditScreen


class EditorTests(WorkflowCase):
    def open_new(self) -> WorkflowEditScreen:
        self.key("n")
        return self.app.top()

    def open_phase(self, index: int) -> PhaseEditScreen:
        self.key("g", *["j"] * (4 + index), ENTER)
        self.assertIsInstance(self.app.top(), PhaseEditScreen)
        return self.app.top()

    def test_new_workflow_end_to_end_builds_a_save_plan(self) -> None:
        editor = self.open_new()
        self.prompt("my-flow", ENTER)
        self.prompt("Research then build.", "j", ENTER)
        self.prompt("research it, build it", "j", ENTER)
        self.assertEqual((editor.wf.name, editor.wf.triggers), ("my-flow", ("research it", "build it")))
        self.key("G", "a", "a")
        self.assertEqual([p.name for p in editor.wf.phases], ["Phase 1", "Phase 2", "Phase 3"])
        self.key("K")
        self.assertEqual([p.name for p in editor.wf.phases], ["Phase 1", "Phase 3", "Phase 2"])
        self.assertEqual(editor.model.current().index, 1)
        self.key("J", "J")
        self.assertEqual([p.name for p in editor.wf.phases], ["Phase 1", "Phase 2", "Phase 3"])
        phase = self.open_phase(0)
        self.prompt("Research", ENTER)
        self.key("j", "j", "s")
        self.assertIsInstance(self.app.top(), SkillPickerScreen)
        self.tick("alpha", "beta")
        self.key(ENTER)
        self.assertIs(self.app.top(), phase)
        self.assertEqual(editor.wf.phases[0].skills, ("alpha", "beta"))
        self.key("j", ENTER)
        self.assertTrue(editor.wf.phases[0].gate)
        self.key(" ")
        self.assertFalse(editor.wf.phases[0].gate)
        self.key("t", "q")
        self.assertTrue(editor.wf.phases[0].gate)
        for position in (1, 2):
            self.open_phase(position)
            self.prompt(f"Step {position}", *["j"] * 5, "a")
            self.key("q")
        self.assertEqual([p.steps for p in editor.wf.phases], [(), ("Step 1",), ("Step 2",)])
        self.key("s")
        (ops, title, on_done), = self.confirms
        kinds = [op.kind for op in ops]
        self.assertLessEqual(set(kinds), {"mkdir", "copytree", "symlink"})
        self.assertEqual((kinds.count("copytree"), kinds.count("symlink")), (1, 2))
        self.assertIn("my-flow", title)
        results = actions.apply(ops)
        self.assertTrue(all(r.ok for r in results))
        on_done(results)
        self.assertFalse(editor.dirty)
        self.assertEqual(workflows.load_def(editor.skill_dir), editor.wf)
        link = os.path.join(self.paths.claude_home, "skills", "my-flow")
        self.assertEqual(os.path.realpath(link), os.path.realpath(editor.skill_dir))
        self.assertIn("my-flow", self.names(self.list))

    def test_q_with_changes_asks_for_y_other_global_keys_stay_out_and_capital_q_quits(self) -> None:
        self.open_new()
        self.key("q")
        self.assertIs(self.app.top(), self.list)
        self.install_workflow()
        for name, words in (("learned", "reserved"), ("gamma", "would keep running that"), ("demo-flow", "already exists"),
                            ("dup", "already a skill in the repo catalog")):  # never save over somebody else's skill
            self.app.push(WorkflowEditScreen(demo_def(name=name)))
            self.key("s")
            self.assertIn(words, self.app.message)
            self.key("q")
        self.assertEqual(self.confirms, [])
        editor = self.open_new()
        self.prompt("x-flow", ENTER)
        self.assertTrue(editor.dirty)
        self.key("2", "5")
        self.assertIs(self.app.top(), editor)
        self.key("q")
        self.assertIs(self.app.top(), editor)
        self.assertIn("unsaved changes", self.app.message)
        self.assertIn("y discard", self.drawn(editor))
        self.key("n")
        self.assertEqual((self.app.top(), self.app.message), (editor, "kept editing"))
        self.assertIsNone(self.key("Q"))
        self.assertIs(self.app.top(), editor)
        self.assertEqual(self.key("y"), QUIT)
        self.assertEqual(WorkflowEditScreen(demo_def()).handle_key(ord("q"), self.app), POP)  # clean: no question
        self.key("q", "y")
        self.assertIs(self.app.top(), self.list)


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


class SaveGuardTests(WorkflowCase):
    """What a save keeps and says: the skill's other files and the keys only the backup holds."""

    def other_files(self, dest: str) -> None:
        for rel, text in (("references/notes.md", "notes\n"), ("helper.py", "print(1)\n")):
            os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
            with open(os.path.join(dest, rel), "w", encoding="utf-8") as handle:
                handle.write(text)
        os.symlink("helper.py", os.path.join(dest, "alias.py"))

    @staticmethod
    def copy_op(ops):
        return next(op for op in ops if op.kind == "copytree")

    def edit_and_save(self, description: str = "Edited description.") -> tuple:
        self.key(ENTER)
        editor = self.app.top()
        self.prompt(description, "j", ENTER)
        self.key("s")
        return editor, self.confirms[-1]

    def test_saving_keeps_the_other_files_and_names_the_dropped_keys(self) -> None:
        dest = self.install_workflow()
        self.other_files(dest)
        path = os.path.join(dest, "workflow.json")
        data = workflows.to_json(demo_def()).replace('"version": 1', '"version": 1,\n  "owner": "me"')
        data = data.replace('"name": "Plan"', '"name": "Plan",\n      "colour": "red"')
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(data)
        editor, (ops, title, on_done) = self.edit_and_save()
        self.assertIn("keeps 3 other files", title)
        self.assertIn("kept only in the backup: owner, phase 1 colour", title)
        self.assertEqual(self.copy_op(ops).kind, "copytree")
        self.assertTrue(self.copy_op(ops).note.startswith("save workflow demo-flow; keeps 3 other files"))
        results = actions.apply(ops)
        self.assertTrue(all(r.ok for r in results))
        on_done(results)
        for rel in ("references/notes.md", "helper.py", "alias.py"):
            self.assertTrue(os.path.exists(os.path.join(dest, rel)), rel)
        self.assertTrue(os.path.islink(os.path.join(dest, "alias.py")))
        self.assertEqual(workflows.load_def(dest).description, "Edited description.")
        self.assertIn("Edited description.", read(os.path.join(dest, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(ops[0].dst, "references", "notes.md")))
        self.assertIn('"owner"', read(os.path.join(ops[0].dst, "workflow.json")))


if __name__ == "__main__":
    unittest.main()
