"""Skill categories and tags: the loader, the CLI columns and filters, and the real-repo coverage guard."""

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
            "tags_order": ["docs", "build", "fast", "extra"],
            "tags": {"alpha": ["build", "fast"], "beta": ["docs"], "gamma": ["docs", "build"],
                     "dup": ["extra"]},
        })

    def check_load_degrades_to_the_default_and_normalises_a_good_file(self) -> None:
        default = categories.Categories()
        self.assertEqual((default.order, dict(default.by_name)), (("Other",), {}))
        self.assertEqual((default.tags_order, dict(default.tags_by_name)), ((), {}))
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
        self.assertEqual((cats.tags_order, dict(cats.tags_by_name)), ((), {}))  # a file without tags
        self.use_fixture_categories()
        cats = categories.load(self.paths)
        self.assertEqual(categories.category_of(cats, "alpha"), "Tools")
        self.assertEqual(categories.category_of(cats, "unmapped"), "Other")
        self.assertEqual(categories.counts(cats, ["alpha", "beta", "gamma", "unmapped", "nope"]),
                         (("Tools", 1), ("Writing", 2), ("Other", 2)))
        # tags: loaded as declared, looked up per skill, never raising on an unmapped name
        self.assertEqual(cats.tags_order, ("docs", "build", "fast", "extra"))
        self.assertEqual(categories.tags_of(cats, "gamma"), ("docs", "build"))
        self.assertEqual(categories.tags_of(cats, "unmapped"), ())
        self.assertTrue(categories.has_tag(cats, "alpha", " FAST "))
        self.assertFalse(categories.has_tag(cats, "alpha", "docs"))
        self.assertEqual(categories.canonical(cats.tags_order, " Docs "), "docs")
        self.assertIsNone(categories.canonical(cats.tags_order, "nope"))
        self.assertEqual(categories.tag_counts(cats, ["alpha", "beta", "gamma", "unmapped"]),
                         (("docs", 2), ("build", 2), ("fast", 1), ("extra", 0)))
        # tag counts append a tag the order does not list, sorted, after the declared ones
        loose = categories.Categories(tags_order=("docs",), tags_by_name={"a": ("docs", "zz"), "b": ("yy",)})
        self.assertEqual(categories.tag_counts(loose, ["a", "b"]), (("docs", 1), ("yy", 1), ("zz", 1)))
        # bad tag data is dropped without touching the categories; used-but-undeclared tags are kept
        self.write_categories({"categories": {"alpha": "Tools"}, "tags_order": ["docs", "docs", 7, "x"],
                               "tags": {"alpha": ["fast", " fast ", 3, "Zeta"], "beta": "docs",
                                        "gamma": [], "dup": [None], "": ["x"]}})
        cats = categories.load(self.paths)
        self.assertEqual(dict(cats.by_name), {"alpha": "Tools"})
        self.assertEqual(cats.tags_order, ("docs", "x", "Zeta", "fast"))
        self.assertEqual(dict(cats.tags_by_name), {"alpha": ("fast", "Zeta")})
        for odd in ({"tags": ["alpha"], "tags_order": "docs"}, {"tags": {"alpha": {"a": 1}}, "tags_order": {}}):
            with self.subTest(odd=odd):
                self.write_categories({"categories": {"alpha": "Tools"}, **odd})
                cats = categories.load(self.paths)
                self.assertEqual((cats.tags_order, dict(cats.tags_by_name)), ((), {}))

    def check_status_and_list_json_rows_carry_the_category_and_tags(self) -> None:
        self.use_fixture_categories()
        status = {(r["scope"], r["name"]): r for r in self.json_of("status", "--json")}
        self.assertEqual(status[("shared", "alpha")]["category"], "Tools")
        self.assertEqual(status[("shared", "alpha")]["tags"], ["build", "fast"])
        self.assertEqual(status[("codex", "gamma")]["category"], "Writing")
        self.assertEqual(status[("codex", "gamma")]["tags"], ["docs", "build"])
        self.assertEqual(status[("shared", "foreign1")]["category"], "Other")
        self.assertEqual(status[("shared", "foreign1")]["tags"], [])
        listed = {(r["scope"], r["name"]): r for r in self.json_of("list", "--json")}
        self.assertEqual((listed[("shared", "beta")]["category"], listed[("shared", "beta")]["tags"]),
                         ("Writing", ["docs"]))
        self.assertEqual((listed[("claude", "dup")]["category"], listed[("claude", "dup")]["tags"]),
                         ("Other", ["extra"]))
        self.assertEqual(listed[("claude", "nometa")]["tags"], [])
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0].split()[:5], ["SCOPE", "NAME", "CATEGORY", "TAGS", "INSTALLED"])
        self.assertIn("docs, build", out)  # a skill's tags are comma-joined in the TAGS column
        code, out, _ = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertNotIn("CATEGORY", out)
        self.assertNotIn("TAGS", out)

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

    def check_tag_flag_filters_case_insensitively_and_combines_with_category(self) -> None:
        self.use_fixture_categories()
        for command in ("list", "status"):
            with self.subTest(command=command):
                rows = self.json_of(command, "--tag", "BuIlD", "--json")
                self.assertEqual(sorted((r["scope"], r["name"]) for r in rows),
                                 [("claude", "gamma"), ("codex", "gamma"), ("shared", "alpha")])
                self.assertTrue(all("build" in r["tags"] for r in rows))  # matched among several tags
                scoped = self.json_of(command, "--tag", "build", "--scope", "codex", "--json")
                self.assertEqual([(r["scope"], r["name"]) for r in scoped], [("codex", "gamma")])
                both = self.json_of(command, "--tag", "build", "--category", "tools", "--json")
                self.assertEqual([(r["scope"], r["name"]) for r in both], [("shared", "alpha")])
                self.assertEqual(self.json_of(command, "--tag", "docs", "--category", "tools", "--json"), [])
                code, _, err = self.run_cli(command, "--tag", "nonsense")
                self.assertEqual(code, 2)
                self.assertIn("unknown tag", err)
                self.assertIn("docs, build, fast, extra", err)
        code, out, _ = self.run_cli("status", "--tag", "fast")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("shared: 1 in repo, 1 installed", out)
        self.assertNotIn("beta", out)
        self.write_categories({"categories": {"alpha": "Tools"}})  # a file without tags: nothing to pick
        code, _, err = self.run_cli("list", "--tag", "docs")
        self.assertEqual(code, 2)
        self.assertIn("none are defined", err)

    def check_categories_command_counts_offered_and_installed_skills(self) -> None:
        self.use_fixture_categories()
        # offered: alpha | beta, gamma | dup, nometa, badname; on disk: alpha | beta (modified), gamma
        self.assertEqual(self.json_of("categories", "--json"), {
            "categories": [
                {"category": "Tools", "offered": 1, "installed": 1},
                {"category": "Writing", "offered": 2, "installed": 2},
                {"category": "Other", "offered": 3, "installed": 0},
            ],
            "tags": [
                {"tag": "docs", "offered": 2, "installed": 2},
                {"tag": "build", "offered": 2, "installed": 2},
                {"tag": "fast", "offered": 1, "installed": 1},
                {"tag": "extra", "offered": 1, "installed": 0},
            ],
        })
        code, out, _ = self.run_cli("categories")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["CATEGORY", "OFFERED", "INSTALLED"])
        self.assertEqual(lines[2].split(), ["Writing", "2", "2"])
        at = lines.index("")  # a blank line, then the tag table
        self.assertEqual(lines[at + 1].split(), ["TAG", "OFFERED", "INSTALLED"])
        self.assertEqual(lines[at + 3].split(), ["build", "2", "2"])
        self.assertEqual(lines[-1].split(), ["extra", "1", "0"])
        self.write_categories("not json")  # an unusable file leaves everything in "Other", no tags
        self.assertEqual(self.json_of("categories", "--json"),
                         {"categories": [{"category": "Other", "offered": 6, "installed": 3}], "tags": []})
        code, out, _ = self.run_cli("categories")
        self.assertEqual(code, 0)
        self.assertNotIn("TAG ", out)
        self.assertEqual({r["category"] for r in self.json_of("list", "--json")}, {"Other"})

    def test_categories_in_the_cli(self) -> None:
        self.run_scenarios(
            self.check_load_degrades_to_the_default_and_normalises_a_good_file,
            self.check_status_and_list_json_rows_carry_the_category_and_tags,
            self.check_category_flag_filters_case_insensitively_and_rejects_unknown_names,
            self.check_tag_flag_filters_case_insensitively_and_combines_with_category,
            self.check_categories_command_counts_offered_and_installed_skills)


