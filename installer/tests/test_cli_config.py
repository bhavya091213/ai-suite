"""Tests for installer.cli: config, caps, sections, edit, doctor, render and render-tree."""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

from installer.core import capabilities
from installer.tests import fixtures
from installer.tests.test_cli import PROBED, CliTestCase


class ConfigCommandTests(CliTestCase):
    def get(self, key: str) -> str:
        return self.run_cli("config", "get", key)[1]

    def check_config_path_get_and_list(self) -> None:
        code, out, _ = self.run_cli("config", "path")
        self.assertEqual((code, out.strip()), (0, self.agents("config.json")))
        self.assertEqual(self.get("tools.claude"), "auto\n")
        self.assertEqual(self.get("guardrails.never_delete"), "true\n")
        self.assertEqual(self.get("paths.obsidian_vaults"), "(none)\n")
        code, out, _ = self.run_cli("config", "get", "tools")
        self.assertEqual((code, json.loads(out)), (0, {"claude": "auto", "codex": "auto"}))
        self.assertEqual(self.run_cli("config", "get", "nope.key")[0], 2)
        code, out, _ = self.run_cli("config", "list")
        self.assertEqual(code, 0)
        self.assertIn("tools.claude", out)
        self.assertIn("defaults", out)
        self.assertEqual(self.json_of("config", "list", "--json")["tools"]["codex"], "auto")

    def check_config_set_writes_the_file_backs_it_up_and_reset_restores_the_default(self) -> None:
        code, out, err = self.run_cli("config", "set", "tools.claude", "off", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("auto -> off", out)
        with open(self.agents("config.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["tools"]["claude"], "off")
        for key, value, shown, default in (("tools.claude", "off", "off\n", "auto\n"),
                                           ("guardrails.disabled_hooks", "a:b,c:d", "a:b, c:d\n",
                                            "(none)\n")):
            with self.subTest(key=key):
                self.assertEqual(self.run_cli("config", "set", key, value, "--yes")[0], 0)
                self.assertEqual(self.get(key), shown)
                code, _, err = self.run_cli("config", "reset", key, "--yes")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.get(key), default)
        self.assertGreaterEqual(len(self.backups("config-*/config.json")), 1)

    def check_config_set_rejects_bad_keys_and_values_and_a_no_op_writes_nothing(self) -> None:
        for argv in (("nope.key", "1"), ("tools.claude", "maybe"),
                     ("guardrails.context_budget_tokens", "abc"),
                     ("guardrails.never_delete", "perhaps"), ("tools", "x")):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli("config", "set", *argv, "--yes")
                self.assertEqual(code, 2)
                self.assertTrue(err.strip())
        code, out, _ = self.run_cli("config", "set", "tools.claude", "auto", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)
        self.assertFalse(os.path.exists(self.agents("config.json")))

    def check_edit_runs_the_editor_on_the_target_file_and_warns_before_rules_are_overwritten(self) -> None:
        for rel in ("config.json", "LOCAL.md", "RULES.md"):
            fixtures.write(self.agents(rel), "x\n")
        with mock.patch("installer.core.editor.edit_file", return_value=0) as edit:
            self.assertEqual(self.run_cli("config", "edit")[0], 0)
            self.assertEqual(self.run_cli("edit", "local")[0], 0)
            code, out, _ = self.run_cli("edit", "rules")
        self.assertEqual(code, 0)
        self.assertIn("overwritten", out)
        self.assertEqual([c.args[0] for c in edit.call_args_list],
                         [self.agents(rel) for rel in ("config.json", "LOCAL.md", "RULES.md")])

    def check_edit_failures_are_reported_not_raised(self) -> None:
        code, _, err = self.run_cli("edit", "settings")  # the file does not exist
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)
        self.assertEqual(self.run_cli("edit", "nonsense")[0], 2)
        fixtures.write(self.agents("config.json"), "{}\n")
        with mock.patch("installer.core.editor.edit_file", side_effect=OSError("no such editor")):
            code, _, err = self.run_cli("edit", "config")
        self.assertEqual(code, 1)
        self.assertIn("no such editor", err)

    def check_sections_follow_the_tool_settings(self) -> None:
        for claude, codex, expected in (("auto", "auto", "shared claude codex\n"),  # both are detected
                                        ("on", "off", "shared claude\n"), ("off", "on", "shared codex\n"),
                                        ("off", "off", "shared\n")):
            with self.subTest(claude=claude, codex=codex):
                self.run_cli("config", "set", "tools.claude", claude, "--yes")
                self.run_cli("config", "set", "tools.codex", codex, "--yes")
                self.assertEqual(self.run_cli("sections")[1], expected)

    def test_config_commands(self) -> None:
        self.run_scenarios(
            self.check_config_path_get_and_list,
            self.check_config_set_writes_the_file_backs_it_up_and_reset_restores_the_default,
            self.check_config_set_rejects_bad_keys_and_values_and_a_no_op_writes_nothing,
            self.check_edit_runs_the_editor_on_the_target_file_and_warns_before_rules_are_overwritten,
            self.check_edit_failures_are_reported_not_raised,
            self.check_sections_follow_the_tool_settings)


class RealProbeTests(CliTestCase):
    real_probe = True

    def test_caps_json_reports_what_the_machine_probe_found(self) -> None:
        data = self.json_of("caps", "--json")
        self.assertEqual(set(data["items"]), set(PROBED))
        self.assertTrue(data["items"]["python"]["present"])
        self.assertEqual(data["items"]["python"]["name"], "python")


class CapsAndDoctorTests(CliTestCase):
    def doctor_json(self, *argv: str):
        code, out, err = self.run_cli(*argv, "doctor", "--json")
        return code, json.loads(out), err

    def check_caps_table_lists_each_probe_and_the_install_hint_when_git_is_missing(self) -> None:
        code, out, _ = self.run_cli("caps")
        self.assertEqual(code, 0)
        self.assertIn("python", out)

        def fake(*args, **kwargs):
            items = {"git": capabilities.Capability("git", False, None, None, "not on PATH")}
            return capabilities.Capabilities(items=items)
        with mock.patch.object(capabilities, "probe", fake):
            code, out, _ = self.run_cli("caps")
        self.assertEqual(code, 0)
        self.assertIn("git is missing", out)

    def check_doctor_is_clean_on_the_fixture_in_text_and_json(self) -> None:
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 0, err + out)
        self.assertIn("python", out)
        self.assertIn("no blockers", out)
        code, data, err = self.doctor_json()
        self.assertEqual((code, data["blockers"]), (0, 0), err)
        self.assertEqual(set(data), {"checks", "blockers"})
        for check in data["checks"]:
            self.assertEqual(set(check), {"name", "state", "text"})
            self.assertIn(check["state"], ("ok", "warn", "blocker"))
        self.assertIn("python", {c["name"] for c in data["checks"]})

    def check_doctor_fails_on_a_blocker_and_the_json_report_agrees(self) -> None:
        nowhere = os.path.join(self.root, "nowhere")
        code, out, _ = self.run_cli("--repo", nowhere, "doctor")
        self.assertEqual(code, 1)
        self.assertIn("repo directory missing", out)
        code, data, _ = self.doctor_json("--repo", nowhere)
        self.assertEqual((code, data["blockers"]), (1, 1))
        blockers = [c for c in data["checks"] if c["state"] == "blocker"]
        self.assertEqual([c["name"] for c in blockers], ["paths"])
        self.assertIn("repo directory missing", blockers[0]["text"])
        fixtures.write(self.agents("config.json"), "{not json")
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", out)

    def check_doctor_warns_but_passes_on_a_semantic_config_problem(self) -> None:
        fixtures.write(self.agents("config.json"), json.dumps({"tools": {"claude": "sometimes"}}))
        code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertIn("[warn] config: tools.claude", out)
        code, data, _ = self.doctor_json()
        self.assertEqual((code, data["blockers"]), (0, 0))
        self.assertIn("warn", {c["state"] for c in data["checks"]})

    def check_doctor_reports_settings_json_warnings(self) -> None:
        settings = {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}}
        fixtures.write(os.path.join(self.home, ".claude", "settings.json"), json.dumps(settings))
        self.run_cli("config", "set", "tools.claude", "on", "--yes")

        def no_headroom(*args, **kwargs):
            return capabilities.Capabilities(items={
                "headroom": capabilities.Capability("headroom", False, None, None, "absent")})
        with mock.patch.object(capabilities, "probe", no_headroom):
            code, out, _ = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertIn("headroom is not installed", out)

    def test_caps_and_doctor(self) -> None:
        self.run_scenarios(
            self.check_caps_table_lists_each_probe_and_the_install_hint_when_git_is_missing,
            self.check_doctor_is_clean_on_the_fixture_in_text_and_json,
            self.check_doctor_fails_on_a_blocker_and_the_json_report_agrees,
            self.check_doctor_warns_but_passes_on_a_semantic_config_problem,
            self.check_doctor_reports_settings_json_warnings)


