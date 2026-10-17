"""Tests for installer.core.extras: catalog loading/validation, detection, install commands."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import tempfile
import unittest

from installer.core import capabilities, extras
from installer.core.extras import Extra, ExtraStatus, commands_for, detect, load, load_checked
from installer.core.paths import Paths
from installer.tests.fixtures import paths_for, write

SAMPLE = {
    "_comment": "External integrations the installer can detect and (on confirmation) install.",
    "extras": {
        "impeccable": {
            "title": "Impeccable - design vocabulary, refinement commands and design checks",
            "category": "design",
            "url": "https://impeccable.style/docs/",
            "tools": ["claude", "codex"],
            "install": ["npx impeccable install"],
            "after_install": {"claude": "run /impeccable init in a project",
                              "codex": "run $impeccable in a project"},
            "detect": {"any_paths": ["~/.claude/skills/impeccable",
                                     "~/.claude/commands/impeccable.md",
                                     "~/.codex/skills/impeccable"]},
        },
        "figma-mcp": {
            "title": "Figma MCP - live canvas and FigJam access for the agent",
            "category": "design",
            "url": "https://help.figma.com/hc/en-us/articles/39888612464151",
            "tools": ["claude", "codex"],
            "install_by_tool": {
                "claude": ["claude plugin install figma@claude-plugins-official"],
                "codex": ["codex mcp add figma --url https://mcp.figma.com/mcp"],
            },
            "detect": {"claude_mcp": "figma", "codex_mcp": "figma",
                       "claude_plugin": "figma@claude-plugins-official"},
        },
        "openai-slides": {
            "title": "OpenAI Slides skill (Codex catalog) - editable .pptx decks",
            "category": "presentations",
            "url": "https://github.com/openai/skills",
            "tools": ["codex"],
            "install": ["codex exec \"use $skill-installer to install slides from openai/skills\""],
            "detect": {"any_paths": ["~/.codex/skills/slides"]},
        },
    },
}

MCP_LIST = (
    "Checking MCP server health...\n\n"
    "context7: npx -y @upstash/context7-mcp - ✓ Connected\n"
    "figma: https://mcp.figma.com/mcp (HTTP) - ✓ Connected\n"
)


def done(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class StubRun:
    def __init__(self, result=None):
        self.result = done() if result is None else result
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def which_claude(name):
    return "/fake/bin/claude" if name == "claude" else None


def no_which(name):
    return None


class NoRun:
    """A runner that must never be called.

    It records calls instead of raising: extras swallows every exception from a detection
    method ("unknown"), so an AssertionError raised here would be swallowed too and the test
    could never fail. Only an assertion on `calls` is reliable.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return done()