class RealRepoCoverageTests(unittest.TestCase):
    """Guard: a skill added to the repo needs a category and tags in shared/skill-categories.json."""

    def skill_names(self, paths: Paths) -> set:
        names = set()
        for scope in ("shared", "claude", "codex"):
            root = paths.source_dir(scope)
            for entry in os.listdir(root):
                if os.path.isdir(os.path.join(root, entry)) and not entry.startswith(".") \
                        and not (scope == "claude" and entry == LEARNED):
                    names.add(entry)
        return names

    def test_every_skill_directory_has_a_category_and_tags(self) -> None:
        paths = Paths.detect()
        cats = categories.load(paths)
        names = self.skill_names(paths)
        with open(os.path.join(paths.repo_dir, categories.CATEGORIES_RELPATH), encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertGreater(len(cats.by_name), 0, "shared/skill-categories.json is missing or unusable")
        with self.subTest("every skill is mapped"):
            self.assertEqual(sorted(names - set(cats.by_name)), [],
                             "add these skills to shared/skill-categories.json")
        with self.subTest("no entry for a skill that is gone"):
            self.assertEqual(sorted(set(cats.by_name) - names), [])
        with self.subTest("every category is declared in order"):
            declared = set(raw["order"])
            self.assertEqual(sorted(set(cats.by_name.values()) - declared), [])
            self.assertIn(categories.DEFAULT_CATEGORY, declared)
        with self.subTest("the counts add up"):
            self.assertEqual(sum(n for _, n in categories.counts(cats, sorted(names))), len(names))
        with self.subTest("every skill has at least one tag"):
            self.assertEqual(sorted(names - set(cats.tags_by_name)), [],
                             "add these skills to \"tags\" in shared/skill-categories.json")
        with self.subTest("no tags for a skill that is gone"):
            self.assertEqual(sorted(set(cats.tags_by_name) - names), [])
        with self.subTest("every tag used is declared in tags_order"):
            declared_tags = raw["tags_order"]
            self.assertEqual(len(declared_tags), len(set(declared_tags)), "duplicate entry in tags_order")
            used = {tag for tags in cats.tags_by_name.values() for tag in tags}
            self.assertEqual(sorted(used - set(declared_tags)), [])
            self.assertEqual(cats.tags_order, tuple(declared_tags))
        with self.subTest("the tag counts add up"):
            self.assertEqual(sum(n for _, n in categories.tag_counts(cats, sorted(names))),
                             sum(len(tags) for tags in cats.tags_by_name.values()))


if __name__ == "__main__":
    unittest.main()
