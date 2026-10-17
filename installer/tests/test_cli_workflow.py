"""`workflow` CLI subcommands, driven in-process on the fixture repo and home."""

from __future__ import annotations

import glob
import json
import os
import tempfile
import unittest
from typing import Any, Dict, Optional
from unittest import mock

from installer.core import skills, workflows
from installer.tests import test_cli

NAME = "demo-flow"
MARKER = workflows.MARKER


def definition(**changes: Any) -> Dict[str, Any]:
    """A valid workflow definition (as JSON data) over the fixture skills alpha and beta."""
    base: Dict[str, Any] = {
        "name": NAME,
        "description": "Demo workflow for the CLI tests.",
        "triggers": ["run the demo", "demo flow"],
        "phases": [
            {"name": "Plan", "goal": "Decide what to do.", "skills": ["alpha"],
             "steps": ["Read the brief."], "outputs": ["plan.md"], "gate": True,
             "gate_text": "the user signs off the plan"},
            {"name": "Do", "goal": "Do it.", "skills": ["beta"], "outputs": ["result.txt"]},
        ],
    }
    base.update(changes)
    return base


def read(*parts: str) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return handle.read()


class WorkflowCliCase(test_cli.CliTestCase):
    def setUp(self) -> None:
        stage = mock.patch.object(tempfile, "tempdir", None)  # restored when the test ends
        stage.start()
        self.addCleanup(stage.stop)
        super().setUp()

    def fresh(self) -> None:
        # save stages into tempfile.mkdtemp(); keep that inside this test's temp dir
        tempfile.tempdir = None
        super().fresh()
        tempfile.tempdir = self.root

    def write_def(self, data: Optional[Dict[str, Any]] = None, filename: str = "wf.json") -> str:
        path = os.path.join(self.root, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(definition() if data is None else data, handle, indent=2)
        return path

    def save(self, data: Optional[Dict[str, Any]] = None, filename: str = "wf.json"):
        return self.run_cli("workflow", "save", self.write_def(data, filename), "--yes")

    def installed_dir(self, name: str = NAME) -> str:
        return self.agents("skills", name)

    def write_installed(self, name: str, text: str) -> str:
        skill_dir = self.installed_dir(name)
        os.makedirs(skill_dir, exist_ok=True)
        path = os.path.join(skill_dir, workflows.WORKFLOW_FILE)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def backup_dirs(self, label: str, *parts: str) -> list:
        return glob.glob(os.path.join(self.home, ".agents", "backups", f"{label}-*", *parts))


class ExampleTests(WorkflowCliCase):
    def check_example_prints_text_and_json_and_the_json_saves_as_is(self) -> None:
        code, out, _ = self.run_cli("workflow", "example")
        self.assertEqual(code, 0)
        for needle in ("research-design-build", "1. Research", "2. Design", "3. Build",
                       "deep-research", "[gate]", "example --json"):
            self.assertIn(needle, out)
        code, out, _ = self.run_cli("workflow", "example", "--json")
        self.assertEqual(code, 0)
        wf = workflows.from_json(out)
        self.assertEqual(wf, workflows.example())
        self.assertEqual(out, workflows.to_json(wf))
        used = frozenset(s for phase in wf.phases for s in phase.skills)
        self.assertEqual(workflows.validate(wf, used), ())
        # against the (small) fixture catalog the only findings are unknown-skill warnings
        found = workflows.validate(wf, workflows.known_skill_names(self.paths))
        self.assertTrue(all(m.startswith(workflows.WARNING_PREFIX) for m in found))
        path = os.path.join(self.root, "example.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(out)
        code, _, err = self.run_cli("workflow", "save", path, "--yes")
        self.assertEqual(code, 0, err)  # warnings print but do not block
        self.assertIn("warning:", err)
        self.assertNotIn("error:", err)
        self.assertTrue(os.path.isfile(self.installed_dir("research-design-build") + "/SKILL.md"))


    def check_save_yes_creates_the_skill_files_and_both_links(self) -> None:
        code, out, err = self.save()
        self.assertEqual(code, 0, err)
        skill_dir = self.installed_dir()
        for rel in ("SKILL.md", "workflow.json", os.path.join("agents", "openai.yaml")):
            self.assertTrue(os.path.isfile(os.path.join(skill_dir, rel)), rel)
        self.assertIn(MARKER, read(skill_dir, "SKILL.md"))
        self.assertEqual(workflows.load_def(skill_dir).name, NAME)
        for tool in ("claude", "codex"):
            link = self.consumer(tool, NAME)
            self.assertTrue(os.path.islink(link), tool)
            self.assertEqual(os.path.realpath(link), os.path.realpath(skill_dir))
        self.assertIn("copytree", out)
        self.assertIn("symlink", out)
        self.assertIn("Done.", out)
        self.assertIn("Links: claude=ok codex=ok", out)
        row = {(r["scope"], r["name"]): r for r in self.json_of("status", "--json")}[("shared", NAME)]
        self.assertEqual(row["state"], "foreign")  # a shared skill with good links and no issues
        self.assertEqual([link["state"] for link in row["links"]], ["ok", "ok"])
        self.assertEqual(row["issues"], [])

    def check_saving_again_backs_the_old_copy_up_keeps_the_links_and_notes_the_files_it_drops(self) -> None:
        self.save()
        skill_dir = self.installed_dir()
        os.makedirs(os.path.join(skill_dir, "references"))
        for rel in (os.path.join("references", "mine.md"), "notes.txt"):
            with open(os.path.join(skill_dir, rel), "w", encoding="utf-8") as handle:
                handle.write("mine\n")
        edited = definition(description="Edited description.",
                            phases=definition()["phases"] + [
                                {"name": "Ship", "skills": [], "steps": ["Release it."]}])
        code, out, err = self.save(edited)
        self.assertEqual(code, 0, err)
        saved = workflows.load_def(skill_dir)
        self.assertEqual((saved.description, len(saved.phases)), ("Edited description.", 3))
        self.assertIn("Edited description.", read(skill_dir, "SKILL.md"))
        old = self.backup_dirs("installer", "shared", NAME, "workflow.json")
        self.assertEqual(len(old), 1, out)
        self.assertIn("Demo workflow for the CLI tests.", read(old[0]))
        self.assertIn("Backups went under", out)
        self.assertNotIn("symlink", out)  # links were already fine
        self.assertIn("Links: claude=ok codex=ok", out)
        self.assertIn("holds 2 file(s) a saved workflow does not carry over", out)
        self.assertIn("notes.txt, references/mine.md", out)
        self.assertLess(out.index("note: "), out.index("Plan ("))
        self.assertFalse(os.path.exists(os.path.join(skill_dir, "references")))
        kept = self.backup_dirs("installer", "shared", NAME, "references", "mine.md")
        self.assertEqual((len(kept), read(kept[0])), (1, "mine\n"))
        _, out, _ = self.save()
        self.assertNotIn("does not carry over", out)  # only the rendered files this time
        for index in range(7):
            with open(os.path.join(skill_dir, f"extra{index}.txt"), "w", encoding="utf-8") as handle:
                handle.write("x\n")
        _, out, _ = self.save()
        self.assertIn("holds 7 file(s)", out)  # the list of names is capped
        self.assertIn("extra4.txt, and 2 more)", out)
        self.assertNotIn("extra5.txt", out)

    def check_validation_errors_exit_2_print_each_and_install_nothing(self) -> None:
        bad = definition(description="", phases=[
            {"name": "One", "skills": []}, {"name": "one", "skills": ["alpha"]}])
        code, out, err = self.save(bad)
        self.assertEqual(code, 2)
        self.assertIn("error: description is empty", err)
        self.assertIn("error: phase 1 ('One') has neither skills nor steps", err)
        self.assertIn("duplicate phase name", err)
        self.assertNotIn("Plan (", out)
        self.assertFalse(os.path.lexists(self.installed_dir()))
        self.assertEqual(self.save(definition(phases=[]))[0], 2)
        self.assertFalse(os.path.lexists(self.installed_dir()))

    def check_invalid_and_tool_managed_names_exit_2_and_install_nothing(self) -> None:
        # macOS is case-insensitive by default: "Learned" would land on the real "learned".
        keep = os.path.join(self.installed_dir("learned"), "USER.txt")
        os.makedirs(os.path.dirname(keep))
        with open(keep, "w", encoding="utf-8") as handle:
            handle.write("generated by /learn\n")
        before = sorted(os.listdir(self.agents("skills")))
        refused = [(bad, "invalid workflow name") for bad in ("bad/name", "..", ".hidden", "../escape")]
        refused += [(name, "tool-managed") for name in ("learned", "LEARNED", "Synced", ".system")]
        for name, message in refused:
            with self.subTest(name=name):
                code, _, err = self.save(definition(name=name))
                self.assertEqual(code, 2)
                self.assertIn(message, err)
                self.assertEqual(sorted(os.listdir(self.agents("skills"))), before)
                self.assertEqual(read(keep), "generated by /learn\n")
        self.assertFalse(os.path.lexists(self.agents("escape")))
        self.assertEqual(self.backup_dirs("installer"), [])

    def check_unreadable_or_malformed_files_exit_2_with_the_reason(self) -> None:
        deep = os.path.join(self.root, "deep.json")
        for text, name in (("{not json", "bad.json"), ("[" * 200000, "deep.json")):
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        for path, needle in ((os.path.join(self.root, "missing.json"), "cannot read"),
                             (os.path.join(self.root, "bad.json"), "not valid JSON"),
                             (deep, "nested too deeply"),
                             (self.write_def({"phases": []}), "name"),
                             (self.root, "")):
            with self.subTest(path=os.path.basename(path)):
                code, _, err = self.run_cli("workflow", "save", path, "--yes")
                self.assertEqual(code, 2)
                self.assertIn(needle, err)
                self.assertNotIn("RecursionError", err)
        self.assertFalse(os.path.lexists(self.installed_dir(NAME)))

    def check_save_needs_confirmation_and_changes_nothing_on_a_dry_run_or_a_no(self) -> None:
        path = self.write_def()
        code, out, err = self.run_cli("workflow", "save", path)
        self.assertEqual(code, 2)
        self.assertIn("--yes", err)
        self.assertIn("Plan (", out)
        code, out, _ = self.run_cli("workflow", "save", path, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Dry run only", out)
        code, out, _ = self.run_cli("workflow", "save", path, stdin="n\n", tty=True)
        self.assertEqual(code, 1)
        self.assertIn("Aborted.", out)
        self.assertFalse(os.path.lexists(self.installed_dir()))
        for tool in ("claude", "codex"):
            self.assertFalse(os.path.lexists(self.consumer(tool, NAME)))
        code, _, _ = self.run_cli("workflow", "save", path, stdin="y\n", tty=True)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(self.installed_dir()))

    def check_saving_over_a_plain_skill_is_refused_until_it_is_retired(self) -> None:
        # foreign1 is a shared skill that is not in the repo; alpha is an installed repo skill.
        for name in ("foreign1", "alpha"):
            before = read(self.installed_dir(name), "SKILL.md")
            for extra in (["--yes"], ["--dry-run"]):
                with self.subTest(name=name, flags=extra):
                    path = self.write_def(definition(name=name))
                    code, out, err = self.run_cli("workflow", "save", path, *extra)
                    self.assertEqual(code, 2)
                    self.assertIn(f"shared/{name} already exists and is not a workflow", err)
                    self.assertIn("nothing was saved", err)
                    self.assertIn(f"retire {name} --scope shared", err)
                    self.assertNotIn("Plan (", out)
                    self.assertEqual(read(self.installed_dir(name), "SKILL.md"), before)
                    self.assertFalse(os.path.exists(
                        os.path.join(self.installed_dir(name), workflows.WORKFLOW_FILE)))
        self.assertEqual(self.backup_dirs("installer"), [])
        self.assertEqual(glob.glob(os.path.join(self.root, "installer-workflow-*")), [])  # nothing staged
        self.assertTrue(os.path.islink(self.consumer("claude", "alpha")))
        code, _, err = self.run_cli("retire", "foreign1", "--scope", "shared", "--yes")  # the explicit way
        self.assertEqual(code, 0, err)
        moved = self.backup_dirs("retired-skills", "shared", "foreign1", "SKILL.md")
        self.assertEqual(len(moved), 1)
        self.assertIn("Not in the repo", read(moved[0]))
        code, out, err = self.save(definition(name="foreign1"))
        self.assertEqual(code, 0, err)
        self.assertEqual(workflows.load_def(self.installed_dir("foreign1")).name, "foreign1")
        self.assertNotIn("does not carry over", out)

    def check_saving_over_a_file_or_a_dangling_link_is_refused(self) -> None:
        skills_dir = self.agents("skills")
        with open(os.path.join(skills_dir, "afile"), "w", encoding="utf-8") as handle:
            handle.write("not a skill\n")
        os.symlink(os.path.join(self.root, "nowhere"), os.path.join(skills_dir, "dangling"))
        for name in ("afile", "dangling"):
            with self.subTest(name=name):
                code, _, err = self.save(definition(name=name))
                self.assertEqual(code, 2)
                self.assertIn("is not a workflow", err)
                self.assertTrue(os.path.lexists(os.path.join(skills_dir, name)))
        self.assertEqual(read(skills_dir, "afile"), "not a skill\n")
        self.assertTrue(os.path.islink(os.path.join(skills_dir, "dangling")))
        self.assertEqual(self.backup_dirs("installer"), [])

    def check_an_existing_real_dir_in_a_tool_is_not_touched_and_the_other_link_is_made(self) -> None:
        real = self.consumer("claude", NAME)
        os.makedirs(real)
        with open(os.path.join(real, "SKILL.md"), "w", encoding="utf-8") as handle:
            handle.write("---\nname: demo-flow\ndescription: shadow\n---\n")
        code, out, err = self.save()
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.islink(real))
        self.assertIn("shadow", read(real, "SKILL.md"))
        self.assertTrue(os.path.islink(self.consumer("codex", NAME)))
        self.assertIn("claude=real-dir", out)

    def test_example_and_save(self) -> None:
        self.run_scenarios(
            self.check_example_prints_text_and_json_and_the_json_saves_as_is,
            self.check_save_yes_creates_the_skill_files_and_both_links,
            self.check_saving_again_backs_the_old_copy_up_keeps_the_links_and_notes_the_files_it_drops,
            self.check_validation_errors_exit_2_print_each_and_install_nothing,
            self.check_invalid_and_tool_managed_names_exit_2_and_install_nothing,
            self.check_unreadable_or_malformed_files_exit_2_with_the_reason,
            self.check_save_needs_confirmation_and_changes_nothing_on_a_dry_run_or_a_no,
            self.check_saving_over_a_plain_skill_is_refused_until_it_is_retired,
            self.check_saving_over_a_file_or_a_dangling_link_is_refused,
            self.check_an_existing_real_dir_in_a_tool_is_not_touched_and_the_other_link_is_made)


class ReadCommandTests(WorkflowCliCase):
    def check_list_explains_how_to_start_and_skips_files_that_are_not_workflows(self) -> None:
        code, out, _ = self.run_cli("workflow", "list")
        self.assertEqual(code, 0)
        self.assertIn("No workflows installed", out)
        self.write_installed("garbage", "{not json")
        self.assertEqual(self.json_of("workflow", "list", "--json"), [])

    def check_list_shows_text_and_json_and_flags_invalid_definitions(self) -> None:
        self.save()
        code, out, _ = self.run_cli("workflow", "list")
        self.assertEqual(code, 0)
        row = next(line.split() for line in out.splitlines() if NAME in line)
        self.assertEqual(row[1:5], [NAME, "2", "2", "valid"])
        data = self.json_of("workflow", "list", "--json")
        self.assertEqual(len(data), 1)
        self.assertEqual((data[0]["name"], data[0]["phases"], data[0]["skills"], data[0]["valid"]),
                         (NAME, 2, 2, True))
        self.assertEqual((data[0]["errors"], data[0]["path"]), ([], self.installed_dir()))
        self.write_installed("empty-flow", json.dumps(definition(name="empty-flow", phases=[])))
        data = {r["name"]: r for r in self.json_of("workflow", "list", "--json")}
        self.assertFalse(data["empty-flow"]["valid"])
        self.assertIn("workflow has no phases", data["empty-flow"]["errors"])
        _, out, _ = self.run_cli("workflow", "list")
        line = next(l for l in out.splitlines() if "empty-flow" in l)
        self.assertIn("invalid", line)
        self.assertIn("1 error(s)", line)

    def check_show_prints_the_definition_the_validation_and_warnings(self) -> None:
        self.save()
        code, out, _ = self.run_cli("workflow", "show", NAME)
        self.assertEqual(code, 0)
        for needle in (NAME, "Demo workflow for the CLI tests.", "run the demo, demo flow",
                       "1. Plan  [gate]", "2. Do", "skills:  alpha", "Read the brief.",
                       "gate:    the user signs off the plan", "outputs: result.txt",
                       "validation:", "  ok"):
            self.assertIn(needle, out)
        data = definition(name="warn-flow")
        data["phases"][0]["skills"] = ["alpha", "ghost-skill"]
        self.save(data)
        code, out, _ = self.run_cli("workflow", "show", "warn-flow")
        self.assertEqual(code, 0)
        self.assertIn("warning: skill 'ghost-skill'", out)

    def check_show_exits_2_with_the_error_text_for_bad_or_unparseable_definitions(self) -> None:
        self.write_installed("bad-flow", json.dumps(definition(name="bad-flow", description="",
                                                               phases=[])))
        code, out, err = self.run_cli("workflow", "show", "bad-flow")
        self.assertEqual(code, 2)
        self.assertIn("error: description is empty", out + err)
        self.assertIn("error: workflow has no phases", out + err)
        self.write_installed("broken-flow", "{not json")
        code, _, err = self.run_cli("workflow", "show", "broken-flow")
        self.assertEqual(code, 2)
        self.assertIn("broken-flow/workflow.json", err)
        self.assertIn("not valid JSON", err)

    def decoy(self, *parts: str) -> str:
        """A readable workflow.json outside (or hidden within) the installed skills."""
        folder = os.path.join(*parts)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, workflows.WORKFLOW_FILE)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(definition(name="decoy")))
        return path

    def check_commands_reject_non_workflows_unknown_names_and_names_that_escape_the_skills_dir(self) -> None:
        # Each escaping name resolves to a real, valid workflow.json, so only the name check stops it.
        outside_abs = os.path.join(self.root, "abs-decoy")
        decoys = {
            "../outside": self.decoy(self.agents("outside")),
            "..": self.decoy(self.agents()),
            ".hidden": self.decoy(self.installed_dir(".hidden")),
            outside_abs: self.decoy(outside_abs),
        }
        cases = [(name, "not an installed workflow") for name in ("alpha", "nothere")]
        cases += [(name, "invalid workflow name") for name in decoys]
        for command in ("show", "render", "retire", "push"):
            extra = ["--yes"] if command in ("retire", "push") else []
            for name, message in cases:
                with self.subTest(command=command, name=name):
                    code, out, err = self.run_cli("workflow", command, name, *extra)
                    self.assertEqual(code, 2)
                    self.assertTrue(err.startswith("error:"), err)
                    self.assertIn(message, err)
                    self.assertEqual(out, "")
        self.assertTrue(os.path.isdir(self.installed_dir("alpha")))
        for name, path in decoys.items():
            self.assertTrue(os.path.isfile(path), name)  # nothing was moved or copied away

    def check_render_matches_the_installed_skill_md_and_follows_the_json_edited_in_place(self) -> None:
        self.save()
        code, out, _ = self.run_cli("workflow", "render", NAME)
        self.assertEqual(code, 0)
        self.assertEqual(out, read(self.installed_dir(), "SKILL.md"))
        self.assertIn(MARKER, out)
        self.assertIn("## Phase 1 - Plan", out)
        self.assertIn("## Handback", out)
        wf = workflows.load_def(self.installed_dir())
        with open(os.path.join(self.installed_dir(), "workflow.json"), "w", encoding="utf-8") as handle:
            handle.write(workflows.to_json(
                workflows.WorkflowDef(wf.name, "Changed by hand.", wf.triggers, wf.phases)))
        _, out, _ = self.run_cli("workflow", "render", NAME)
        self.assertIn("Changed by hand.", out)

    def test_list_show_and_render(self) -> None:
        self.run_scenarios(
            self.check_list_explains_how_to_start_and_skips_files_that_are_not_workflows,
            self.check_list_shows_text_and_json_and_flags_invalid_definitions,
            self.check_show_prints_the_definition_the_validation_and_warnings,
            self.check_show_exits_2_with_the_error_text_for_bad_or_unparseable_definitions,
            self.check_commands_reject_non_workflows_unknown_names_and_names_that_escape_the_skills_dir,
            self.check_render_matches_the_installed_skill_md_and_follows_the_json_edited_in_place)


