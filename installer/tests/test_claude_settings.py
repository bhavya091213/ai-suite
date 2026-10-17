"""Tests for installer.core.claude_settings."""

from __future__ import annotations

import json
import os
import unittest

from installer.core.claude_settings import HOOK_PROFILES, patch_env, warnings

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
EXAMPLE_PATH = os.path.join(REPO_DIR, "claude-code", "settings.example.json")

NO_HEADROOM = {"profile": {"headroom": False}}
WITH_HEADROOM = {"profile": {"headroom": True}}
PROXY_ENV = '{"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8787"}}'


def read_example() -> str:
    with open(EXAMPLE_PATH, encoding="utf-8") as handle:
        return handle.read()


class PatchEnvTests(unittest.TestCase):
    def test_patching_sets_appends_removes_and_keeps_everything_else(self) -> None:
        text = read_example()
        original = json.loads(text)
        with self.subTest("an empty update only reformats and patching is idempotent"):
            out = patch_env(text, {})
            self.assertEqual(json.loads(out), original)
            self.assertEqual(list(json.loads(out)), list(original))
            self.assertTrue(out.endswith("}\n") and not out.endswith("\n\n"))
            updates = {"ECC_HOOK_PROFILE": "standard", "ENABLE_TOOL_SEARCH": None}
            once = patch_env(text, updates)
            self.assertEqual(patch_env(once, updates), once)
        with self.subTest("values are set in place, appended and removed"):
            out = json.loads(patch_env(text, {"ANTHROPIC_BASE_URL": "https://example.test"}))
            expected = json.loads(text)
            expected["env"]["ANTHROPIC_BASE_URL"] = "https://example.test"
            self.assertEqual(out, expected)
            out = json.loads(patch_env(text, {"ECC_HOOK_PROFILE": "strict", "ECC_DISABLED_HOOKS": "a,b"}))
            self.assertEqual(list(out["env"]),
                             ["ANTHROPIC_BASE_URL", "ENABLE_TOOL_SEARCH", "ECC_HOOK_PROFILE", "ECC_DISABLED_HOOKS"])
            out = json.loads(patch_env(text, {"ANTHROPIC_BASE_URL": None, "ENABLE_TOOL_SEARCH": None}))
            self.assertNotIn("env", out)  # an emptied env is dropped; the other keys keep their order
            self.assertEqual(list(out), [key for key in original if key != "env"])
        with self.subTest("a missing env is created last and removals never create one"):
            data = json.loads(patch_env('{"model": "x", "theme": "dark"}', {"A": "1"}))
            self.assertEqual((list(data), data["env"]), (["model", "theme", "env"], {"A": "1"}))
            self.assertEqual(json.loads(patch_env('{"model": "x"}', {"A": None})), {"model": "x"})
            self.assertEqual(json.loads(patch_env("", {"A": "1"})), {"env": {"A": "1"}})
        with self.subTest("unusable input raises ValueError naming the problem"):
            cases = [('{"env": {', {"A": "1"}, ("not valid JSON",)), ("[1, 2]", {"A": "1"}, ("object",)),
                     ('{"env": ["x"]}', {"A": "1"}, ("env",)), ("{}", {"A": 1}, ())]
            for bad, updates, fragments in cases:
                with self.subTest(text=bad, updates=updates), self.assertRaises(ValueError) as caught:
                    patch_env(bad, updates)  # type: ignore[arg-type]
                for fragment in fragments:
                    self.assertIn(fragment, str(caught.exception))


class WarningsTests(unittest.TestCase):
    def test_the_proxy_and_hook_profile_warnings(self) -> None:
        with self.subTest("the example warns about the proxy only without headroom"):
            self.assertEqual(warnings(read_example(), WITH_HEADROOM), ())
            self.assertEqual(len(warnings(read_example(), NO_HEADROOM)), 1)
        with self.subTest("proxy conditions"):
            cases = [('{"env": {"ANTHROPIC_BASE_URL": "http://LocalHost:9000"}}', NO_HEADROOM, 1),
                     ('{"env": {"ANTHROPIC_BASE_URL": "https://gateway.example.com"}}', NO_HEADROOM, 0)]
            cases += [(PROXY_ENV, context, 0) for context in ({}, {"profile": {}}, {"profile": None})]  # unknown
            for text, context, count in cases:
                with self.subTest(text=text, context=context):
                    self.assertEqual(len(warnings(text, context)), count)
        with self.subTest("the hook profile must be a known name"):
            for good in HOOK_PROFILES:
                self.assertEqual(warnings('{"env": {"ECC_HOOK_PROFILE": "%s"}}' % good, WITH_HEADROOM), ())
            result = warnings('{"env": {"ECC_HOOK_PROFILE": "paranoid"}}', WITH_HEADROOM)
            self.assertEqual(len(result), 1)
            for fragment in ("ECC_HOOK_PROFILE", "paranoid", "minimal, standard, strict"):
                self.assertIn(fragment, result[0])
            for bad in ('""', "3", '["strict"]'):  # empty or non-string
                self.assertEqual(len(warnings('{"env": {"ECC_HOOK_PROFILE": %s}}' % bad, WITH_HEADROOM)), 1)
        with self.subTest("bad input never raises"):
            self.assertEqual(warnings("{}", NO_HEADROOM), ())
            self.assertIn("not valid JSON", warnings("{nope", NO_HEADROOM)[0])


if __name__ == "__main__":
    unittest.main()