class RenderCommandTests(CliTestCase):
    def write_repo(self, rel: str, text: str) -> str:
        return fixtures.write(os.path.join(self.paths.repo_dir, rel), text)

    def set_tool(self, tool: str, value: str) -> None:
        self.assertEqual(self.run_cli("config", "set", "tools." + tool, value, "--yes")[0], 0)

    def check_render_prints_a_template_and_leaves_a_plain_file_alone(self) -> None:
        path = self.write_repo("shared/page.md",
                               "<!-- installer:template -->\nclaude is {{ config.tools.claude }}\n")
        code, out, _ = self.run_cli("render", path)
        self.assertEqual((code, out), (0, "claude is auto\n"))
        path = self.write_repo("shared/plain.md", "keep {{ this }} as is\n")
        code, out, _ = self.run_cli("render", path)
        self.assertEqual((code, out), (0, "keep {{ this }} as is\n"))

    def check_render_exits_3_when_a_requirement_is_unmet_and_drops_the_marker_when_met(self) -> None:
        path = self.write_repo("claude-code/commands/x.md", "<!-- installer:requires codex -->\nbody\n")
        dir_file = self.write_repo("claude-code/scripts/pipe/run.sh", "echo hi\n")
        self.write_repo("claude-code/scripts/pipe/.installer-requires", "codex\n")
        self.set_tool("codex", "off")
        code, out, err = self.run_cli("render", path)
        self.assertEqual((code, out), (3, ""))
        self.assertIn("excluded", err)
        self.assertEqual(self.run_cli("render", dir_file)[0], 3)  # a directory requirement file counts too
        self.set_tool("codex", "on")
        code, out, _ = self.run_cli("render", path)
        self.assertEqual((code, out), (0, "body\n"))

    def check_render_applies_rewrite_rules_however_the_repo_and_file_are_spelled(self) -> None:
        agent = self.write_repo("claude-code/agents/planner.md",
                                "---\nname: planner\nmodel: opus\n---\nbody\n")
        self.run_cli("config", "set", "subagents.claude.heavy", "claude-heavy-x", "--yes")
        link = os.path.join(self.root, "repo-link")
        try:
            os.symlink(self.paths.repo_dir, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available here")
        via_link = os.path.join(link, "claude-code", "agents", "planner.md")
        expected = "---\nname: planner\nmodel: claude-heavy-x\n---\nbody\n"
        for repo, file in ((self.paths.repo_dir, via_link), (link, agent), (link, via_link)):
            with self.subTest(repo=repo, file=file):
                code, out, err = self.run_raw("--repo", repo, "--home", self.home, "render", file)
                self.assertEqual((code, out), (0, expected), err)
        self.addCleanup(os.chdir, os.getcwd())  # a file given relative to the working directory
        os.chdir(os.path.join(self.paths.repo_dir, "claude-code"))
        code, out, err = self.run_cli("render", os.path.join("agents", "planner.md"))
        self.assertEqual((code, out), (0, expected), err)

    def check_render_reports_files_outside_the_repo_missing_files_and_bad_templates(self) -> None:
        outside = fixtures.write(os.path.join(self.root, "outside", "planner.md"),
                                 "---\nname: planner\nmodel: opus\n---\n")
        code, out, err = self.run_cli("render", outside)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("outside the repo", err)
        link = os.path.join(self.paths.repo_dir, "shared", "escape.md")  # a link out of the repo is outside too
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pass
        else:
            self.assertEqual(self.run_cli("render", link)[0], 2)
        self.assertEqual(self.run_cli("render", os.path.join(self.root, "missing.md"))[0], 2)
        path = self.write_repo("shared/bad.md", "<!-- installer:template -->\n{% if x %}never closed\n")
        code, _, err = self.run_cli("render", path)
        self.assertEqual(code, 1)
        self.assertIn("bad.md", err)

    def check_render_tree_mirrors_the_directory_and_refuses_to_overwrite_it(self) -> None:
        self.write_repo("shared/docs/a.md", "<!-- installer:template -->\nhi {{ config.tools.codex }}\n")
        self.write_repo("shared/docs/b.txt", "plain\n")
        self.write_repo("shared/docs/c.md", "<!-- installer:requires gemini -->\nnever\n")
        self.set_tool("codex", "on")
        out_dir = os.path.join(self.root, "stage", "docs")
        src = os.path.join(self.paths.repo_dir, "shared", "docs")
        code, out, err = self.run_cli("render-tree", src, out_dir, "--rel", "shared/docs")
        self.assertEqual(code, 0, err)
        self.assertIn("rendered 1, copied 1, excluded", out)
        with open(os.path.join(out_dir, "a.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "hi on\n")
        self.assertFalse(os.path.exists(os.path.join(out_dir, "c.md")))
        code, _, err = self.run_cli("render-tree", src, out_dir, "--rel", "shared/docs")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        code, out, _ = self.run_cli("render-tree", src, os.path.join(self.root, "stage2"),
                                    "--rel", "shared/docs", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["rendered"], ["shared/docs/a.md"])
        self.assertEqual(self.run_cli("render-tree", src, os.path.join(self.root, "stage3"))[0], 2)  # --rel is required

    def test_render_and_render_tree(self) -> None:
        self.run_scenarios(
            self.check_render_prints_a_template_and_leaves_a_plain_file_alone,
            self.check_render_exits_3_when_a_requirement_is_unmet_and_drops_the_marker_when_met,
            self.check_render_applies_rewrite_rules_however_the_repo_and_file_are_spelled,
            self.check_render_reports_files_outside_the_repo_missing_files_and_bad_templates,
            self.check_render_tree_mirrors_the_directory_and_refuses_to_overwrite_it)


class ExtrasHomeIsolationTests(CliTestCase):
    """`--home` must sandbox extras detection and the commands extras install runs."""

    def write_catalog(self, **extras: dict) -> None:
        entries = {key: {"title": key, "category": "t", "url": "https://example.invalid/" + key,
                         "tools": ["claude", "codex"], "install": ["true"], **spec}
                   for key, spec in extras.items()}
        fixtures.write(os.path.join(self.paths.repo_dir, "shared", "extras.json"),
                       json.dumps({"extras": entries}))

    def installed(self) -> dict:
        return {row["key"]: row["installed"] for row in self.json_of("extras", "list", "--json")}

    def check_detection_reads_the_fixture_home_not_the_process_home(self) -> None:
        self.write_catalog(
            plain={"detect": {"any_paths": ["~/iso-marker"]}},
            dotdir={"tools": ["claude"], "detect": {"any_paths": ["~/.claude/skills/iso-extra"]}})
        decoy = os.path.join(self.root, "process-home")  # stands in for the real home
        fixtures.write(os.path.join(decoy, "iso-marker"), "x")
        fixtures.write(os.path.join(decoy, ".claude", "skills", "iso-extra", "SKILL.md"), "x")
        os.environ["HOME"] = decoy
        self.assertEqual(self.installed(), {"plain": {"claude": False, "codex": False},
                                            "dotdir": {"claude": False}})
        fixtures.write(os.path.join(self.home, "iso-marker"), "x")
        fixtures.write(os.path.join(self.home, ".claude", "skills", "iso-extra", "SKILL.md"), "x")
        self.assertEqual(self.installed(), {"plain": {"claude": True, "codex": True},
                                            "dotdir": {"claude": True}})

    def check_install_runs_with_the_fixture_home_in_its_environment_and_looks_programs_up_on_the_context_path(
            self) -> None:
        marker = os.path.join(self.root, "seen.txt")
        script = ("import os; open(r'%s', 'w').write('|'.join("
                  "os.environ.get(k, '-') for k in ('HOME', 'CLAUDE_CONFIG_DIR')))" % marker)
        ran = os.path.join(self.root, "ran.txt")
        tool_dir = os.path.join(self.root, "bin")
        tool = fixtures.write(os.path.join(tool_dir, "iso-tool"), "#!/bin/sh\necho ok > '%s'\n" % ran)
        os.chmod(tool, 0o755)
        self.write_catalog(demo={"install": ['%s -c "%s"' % (sys.executable, script)]},
                           lookup={"install": ["iso-tool"]})
        os.environ["HOME"] = os.path.join(self.root, "process-home")
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.root, "process-home", "claude-elsewhere")
        code, _, err = self.run_cli("extras", "install", "demo", "--tool", "claude", "--yes")
        self.assertEqual(code, 0, err)
        with open(marker, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.home + "|-")  # --home wins over exported tool homes
        env = dict(os.environ, PATH=tool_dir + os.pathsep + os.environ.get("PATH", ""))
        code, _, err = self.run_raw("--repo", self.paths.repo_dir, "--home", self.home,
                                    "extras", "install", "lookup", "--tool", "claude", "--yes", env=env)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(ran))

    def test_extras_and_the_home_sandbox(self) -> None:
        self.run_scenarios(
            self.check_detection_reads_the_fixture_home_not_the_process_home,
            self.check_install_runs_with_the_fixture_home_in_its_environment_and_looks_programs_up_on_the_context_path)


if __name__ == "__main__":
    unittest.main()