class RetireAndPushTests(WorkflowCliCase):
    def repo_copy(self, *parts: str) -> str:
        return os.path.join(self.paths.repo_dir, "shared", "skills", NAME, *parts)

    def check_retire_yes_moves_the_dir_and_links_under_the_retired_root_and_a_second_retire_exits_2(self) -> None:
        self.save()
        code, out, err = self.run_cli("workflow", "retire", NAME, "--yes")
        self.assertEqual(code, 0, err)
        self.assertFalse(os.path.lexists(self.installed_dir()))
        moved = self.backup_dirs("retired-skills", "shared", NAME, "workflow.json")
        self.assertEqual(len(moved), 1)
        self.assertEqual(workflows.from_json(read(moved[0])).name, NAME)
        for tool in ("claude", "codex"):
            self.assertFalse(os.path.lexists(self.consumer(tool, NAME)), tool)
            links = self.backup_dirs("retired-skills", tool, NAME)
            self.assertEqual(len(links), 1, tool)
            self.assertTrue(os.path.islink(links[0]))
        self.assertIn("Backups went under", out)
        self.assertEqual(self.json_of("workflow", "list", "--json"), [])
        code, _, err = self.run_cli("workflow", "retire", NAME, "--yes")
        self.assertEqual(code, 2)
        self.assertIn("not an installed workflow", err)

    def check_push_yes_copies_the_workflow_into_the_repo_and_pushing_again_backs_the_copy_up(self) -> None:
        self.save()
        self.assertFalse(os.path.exists(self.repo_copy()))
        code, out, err = self.run_cli("workflow", "push", NAME, "--yes")
        self.assertEqual(code, 0, err)
        for rel in ("SKILL.md", "workflow.json", os.path.join("agents", "openai.yaml")):
            self.assertTrue(os.path.isfile(self.repo_copy(rel)), rel)
        self.assertEqual(read(self.repo_copy("workflow.json")),
                         read(self.installed_dir(), "workflow.json"))
        self.assertIn("push shared/" + NAME, out)
        catalog, _issues = skills.scan_catalog(self.paths)
        self.assertIn(("shared", NAME), catalog)
        code, out, err = self.run_cli("workflow", "push", NAME, "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.backup_dirs("installer", "repo", "shared", NAME, "SKILL.md")), 1, out)
        self.assertTrue(os.path.isfile(self.repo_copy("SKILL.md")))

    def check_retire_and_push_need_confirmation_and_change_nothing_on_a_dry_run(self) -> None:
        self.save()
        for command in ("retire", "push"):
            with self.subTest(command=command):
                code, _, err = self.run_cli("workflow", command, NAME)
                self.assertEqual(code, 2)
                self.assertIn("--yes", err)
                code, out, _ = self.run_cli("workflow", command, NAME, "--dry-run")
                self.assertEqual(code, 0)
                self.assertIn("Dry run only", out)
        code, out, _ = self.run_cli("workflow", "retire", NAME, stdin="n\n", tty=True)
        self.assertEqual(code, 1)
        self.assertIn("Aborted.", out)
        self.assertTrue(os.path.isdir(self.installed_dir()))
        self.assertTrue(os.path.islink(self.consumer("claude", NAME)))
        self.assertFalse(os.path.exists(self.repo_copy()))

    def check_workflow_without_an_action_is_a_usage_error(self) -> None:
        code, _, err = self.run_cli("workflow")
        self.assertEqual(code, 2)
        self.assertIn("ACTION", err)

    def check_module_never_deletes_anything(self) -> None:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cli_workflow.py")
        source = read(path)
        for call in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", "rm -rf"):
            self.assertNotIn(call, source)
        self.assertLess(len(source.splitlines()), 500)
        self.assertNotIn("/Users" + "/", source)

    def test_retire_push_usage_and_source_guards(self) -> None:
        self.run_scenarios(
            self.check_retire_yes_moves_the_dir_and_links_under_the_retired_root_and_a_second_retire_exits_2,
            self.check_push_yes_copies_the_workflow_into_the_repo_and_pushing_again_backs_the_copy_up,
            self.check_retire_and_push_need_confirmation_and_change_nothing_on_a_dry_run,
            self.check_workflow_without_an_action_is_a_usage_error,
            self.check_module_never_deletes_anything)


if __name__ == "__main__":
    unittest.main()
