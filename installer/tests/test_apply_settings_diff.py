"""The printed settings diff must never show a secret (installer.core.apply_settings.diff_lines)."""

from __future__ import annotations

import json
import unittest
from typing import Tuple

from installer.core import apply_settings, claude_settings
from installer.tests.settings_support import SAMPLE_SETTINGS, dump


class DiffRedactionTests(unittest.TestCase):
    """The printed diff must never show a secret that sits next to a changed line."""

    TOKEN = "sk-fake-1"
    HELPER = "helper-fake-9"

    def settings_change(self, indent: int) -> Tuple[str, str, str]:
        env = {"ECC_HOOK_PROFILE": "standard", "ENABLE_TOOL_SEARCH": "true", "ANTHROPIC_AUTH_TOKEN": self.TOKEN}
        old = dump(dict(SAMPLE_SETTINGS, env=env, apiKeyHelper=self.HELPER), indent)
        return ("~/.claude/settings.json", old, claude_settings.patch_env(old, {"ECC_HOOK_PROFILE": "strict"}))

    def test_the_diff_masks_secrets_next_to_a_change_and_never_masks_the_managed_keys(self) -> None:
        for check in (self.check_json_secrets, self.check_toml_secrets, self.check_managed_keys):
            with self.subTest(check.__name__):
                check()

    def check_json_secrets(self) -> None:
        for indent in (2, 4):  # 4 spaces: the file is reformatted, so the whole document is in the diff
            with self.subTest(indent=indent):
                change = self.settings_change(indent)
                self.assertIn(self.TOKEN, change[1])
                text = "\n".join(apply_settings.diff_lines(change))
                for secret in (self.TOKEN, self.HELPER):
                    self.assertNotIn(secret, text)
                self.assertIn('"ECC_HOOK_PROFILE": "strict"', text)
                if indent == 4:
                    self.assertNotIn('"ENABLE_TOOL_SEARCH": "true"', text)  # every unmanaged env value is masked
                    self.assertIn('"ENABLE_TOOL_SEARCH": "***"', text)
                    self.assertIn('"permissions"', text)  # structure and unrelated keys stay readable
        minified = json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": self.TOKEN}, "model": "opus"})  # one line
        patched = claude_settings.patch_env(minified, {"ECC_HOOK_PROFILE": "strict"})
        self.assertNotIn(self.TOKEN, "\n".join(apply_settings.diff_lines(("~/.claude/settings.json", minified, patched))))

    def check_toml_secrets(self) -> None:
        old = 'model = "a"\nenv = { GITHUB_TOKEN = "ghp_fake" }\napi_key = \'plain-fake\'\n'
        new = old.replace('model = "a"', 'model = "b"')
        text = "\n".join(apply_settings.diff_lines(("/h/.codex/config.toml", old, new)))
        self.assertNotIn("ghp_fake", text)
        self.assertNotIn("plain-fake", text)
        self.assertIn('-model = "a"', text)
        self.assertIn('+model = "b"', text)

    def check_managed_keys(self) -> None:
        old = dump({"env": {"ECC_DISABLED_HOOKS": "a:b", "ECC_HOOK_PROFILE": "standard"}})
        new = claude_settings.patch_env(old, {"ECC_DISABLED_HOOKS": "c:d"})
        text = "\n".join(apply_settings.diff_lines(("/h/.claude/settings.json", old, new)))
        self.assertIn('-    "ECC_DISABLED_HOOKS": "a:b",', text)
        self.assertIn('+    "ECC_DISABLED_HOOKS": "c:d",', text)
