"""Tests for installer.core.rewrite: the six path-specific rules, run on the REAL repo files."""

from __future__ import annotations

import glob
import json
import os
import unittest

from installer.core.rewrite import rewrite

try:  # tomllib exists on Python 3.11+ only
    import tomllib
except ImportError:  # pragma: no cover - depends on interpreter
    tomllib = None

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

PLANNER = "claude-code/agents/planner.md"
IMPLEMENTER = "claude-code/agents/unit-implementer.md"
REVIEWER = "codex/agents/reviewer.toml"
EXPLORER = "codex/agents/explorer.toml"
CONFIG = "codex/config.example.toml"
SETTINGS = "claude-code/settings.example.json"
HOOKS = "codex/hooks.json"
MCP = "shared/mcp-servers.json"
ALL_RULE_FILES = (PLANNER, REVIEWER, CONFIG, SETTINGS, HOOKS, MCP)
AGENT_X = "claude-code/agents/x.md"
ROLE_X = "codex/agents/x.toml"


def read_repo(rel_path):
    with open(os.path.join(REPO, *rel_path.split("/")), encoding="utf-8") as handle:
        return handle.read()


def make_context(headroom=True, codex=True, claude=True):
    """A context shaped like render.build_context output (only the keys rewrite reads)."""
    return {
        "config": {"subagents": {"codex": {"max_threads": 8, "max_depth": 2}}},
        "profile": {
            "claude": claude, "codex": codex, "headroom": headroom,
            "claude_heavy": "claude-heavy-x", "claude_light": "claude-light-x",
            "claude_trivial": "claude-trivial-x", "codex_model": "codex-model-x",
            "codex_heavy": "effort-heavy", "codex_light": "effort-light",
            "codex_trivial": "effort-trivial", "hook_profile": "strict",
            "disabled_hooks": ("pre:bash:tmux-reminder", "post:edit:format"),
        },
    }


def real(rel, context):
    """Rewrite the real repo file `rel`."""
    return rewrite(rel, read_repo(rel), context)


def loaded(rel, context, text=None):
    """JSON-decoded rewrite of `rel` (the real file unless `text` is given)."""
    return json.loads(rewrite(rel, read_repo(rel) if text is None else text, context))


def changed_lines(before, after):
    """(old, new) pairs for lines that differ; asserts the line count is unchanged."""
    old, new = before.split("\n"), after.split("\n")
    assert len(old) == len(new), "line count changed"
    return [(a, b) for a, b in zip(old, new) if a != b]


def parse_toml(text):
    return tomllib.loads(text) if tomllib is not None else None


def hook(command):
    return {"type": "command", "command": command}


def names(pattern):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(REPO, *pattern)))


