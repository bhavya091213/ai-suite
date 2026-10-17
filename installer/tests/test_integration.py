"""End-to-end checks that cross module boundaries.

1. scan_catalog + scan_installed + status.compute on the shared fixture: the documented
   state of every fixture entry.
2. The REAL repo trees (shared/, claude-code/, codex/) rendered with two contexts
   (every tool present, then codex and headroom absent).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Dict, Mapping, Optional, Tuple

from installer.core import capabilities, config, render, skills, status
from installer.core.paths import Paths
from installer.core.types import LinkState, SkillStatus, State
from installer.tests import fixtures

try:  # tomllib exists on Python 3.11+ only
    import tomllib
except ImportError:  # pragma: no cover - depends on the interpreter
    tomllib = None  # type: ignore[assignment]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TREES = ("shared", "claude-code", "codex")
Key = Tuple[str, str]


class FixtureWorldTests(unittest.TestCase):
    """The fixture documented in installer/tests/fixtures.py, seen through the real core."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.paths = fixtures.build(cls._tmp.name)
        cls.catalog, cls.repo_issues = skills.scan_catalog(cls.paths)
        cls.installed = skills.scan_installed(cls.paths)
        cls.rows = status.compute(cls.catalog, cls.installed, cls.paths, {}, cls.repo_issues)
        cls.by_key: Dict[Key, SkillStatus] = {row.key: row for row in cls.rows}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def row(self, scope: str, name: str) -> SkillStatus:
        self.assertIn((scope, name), self.by_key)
        return self.by_key[(scope, name)]

    def link_states(self, scope: str, name: str) -> Mapping[str, LinkState]:
        return {link.consumer: link.state for link in self.row(scope, name).links}

    def test_catalog_has_exactly_the_documented_skills(self) -> None:
        self.assertEqual(sorted(self.catalog), [
            ("claude", "dup"), ("claude", "gamma"), ("claude", "nometa"),
            ("codex", "badname"), ("codex", "gamma"),
            ("shared", "alpha"), ("shared", "beta"), ("shared", "dup"),
        ])

    def test_alpha_is_installed_with_both_links_ok(self) -> None:
        row = self.row("shared", "alpha")
        self.assertEqual(row.state, State.INSTALLED)
        self.assertEqual(self.link_states("shared", "alpha"),
                         {"claude": LinkState.OK, "codex": LinkState.OK})
        self.assertEqual((row.issues, row.duplicates), ((), ()))

    def test_beta_is_modified_with_a_shadowing_claude_dir_and_a_broken_codex_link(self) -> None:
        row = self.row("shared", "beta")
        self.assertEqual(row.state, State.MODIFIED)
        self.assertEqual(self.link_states("shared", "beta"),
                         {"claude": LinkState.REAL_DIR, "codex": LinkState.BROKEN})
        self.assertTrue(any(d.startswith("claude: real directory") for d in row.duplicates))
        self.assertTrue(any(i.startswith("claude: real directory shadows") for i in row.issues))
        self.assertTrue(any(i.startswith("codex: broken symlink") for i in row.issues))

    def test_beta_duplicate_note_compares_the_claude_copy_with_the_edited_shared_copy(self) -> None:
        # The claude copy equals the REPO beta, but the shared copy was edited locally,
        # so against the shared copy it is a different-content duplicate.
        row = self.row("shared", "beta")
        note = next(d for d in row.duplicates if d.startswith("claude: real directory"))
        self.assertIn(status.DIFFERENT_COPY, note)
        self.assertNotIn(status.IDENTICAL_COPY, note)

    def test_foreign_entries(self) -> None:
        self.assertEqual(self.row("shared", "foreign1").state, State.FOREIGN)
        ghost = self.row("claude", "ghost")
        self.assertEqual(ghost.state, State.FOREIGN)
        self.assertEqual(ghost.installed.kind, "broken-symlink")
        self.assertTrue(any("broken symlink" in issue for issue in ghost.issues))
        stray = self.row("codex", "stray.txt")
        self.assertEqual(stray.state, State.FOREIGN)
        self.assertEqual(stray.installed.kind, "file")
        self.assertTrue(stray.issues)

    def test_platform_variants(self) -> None:
        self.assertEqual(self.row("claude", "gamma").state, State.INSTALLED)
        self.assertEqual(self.row("codex", "gamma").state, State.MODIFIED)
        self.assertEqual(self.row("claude", "gamma").links, ())

    def test_tool_managed_entries_are_ignored(self) -> None:
        for key in (("claude", "synced"), ("claude", "learned"), ("codex", ".system")):
            row = self.row(*key)
            self.assertEqual(row.state, State.IGNORED, key)
            self.assertIsNotNone(row.installed.ignored_reason)

    def test_repo_duplicate_scope_is_noted_on_both_rows(self) -> None:
        for key in (("shared", "dup"), ("claude", "dup")):
            self.assertTrue(any("claude/dup duplicates shared/dup" in d
                                for d in self.row(*key).duplicates), key)
        self.assertEqual(self.row("shared", "dup").state, State.NOT_INSTALLED)

    def test_frontmatter_problems_are_reported(self) -> None:
        nometa = self.row("claude", "nometa")
        self.assertTrue(any("lacks name and description" in i for i in nometa.issues))
        badname = self.row("codex", "badname")
        self.assertTrue(any("other-name" in i for i in badname.issues))
        kinds = {(i.scope, i.name): i.kind for i in self.repo_issues}
        self.assertEqual(kinds[("claude", "nometa")], "missing-frontmatter")
        self.assertEqual(kinds[("codex", "badname")], "name-mismatch")
        self.assertEqual(kinds[("claude", "dup")], "duplicate-scope")

    def test_every_entry_is_accounted_for_and_nothing_else_appears(self) -> None:
        self.assertEqual(sorted(self.by_key), [
            ("claude", "dup"), ("claude", "gamma"), ("claude", "ghost"), ("claude", "learned"),
            ("claude", "nometa"), ("claude", "synced"),
            ("codex", ".system"), ("codex", "badname"), ("codex", "gamma"), ("codex", "stray.txt"),
            ("shared", "alpha"), ("shared", "beta"), ("shared", "dup"), ("shared", "foreign1"),
        ])

    def test_counts_per_scope(self) -> None:
        by_scope = {c.scope: c for c in status.counts(self.rows)}
        shared = by_scope["shared"]
        self.assertEqual((shared.available, shared.installed, shared.modified, shared.missing,
                          shared.foreign), (3, 1, 1, 1, 1))
        self.assertEqual(by_scope["codex"].modified, 1)
        self.assertEqual(by_scope["claude"].installed, 1)

    def test_problems_lists_exactly_the_rows_with_something_to_say(self) -> None:
        keys = {row.key for row in status.problems(self.rows)}
        self.assertEqual(keys, {
            ("shared", "beta"), ("shared", "dup"), ("claude", "dup"), ("claude", "ghost"),
            ("claude", "nometa"), ("codex", "badname"), ("codex", "stray.txt"),
        })


