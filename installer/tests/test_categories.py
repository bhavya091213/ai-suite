"""Skill categories: the loader, the CLI columns and filters, and the real-repo coverage guard."""

from __future__ import annotations

import json
import os
import unittest

from installer.core import categories
from installer.core.paths import Paths
from installer.tests import fixtures
from installer.tests.test_cli import CliTestCase

LEARNED = "learned"  # claude-code/skills/learned is a landing directory, not a skill


class CategoriesCliTests(CliTestCase):
    """The loader and the status / list / categories commands, on the fixture repo."""

    def write_categories(self, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        fixtures.write(os.path.join(self.paths.repo_dir, categories.CATEGORIES_RELPATH), text)

    def use_fixture_categories(self) -> None:
        self.write_categories({
            "order": ["Tools", "Writing", "Other"],
            "categories": {"alpha": "Tools", "beta": "Writing", "gamma": "Writing"},
        })

    def check_load_degrades_to_the_default_and_normalises_a_good_file(self) -> None:
        default = categories.Categories()
        self.assertEqual((default.order, dict(default.by_name)), (("Other",), {}))
        self.assertEqual(categories.load(self.paths), default)  # no file in the fixture repo
        for bad in ("not json", "[]", '{"categories": ["alpha"]}', "{", ""):
            with self.subTest(bad=bad):
                self.write_categories(bad)
                self.assertEqual(categories.load(self.paths), default)
        self.write_categories({"order": ["Tools", "Tools", 7, "Writing"],
                               "categories": {"alpha": "Tools", "beta": " Writing ", "dup": "Zeta",
                                              "gamma": 5, "": "Tools"}})
        cats = categories.load(self.paths)
        self.assertEqual(cats.order, ("Tools", "Writing", "Zeta", "Other"))
        self.assertEqual(dict(cats.by_name), {"alpha": "Tools", "beta": "Writing", "dup": "Zeta"})
        self.use_fixture_categories()
        cats = categories.load(self.paths)
        self.assertEqual(categories.category_of(cats, "alpha"), "Tools")
        self.assertEqual(categories.category_of(cats, "unmapped"), "Other")
        self.assertEqual(categories.counts(cats, ["alpha", "beta", "gamma", "unmapped", "nope"]),
                         (("Tools", 1), ("Writing", 2), ("Other", 2)))

    def check_status_and_list_json_rows_carry_the_category(self) -> None:
        self.use_fixture_categories()
        status = {(r["scope"], r["name"]): r["category"] for r in self.json_of("status", "--json")}
        self.assertEqual(status[("shared", "alpha")], "Tools")
        self.assertEqual(status[("codex", "gamma")], "Writing")
        self.assertEqual(status[("shared", "foreign1")], "Other")
        listed = {(r["scope"], r["name"]): r["category"] for r in self.json_of("list", "--json")}
        self.assertEqual(listed[("shared", "beta")], "Writing")
        self.assertEqual(listed[("claude", "dup")], "Other")
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("CATEGORY", out.splitlines()[0])
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertNotIn("CATEGORY", out)

    def check_category_flag_filters_case_insensitively_and_rejects_unknown_names(self) -> None:
        self.use_fixture_categories()
        for command in ("list", "status"):
            with self.subTest(command=command):
                rows = self.json_of(command, "--category", "wRiTiNg", "--json")
                self.assertEqual(sorted((r["scope"], r["name"]) for r in rows),
                                 [("claude", "gamma"), ("codex", "gamma"), ("shared", "beta")])
                self.assertEqual({r["category"] for r in rows}, {"Writing"})
                scoped = self.json_of(command, "--category", "Writing", "--scope", "codex", "--json")
                self.assertEqual([(r["scope"], r["name"]) for r in scoped], [("codex", "gamma")])
                code, _, err = self.run_cli(command, "--category", "nonsense")
                self.assertEqual(code, 2)
                self.assertIn("unknown category", err)
                self.assertIn("Tools, Writing, Other", err)
        code, out, _ = self.run_cli("status", "--category", "tools")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("shared: 1 in repo, 1 installed", out)  # the counts line follows the filter
        self.assertNotIn("beta", out)

    def check_categories_command_counts_offered_and_installed_skills(self) -> None:
        self.use_fixture_categories()
        # offered: alpha | beta, gamma | dup, nometa, badname; on disk: alpha | beta (modified), gamma
        self.assertEqual(self.json_of("categories", "--json"), [
            {"category": "Tools", "offered": 1, "installed": 1},
            {"category": "Writing", "offered": 2, "installed": 2},
            {"category": "Other", "offered": 3, "installed": 0},
        ])
        code, out, _ = self.run_cli("categories")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0].split(), ["CATEGORY", "OFFERED", "INSTALLED"])
        self.assertEqual(out.splitlines()[2].split(), ["Writing", "2", "2"])
        self.write_categories("not json")  # an unusable file leaves everything in "Other"
        self.assertEqual(self.json_of("categories", "--json"),
                         [{"category": "Other", "offered": 6, "installed": 3}])
        self.assertEqual({r["category"] for r in self.json_of("list", "--json")}, {"Other"})

    def test_categories_in_the_cli(self) -> None:
        self.run_scenarios(
            self.check_load_degrades_to_the_default_and_normalises_a_good_file,
            self.check_status_and_list_json_rows_carry_the_category,
            self.check_category_flag_filters_case_insensitively_and_rejects_unknown_names,
            self.check_categories_command_counts_offered_and_installed_skills)


class RealRepoCoverageTests(unittest.TestCase):
    """Guard: a skill added to the repo needs an entry in shared/skill-categories.json."""

    def skill_names(self, paths: Paths) -> set:
        names = set()
        for scope in ("shared", "claude", "codex"):
            root = paths.source_dir(scope)
            for entry in os.listdir(root):
                if os.path.isdir(os.path.join(root, entry)) and not entry.startswith(".") \
                        and not (scope == "claude" and entry == LEARNED):
                    names.add(entry)
        return names

    def test_every_skill_directory_has_a_category(self) -> None:
        paths = Paths.detect()
        cats = categories.load(paths)
        names = self.skill_names(paths)
        self.assertGreater(len(cats.by_name), 0, "shared/skill-categories.json is missing or unusable")
        with self.subTest("every skill is mapped"):
            self.assertEqual(sorted(names - set(cats.by_name)), [],
                             "add these skills to shared/skill-categories.json")
        with self.subTest("no entry for a skill that is gone"):
            self.assertEqual(sorted(set(cats.by_name) - names), [])
        with self.subTest("every category is declared in order"):
            with open(os.path.join(paths.repo_dir, categories.CATEGORIES_RELPATH), encoding="utf-8") as fh:
                declared = set(json.load(fh)["order"])
            self.assertEqual(sorted(set(cats.by_name.values()) - declared), [])
            self.assertIn(categories.DEFAULT_CATEGORY, declared)
        with self.subTest("the counts add up"):
            self.assertEqual(sum(n for _, n in categories.counts(cats, sorted(names))), len(names))


if __name__ == "__main__":
    unittest.main()