class Fixture(unittest.TestCase):
    """A temp repo + home. self.paths points inside it; self.env sets HOME to the temp home."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.paths = paths_for(self.root)
        self.home = os.path.join(self.root, "home")
        self.env = {"HOME": self.home}

    def write_catalog(self, data):
        text = data if isinstance(data, str) else json.dumps(data)
        return write(os.path.join(self.paths.repo_dir, "shared", "extras.json"), text)

    def catalog(self):
        self.write_catalog(SAMPLE)
        return {e.key: e for e in load(self.paths)}

    def detect_checked(self, extra, paths=None, **kwargs):
        """detect() with defaults for env/run/which; a NoRun runner is asserted to be untouched."""
        kwargs.setdefault("env", self.env)
        kwargs.setdefault("run", NoRun())
        kwargs.setdefault("which", no_which)
        status = detect(extra, paths or self.paths, **kwargs)
        if isinstance(kwargs["run"], NoRun):
            self.assertEqual(kwargs["run"].calls, [], "the CLI must not be run here")
        return status

    def status(self, key, **kwargs):
        return self.detect_checked(self.catalog()[key], **kwargs).installed


class ExtrasTest(Fixture):
    def test_load_catalog(self):
        self.assertEqual(load(self.paths), ())
        self.assertEqual(load_checked(self.paths), ((), ()))
        for payload in ("", "{nope", "[]", '{"extras": []}', "{}", b"\xff\xfe\x00\x80 not utf-8"):
            with self.subTest(payload=payload):
                path = self.write_catalog("")
                with open(path, "wb") as fh:
                    fh.write(payload if isinstance(payload, bytes) else payload.encode())
                self.assertEqual(load(self.paths), ())
                self.assertEqual(len(load_checked(self.paths)[1]), 1)

        self.write_catalog(SAMPLE)
        loaded = load(self.paths)
        self.assertEqual([e.key for e in loaded], ["impeccable", "figma-mcp", "openai-slides"])
        impeccable, figma, slides = loaded
        self.assertEqual((impeccable.category, impeccable.tools, impeccable.install),
                         ("design", ("claude", "codex"), ("npx impeccable install",)))
        self.assertEqual(figma.install, ())
        self.assertEqual(figma.install_by_tool["codex"], ("codex mcp add figma --url https://mcp.figma.com/mcp",))
        self.assertEqual(slides.tools, ("codex",))
        self.assertEqual(load_checked(self.paths), (loaded, ()))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            figma.title = "x"
        for mapping in (figma.install_by_tool, figma.after_install, figma.detect):
            with self.assertRaises(TypeError):
                mapping["claude"] = ("x",)

        self.write_catalog({"extras": {"mini": {"title": "Mini"},
                                       "dup": {"title": "A", "tools": ["codex", "codex", "claude"]}}})
        mini, dup = load(self.paths)
        self.assertEqual((mini.category, mini.url, mini.tools, mini.install),
                         ("other", "", ("claude", "codex"), ()))
        self.assertEqual(dup.tools, ("codex", "claude"))

        bad = {
            "no-title": {"category": "x"}, "bad-tools": {"title": "T", "tools": ["gemini"]},
            "install-not-list": {"title": "T", "install": "npx x"},
            "ibt-key": {"title": "T", "install_by_tool": {"gemini": ["x"]}},
            "detect-type": {"title": "T", "detect": ["x"]}, "not-an-object": "text",
            "bad key!": {"title": "T"},
        }
        self.write_catalog({"extras": {**bad, "good": {"title": "Good"}}})
        loaded, problems = load_checked(self.paths)
        self.assertEqual([e.key for e in loaded], ["good"])
        self.assertEqual(len(problems), len(bad))
        for key in bad:
            self.assertTrue(any(repr(key) in p for p in problems), key)
        for problem in problems:
            self.assertTrue(problem.startswith("shared/extras.json"), problem)
            self.assertNotIn(self.root, problem)

        # never-delete: detection and loading code carries no destructive call
        for module in (extras, capabilities):
            with open(module.__file__, encoding="utf-8") as fh:
                source = fh.read()
            for needle in ("os.remove", "os.unlink", "os.rmdir", "rmtree", "shell=True", "input(", "print("):
                self.assertNotIn(needle, source, f"{module.__name__}: {needle}")

    def test_detect(self):
        def touch(tool, rel):
            write(os.path.join(self.home, "." + tool, rel), "x")

        # any_paths: per-tool state, no CLI needed (status() asserts the runner untouched)
        self.assertEqual(dict(self.status("impeccable")), {"claude": False, "codex": False})
        touch("claude", "commands/impeccable.md")
        touch("codex", "skills/impeccable/SKILL.md")
        self.assertEqual(dict(self.status("impeccable")), {"claude": True, "codex": True})
        self.assertEqual(dict(self.status("openai-slides")), {"codex": False})
        status = detect(self.catalog()["impeccable"], self.paths, env=self.env)
        self.assertIsInstance(status, ExtraStatus)
        with self.assertRaises(TypeError):
            status.installed["claude"] = True
        no_detect = Extra("e", "E", "x", "", ("claude", "codex"))
        self.assertEqual(dict(self.detect_checked(no_detect).installed), {"claude": None, "codex": None})
        everywhere = Extra("e", "E", "x", "", ("claude", "codex"), detect={"any_paths": ("~/tools/e",)})
        other = os.path.join(self.root, "other-home")
        write(os.path.join(other, "tools", "e"), "x")
        self.assertFalse(detect(everywhere, self.paths, env=self.env).installed["codex"])
        self.assertTrue(detect(everywhere, self.paths, env={"HOME": other}).installed["codex"])
        relocated = Paths(
            repo_dir=self.paths.repo_dir, agents_home=os.path.join(self.root, "agents"),
            claude_home=os.path.join(self.root, "elsewhere", "claude"),
            codex_home=os.path.join(self.root, "elsewhere", "codex"))
        write(os.path.join(relocated.claude_home, "skills", "impeccable", "SKILL.md"), "x")
        result = detect(self.catalog()["impeccable"], relocated, env=self.env).installed
        self.assertEqual(dict(result), {"claude": True, "codex": False})

        # claude_mcp: call contract, name matching, failures are unknown
        run = StubRun(done(MCP_LIST))
        self.assertTrue(self.status("figma-mcp", run=run, which=which_claude)["claude"])
        self.assertEqual([c for c, _ in run.calls], [["claude", "mcp", "list"]])
        kwargs = run.calls[0][1]
        self.assertEqual((kwargs["timeout"], kwargs["capture_output"], kwargs["check"], kwargs["env"]),
                         (5, True, False, self.env))
        self.assertNotIn("shell", kwargs)

        def claude_mcp(result):
            return self.status("figma-mcp", run=StubRun(result), which=which_claude)["claude"]

        for text, listed in (("context7: npx - ok\n", False), ("figma-desktop: npx x\n", False),
                             ("xfigma: y\n", False), ("  figma: x\n", True), ("other\nfigma - ok\n", True)):
            with self.subTest(text=text):
                self.assertIs(claude_mcp(done(text)), listed)
        for failure in (subprocess.TimeoutExpired(["claude"], 5), FileNotFoundError("x"),
                        RuntimeError("boom"), done("figma: x", "err", 1)):
            with self.subTest(failure=repr(failure)):
                self.assertIsNone(claude_mcp(failure))
        self.assertIsNone(self.status("figma-mcp", run=NoRun(), which=no_which)["claude"])
        # a codex-only extra never runs the claude CLI even when it is on PATH
        self.assertEqual(dict(self.status("openai-slides", run=NoRun(), which=which_claude)), {"codex": False})

        # codex_mcp: TOML table headers; a missing config is False, an unreadable one unknown
        def codex_mcp(text):
            write(os.path.join(self.paths.codex_home, "config.toml"), text)
            return self.status("figma-mcp", run=StubRun(done(MCP_LIST)), which=which_claude)["codex"]

        for header in ("[mcp_servers.figma]", '[mcp_servers."figma"]', "  [mcp_servers.figma]  # note",
                       "[mcp_servers.figma.env]"):
            self.assertTrue(codex_mcp(f"[other]\na = 1\n\n{header}\nx = 1\n"), header)
        for text in ("# [mcp_servers.figma]\n", "[mcp_servers.figma-desktop]\n", "[mcp_servers.xfigma]\n",
                     'note = "[mcp_servers.figma]"\n', ""):
            self.assertFalse(codex_mcp(text), text)
        codex_only = Extra("e", "E", "x", "", ("codex",), detect={"claude_mcp": "figma", "codex_mcp": "figma"})
        codex_mcp("[mcp_servers.figma]\n")
        result = self.detect_checked(codex_only, which=which_claude).installed  # asserts claude CLI not run
        self.assertEqual(dict(result), {"codex": True})
        self.assertFalse(detect(codex_only, relocated, env=self.env).installed["codex"], "missing config")
        os.makedirs(os.path.join(relocated.codex_home, "config.toml"))  # a directory, not a file
        self.assertIsNone(detect(codex_only, relocated, env=self.env).installed["codex"], "unreadable config")

        # claude_plugin: "key in enabledPlugins" counts as installed even when switched off
        key = "figma@claude-plugins-official"

        def settings(payload):
            text = payload if isinstance(payload, str) else json.dumps(payload)
            write(os.path.join(self.paths.claude_home, "settings.json"), text)

        self.assertFalse(claude_mcp(done("other: x\n")), "no settings file")
        for payload, installed in (({"enabledPlugins": {key: True}}, True), ({"enabledPlugins": {key: False}}, True),
                                   ({"enabledPlugins": {"other@market": True}}, False), ({"env": {}}, False)):
            with self.subTest(payload=payload):
                settings(payload)
                self.assertIs(claude_mcp(done("other: x\n")), installed)
        settings("{not json")
        self.assertIsNone(claude_mcp(done("other: x\n")), "invalid settings are unknown")
        settings({"enabledPlugins": {key: True}})
        self.assertTrue(claude_mcp(subprocess.TimeoutExpired(["claude"], 5)), "enabled beats an unknown listing")
        write(os.path.join(self.paths.codex_home, "config.toml"), "[mcp_servers.figma]\n")
        result = self.status("figma-mcp", run=StubRun(done(MCP_LIST)), which=which_claude)
        self.assertEqual(dict(result), {"claude": True, "codex": True})
        settings({"enabledPlugins": {}})
        self.assertIsNone(claude_mcp(subprocess.TimeoutExpired(["claude"], 5)), "unknown blocks False")

    def test_commands_for(self):
        cat = self.catalog()
        self.assertEqual(commands_for(cat["impeccable"], "claude"), ("npx impeccable install",))
        self.assertEqual(commands_for(cat["figma-mcp"], "claude"),
                         ("claude plugin install figma@claude-plugins-official",))
        self.assertEqual(commands_for(cat["figma-mcp"], "codex"),
                         ("codex mcp add figma --url https://mcp.figma.com/mcp",))
        self.assertEqual(commands_for(cat["openai-slides"], "claude"), ())
        self.assertEqual(commands_for(cat["impeccable"], "gemini"), ())
        extra = Extra("e", "E", "x", "", ("claude", "codex"), install=("do it",),
                      install_by_tool={"claude": ("claude only",), "codex": ()})
        self.assertEqual(commands_for(extra, "claude"), ("claude only",))
        self.assertEqual(commands_for(extra, "codex"), ("do it",))
        self.assertEqual(commands_for(Extra("e", "E", "x", "", ("claude",)), "claude"), ())


if __name__ == "__main__":
    unittest.main()