def fake_caps(absent: Tuple[str, ...] = ()) -> Mapping:
    """A capabilities context in which every probe is present except `absent`."""
    return {name: {"present": name not in absent, "version": "1.0", "path": "/usr/bin/" + name,
                   "detail": ""} for name in capabilities.PROBES}


class RealRepoRenderTests(unittest.TestCase):
    """Render the real shared/, claude-code/ and codex/ trees and check the results hold up."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = cls._tmp.name
        cls.out: Dict[str, str] = {}
        cls.reports: Dict[str, Dict[str, render.RenderReport]] = {}
        paths = Paths.detect(repo_dir=REPO_ROOT, env={}, home=os.path.join(base, "home"))
        for label, absent in (("on", ()), ("off", ("codex", "headroom"))):
            context = render.build_context(config.DEFAULTS, fake_caps(absent), paths,
                                           env={"HOME": os.path.join(base, "home"), "USER": "tester"})
            cls.out[label] = os.path.join(base, label)
            cls.reports[label] = {
                tree: render.render_tree(os.path.join(REPO_ROOT, tree),
                                         os.path.join(cls.out[label], tree), context, tree)
                for tree in TREES
            }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def path(self, label: str, *parts: str) -> str:
        return os.path.join(self.out[label], *parts)

    def read(self, label: str, *parts: str) -> str:
        with open(self.path(label, *parts), encoding="utf-8") as handle:
            return handle.read()

    def files(self, label: str, suffix: str, skip_skills: bool = False):
        for tree in TREES:
            for folder, dirs, names in os.walk(self.path(label, tree)):
                if skip_skills and os.path.basename(folder) == "skills":
                    dirs[:] = []
                    continue
                for name in names:
                    if name.endswith(suffix):
                        yield os.path.join(folder, name)

    def test_the_context_resolves_as_intended(self) -> None:
        paths = Paths.detect(repo_dir=REPO_ROOT, env={}, home="/nonexistent-home")
        on = render.build_context(config.DEFAULTS, fake_caps(), paths, env={})
        off = render.build_context(config.DEFAULTS, fake_caps(("codex", "headroom")), paths, env={})
        self.assertEqual((on["profile"]["review_backend"], on["profile"]["headroom"]), ("codex", True))
        self.assertEqual((off["profile"]["review_backend"], off["profile"]["headroom"]), ("claude", False))

    def test_no_template_tags_survive_in_rendered_markdown(self) -> None:
        for label in ("on", "off"):
            for tree, report in self.reports[label].items():
                for rel in report.rendered:
                    if not rel.endswith(".md"):
                        continue
                    text = self.read(label, tree, rel[len(tree) + 1:])
                    self.assertNotIn("{{", text, f"{label}: {rel}")
                    self.assertNotIn("{%", text, f"{label}: {rel}")

    def test_rendering_produced_no_warnings(self) -> None:
        for label in ("on", "off"):
            for tree, report in self.reports[label].items():
                self.assertEqual(report.warnings, (), f"{label}/{tree}")

    def test_orchestrate_mentions_the_codex_runner_only_when_codex_is_on(self) -> None:
        self.assertIn("codex-review-runner", self.read("on", "claude-code", "commands", "orchestrate.md"))
        self.assertNotIn("codex-review-runner", self.read("off", "claude-code", "commands", "orchestrate.md"))

    def test_codex_only_files_are_absent_from_the_off_render(self) -> None:
        self.assertFalse(os.path.exists(self.path("off", "claude-code", "agents", "codex-review-runner.md")))
        self.assertFalse(os.path.exists(self.path("off", "claude-code", "scripts", "codex-review-pipeline")))
        self.assertTrue(os.path.isfile(self.path("on", "claude-code", "agents", "codex-review-runner.md")))
        self.assertTrue(os.path.isdir(self.path("on", "claude-code", "scripts", "codex-review-pipeline")))
        excluded = {rel for rel, _ in self.reports["off"]["claude-code"].excluded}
        self.assertIn("claude-code/agents/codex-review-runner.md", excluded)
        self.assertIn("claude-code/scripts/codex-review-pipeline", excluded)

    def test_every_rendered_json_file_parses(self) -> None:
        for label in ("on", "off"):
            found = list(self.files(label, ".json", skip_skills=True))
            self.assertTrue(found)
            for path in found:
                with open(path, encoding="utf-8") as handle:
                    try:
                        json.load(handle)
                    except ValueError as exc:
                        self.fail(f"{path}: {exc}")

    def load_json(self, label: str, *parts: str) -> Mapping:
        return json.loads(self.read(label, *parts))

    def test_headroom_and_codex_are_stripped_from_the_off_settings(self) -> None:
        on = self.load_json("on", "claude-code", "settings.example.json")
        off = self.load_json("off", "claude-code", "settings.example.json")
        self.assertIn("ANTHROPIC_BASE_URL", on["env"])
        self.assertIn("headroom@headroom-marketplace", on["enabledPlugins"])
        self.assertIn("codex@openai-codex", on["enabledPlugins"])
        self.assertNotIn("ANTHROPIC_BASE_URL", off["env"])
        self.assertNotIn("headroom@headroom-marketplace", off["enabledPlugins"])
        self.assertNotIn("codex@openai-codex", off["enabledPlugins"])
        self.assertNotIn("headroom-marketplace", off["extraKnownMarketplaces"])
        self.assertNotIn("headroom", json.dumps(off["hooks"]).lower())
        self.assertEqual(off["env"]["ECC_HOOK_PROFILE"], "standard")

    def test_headroom_server_is_dropped_from_the_off_mcp_catalog(self) -> None:
        on = self.load_json("on", "shared", "mcp-servers.json")["servers"]
        off = self.load_json("off", "shared", "mcp-servers.json")["servers"]
        self.assertIn("headroom", on)
        self.assertNotIn("headroom", off)
        self.assertIn("context7", off)

    @unittest.skipIf(tomllib is None, "tomllib needs Python 3.11+")
    def test_every_rendered_toml_file_parses(self) -> None:
        for label in ("on", "off"):
            found = list(self.files(label, ".toml", skip_skills=True))
            self.assertTrue(found)
            for path in found:
                with open(path, "rb") as handle:
                    try:
                        tomllib.load(handle)
                    except ValueError as exc:
                        self.fail(f"{path}: {exc}")

    def test_rendered_rules_contain_the_environment_section(self) -> None:
        for label in ("on", "off"):
            self.assertIn("## F. Environment", self.read(label, "shared", "RULES.md"))

    def test_codex_agents_file_embeds_the_rendered_rules(self) -> None:
        for label in ("on", "off"):
            text = self.read(label, "codex", "AGENTS.md")
            self.assertIn("BEGIN SHARED RULES", text)
            self.assertNotIn("{{", text)


if __name__ == "__main__":
    unittest.main()