class RewriteTests(unittest.TestCase):
    def test_agent_model_rules(self):
        """Rules 1 and 2: Claude agent `model:` and Codex role `model` / effort lines."""
        context = make_context()
        self.assertEqual(changed_lines(read_repo(PLANNER), real(PLANNER, context)),
                         [("model: opus", "model: claude-heavy-x")])
        self.assertEqual(changed_lines(read_repo(IMPLEMENTER), real(IMPLEMENTER, context)),
                         [("model: sonnet", "model: claude-light-x")])
        self.assertEqual(rewrite(AGENT_X, "---\nname: x\nmodel: haiku\n---\nbody\n", context),
                         "---\nname: x\nmodel: claude-trivial-x\n---\nbody\n")
        for name in names(("claude-code", "agents", "*.md")):
            rel = "claude-code/agents/" + name
            diffs = changed_lines(read_repo(rel), real(rel, context))
            self.assertLessEqual(len(diffs), 1, rel)
            for old, new in diffs:
                self.assertTrue(old.startswith("model: ") and new.startswith("model: claude-"), rel)
        for text in ("---\nname: x\nmodel: inherit\n---\n", "---\nmodel: claude-opus-4-1\n---\n",
                     "---\nname: x\nmeta:\n  model: opus\n# model: opus\n---\n",
                     "model: opus\n", "---\nmodel: opus\nno closing", ""):
            self.assertEqual(rewrite(AGENT_X, text, context), text, repr(text))
        text = "---\nname: x\nmodel: opus\n---\nmodel: opus\n\n```\nmodel: sonnet\n```\n"
        self.assertEqual(rewrite(AGENT_X, text, context),
                         text.replace("model: opus\n---", "model: claude-heavy-x\n---", 1))
        before = read_repo(PLANNER)
        for missing in ({}, {"profile": {}}, {"profile": {"claude_heavy": "  "}}):
            self.assertEqual(rewrite(PLANNER, before, missing), before)

        for rel, effort, old in ((REVIEWER, "heavy", "xhigh"), (EXPLORER, "light", "medium")):
            self.assertEqual(changed_lines(read_repo(rel), real(rel, context)), [
                ('model = "gpt-5.6-sol"', 'model = "codex-model-x"'),
                ('model_reasoning_effort = "%s"' % old, 'model_reasoning_effort = "effort-%s"' % effort)])
        for name in names(("codex", "agents", "*.toml")):
            rel = "codex/agents/" + name
            after = real(rel, context)
            self.assertIn('model = "codex-model-x"', after, rel)
            if tomllib is not None:
                self.assertEqual(parse_toml(after)["developer_instructions"],
                                 parse_toml(read_repo(rel))["developer_instructions"], rel)
        tiers = {"xhigh": "heavy", "high": "heavy", "medium": "light", "low": "trivial"}
        for effort, tier in tiers.items():
            self.assertEqual(rewrite(ROLE_X, 'model_reasoning_effort = "%s"\n' % effort, context),
                             'model_reasoning_effort = "effort-%s"\n' % tier, effort)
        unknown = 'model_reasoning_effort = "ultra"\n'
        self.assertEqual(rewrite(ROLE_X, unknown, context), unknown)
        text = ('model = "a"  # keep me\nmodel_reasoning_effort = "low"\n'
                'developer_instructions = """\nmodel = "keep"\n"""\n[nested]\nmodel = "b"\n')
        self.assertEqual(changed_lines(text, rewrite(ROLE_X, text, context)), [
            ('model = "a"  # keep me', 'model = "codex-model-x"  # keep me'),
            ('model_reasoning_effort = "low"', 'model_reasoning_effort = "effort-trivial"')])
        before = read_repo(REVIEWER)
        self.assertEqual(rewrite(REVIEWER, before, {}), before)

    def test_config_settings_hooks_and_mcp_rules(self):
        """Rules 3 to 6: Codex config, Claude settings, Codex hooks and shared MCP servers."""
        # codex config, headroom on
        before = read_repo(CONFIG)
        after = real(CONFIG, make_context())
        self.assertEqual(changed_lines(before, after), [
            ('model = "gpt-5.6-sol"', 'model = "codex-model-x"'),
            ("max_threads = 6", "max_threads = 8"), ("max_depth = 1", "max_depth = 2")])
        self.assertIn('# model = "gpt-6-astra"', after)  # a comment is never "the first model"
        # codex config, headroom off: line-by-line comments, idempotent, still valid TOML
        off = real(CONFIG, make_context(headroom=False))
        lines = off.split("\n")
        for _old, new in changed_lines(before, off):
            self.assertTrue(new.startswith("# ") or new in (
                'model = "codex-model-x"', "max_threads = 8", "max_depth = 2"), new)
        for line in ('# model_provider = "headroom"', "# [model_providers.headroom]", "# hooks = true"):
            self.assertIn(line, lines, line)
        self.assertNotIn("# #", off)
        if tomllib is not None:
            data = parse_toml(off)
            self.assertNotIn("model_provider", data)
            self.assertNotIn("headroom", data["mcp_servers"])
            self.assertIn("github", data["mcp_servers"])
        for context in (make_context(), make_context(headroom=False)):
            once = real(CONFIG, context)
            self.assertEqual(rewrite(CONFIG, once, context), once)
        cases = (
            ("agent role tables keep their own keys", make_context(),
             "[agents]\nmax_threads = 6\n\n[agents.r]\nmax_threads = 99\n",
             "[agents]\nmax_threads = 8\n\n[agents.r]\nmax_threads = 99\n"),
            ("model in a table is not top level", make_context(), '[o]\nmodel = "x"\n', '[o]\nmodel = "x"\n'),
            ("end marker must match start", make_context(headroom=False),
             "# --- Headroom a ---\nx = 1\n# --- end Headroom b ---\ny = 2\n"
             "# --- end Headroom a ---\nz = 3\n",
             "# --- Headroom a ---\n# x = 1\n# --- end Headroom b ---\n# y = 2\n"
             "# --- end Headroom a ---\nz = 3\n"),
        )
        for label, context, text, expected in cases:
            self.assertEqual(rewrite(CONFIG, text, context), expected, label)
        for context in ({}, {"profile": {}}, {"config": {"subagents": {"codex": {"max_threads": True}}}}):
            self.assertEqual(rewrite(CONFIG, before, context), before)
        text = "[agents]\nmax_threads = 6\nmax_depth = 1\n"
        self.assertEqual(rewrite(CONFIG, text, {"config": {"subagents": {"codex": {
            "max_threads": 0, "max_depth": 0}}}}), "[agents]\nmax_threads = 6\nmax_depth = 0\n")

        # claude settings
        original = json.loads(read_repo(SETTINGS))
        data = loaded(SETTINGS, make_context())
        self.assertEqual(list(data["env"]), ["ANTHROPIC_BASE_URL", "ENABLE_TOOL_SEARCH",
                                             "ECC_HOOK_PROFILE", "ECC_DISABLED_HOOKS"])
        self.assertEqual(data["env"]["ECC_DISABLED_HOOKS"], "pre:bash:tmux-reminder,post:edit:format")
        self.assertEqual({k: v for k, v in data.items() if k != "env"},
                         {k: v for k, v in original.items() if k != "env"})
        data = loaded(SETTINGS, make_context(headroom=False))
        self.assertNotIn("ANTHROPIC_BASE_URL", data["env"])
        self.assertEqual(data["hooks"], {})
        body = {key: value for key, value in data.items() if key != "_comment"}
        self.assertNotIn("headroom", json.dumps(body).lower())
        self.assertTrue(data["enabledPlugins"]["codex@openai-codex"])
        keep, drop = hook("echo hi"), hook("$HOME/.local/bin/HeadRoom init")
        partial = loaded(SETTINGS, make_context(headroom=False), json.dumps({"hooks": {
            "A": [{"matcher": "x", "hooks": [drop, keep]}], "B": [{"matcher": "z", "hooks": [drop]}]}}))
        self.assertEqual(partial["hooks"], {"A": [{"matcher": "x", "hooks": [keep]}]})
        data = loaded(SETTINGS, make_context(codex=False))
        self.assertNotIn("codex@openai-codex", data["enabledPlugins"])
        self.assertNotIn("openai-codex", data["extraKnownMarketplaces"])
        self.assertEqual(data["hooks"], original["hooks"])
        self.assertIn("headroom@headroom-marketplace", data["enabledPlugins"])
        before_s = read_repo(SETTINGS)
        for context in ({}, {"profile": {}}, {"profile": {"hook_profile": " "}}):
            self.assertEqual(rewrite(SETTINGS, before_s, context), before_s)
        for text in ("{not json", "[1, 2]", ""):
            self.assertEqual(rewrite(SETTINGS, text, make_context(headroom=False)), text)

        # codex hooks
        before_h = read_repo(HOOKS)
        for context in (make_context(), make_context(codex=False), {}):
            self.assertEqual(rewrite(HOOKS, before_h, context), before_h)
        self.assertEqual(real(HOOKS, make_context(headroom=False)), '{\n  "hooks": {}\n}\n')
        text = json.dumps({"hooks": {"Z": [{"hooks": [keep]}], "A": [{"hooks": [hook("headroom ensure")]}]}})
        self.assertEqual(loaded(HOOKS, make_context(headroom=False), text)["hooks"], {"Z": [{"hooks": [keep]}]})

        # shared MCP servers
        self.assertEqual(real(MCP, make_context()), read_repo(MCP))
        original = json.loads(read_repo(MCP))
        data = loaded(MCP, make_context(headroom=False))
        self.assertEqual(list(data["servers"]), [n for n in original["servers"] if n != "headroom"])
        self.assertEqual(data["_comment"], original["_comment"])
        for name, spec in data["servers"].items():
            self.assertEqual(spec, original["servers"][name], name)
        for kwargs, remaining in (({"codex": False}, ["claude"]), ({"claude": False}, ["codex"])):
            for name, spec in loaded(MCP, make_context(**kwargs))["servers"].items():
                self.assertEqual(spec["targets"], remaining, name)
        self.assertEqual(loaded(MCP, make_context(codex=False, claude=False))["servers"], {})
        before_m = read_repo(MCP)
        for context in ({}, {"profile": {}}):
            self.assertEqual(rewrite(MCP, before_m, context), before_m)
        for text in ("{bad", "[]", '{"servers": []}'):
            self.assertEqual(rewrite(MCP, text, make_context(headroom=False)), text)

    def test_dispatch_purity_and_valid_output(self):
        """Unrelated paths are untouched, every rule is reached, input is not mutated."""
        off = make_context(headroom=False, codex=False, claude=False)
        text = '---\nmodel: opus\n---\nmodel = "x"\n\r\n{"servers": {"headroom": {}}}\xe9 \t\n'
        paths = ("README.md", "shared/RULES.md", "claude-code/CLAUDE.md", "codex/AGENTS.md", "",
                 "claude-code/settings.json", "codex/config.toml", "claude-code/commands/x.md",
                 "shared/skills/foo/SKILL.md", "claude-code/agents/sub/x.md", "claude-code/agents/x.txt",
                 "codex/agents/x.md", "other/claude-code/agents/x.md")
        for rel in paths:
            self.assertEqual(rewrite(rel, text, off), text, rel)
        for rel in ("README.md", "shared/RULES.md", "install.sh"):
            self.assertEqual(real(rel, off), read_repo(rel), rel)
        expected = real(PLANNER, make_context())
        self.assertNotEqual(expected, read_repo(PLANNER))
        self.assertEqual(rewrite("./" + PLANNER, read_repo(PLANNER), make_context()), expected)
        self.assertEqual(rewrite(PLANNER.replace("/", "\\"), read_repo(PLANNER), make_context()), expected)

        context = make_context(headroom=False, codex=False)
        snapshot = json.dumps(context, sort_keys=True, default=list)
        for rel in ALL_RULE_FILES:
            self.assertNotEqual(real(rel, context), read_repo(rel), rel)
        self.assertEqual(json.dumps(context, sort_keys=True, default=list), snapshot)
        for bad in (None, [], "ctx"):
            self.assertEqual(real(PLANNER, bad), read_repo(PLANNER))

        roles = ["codex/agents/" + name for name in names(("codex", "agents", "*.toml"))]
        for headroom in (True, False):
            for codex in (True, False):
                context = make_context(headroom=headroom, codex=codex, claude=codex)
                for rel in (SETTINGS, HOOKS, MCP):
                    json.loads(real(rel, context))
                for rel in [CONFIG] + roles:
                    parse_toml(real(rel, context))


if __name__ == "__main__":
    unittest.main()
