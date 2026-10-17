"""Tests for installer.core.editor."""

from __future__ import annotations

import sys
import unittest
from types import MappingProxyType
from typing import Dict, List, Optional, Sequence

from installer.core.config import DEFAULTS, Config
from installer.core.editor import edit_file, resolve_editor


def make_which(found: Sequence[str]):
    """A `which` stub that records its calls and finds only the names in `found`."""
    calls: List[str] = []

    def which(name: str) -> Optional[str]:
        calls.append(name)
        return "/usr/bin/" + name if name in found else None

    which.calls = calls  # type: ignore[attr-defined]
    return which


class ResolveEditorTests(unittest.TestCase):
    def test_the_editor_comes_from_config_then_the_environment_then_the_path(self) -> None:
        for check in (self.check_config_wins_then_visual_then_editor, self.check_the_path_is_searched_nano_vim_vi,
                      self.check_a_config_object_and_keyword_arguments_are_accepted):
            with self.subTest(check.__name__):
                check()

    def check_config_wins_then_visual_then_editor(self) -> None:
        which = make_which(["nano"])
        argv = resolve_editor({"editor": "code --wait"}, {"VISUAL": "emacs", "EDITOR": "ed"}, which)
        self.assertEqual(argv, ("code", "--wait"))
        self.assertEqual(which.calls, [])  # type: ignore[attr-defined]  # the PATH is not even searched
        self.assertEqual(resolve_editor({}, {"VISUAL": "nvim", "EDITOR": "ed"}, make_which([])), ("nvim",))
        self.assertEqual(resolve_editor({}, {"EDITOR": "ed -s"}, make_which([])), ("ed", "-s"))
        self.assertEqual(resolve_editor({}, {"VISUAL": "  ", "EDITOR": "ed"}, make_which([])), ("ed",))
        self.assertEqual(resolve_editor({"editor": ""}, {"VISUAL": "nvim"}, make_which([])), ("nvim",))
        self.assertEqual(resolve_editor({"editor": "   "}, {"EDITOR": "ed"}, make_which([])), ("ed",))

    def check_the_path_is_searched_nano_vim_vi(self) -> None:
        self.assertEqual(resolve_editor({}, {}, make_which(["nano", "vim", "vi"])), ("nano",))
        self.assertEqual(resolve_editor({}, {}, make_which(["vim", "vi"])), ("vim",))
        self.assertEqual(resolve_editor({}, {}, make_which(["vi"])), ("vi",))
        self.assertEqual(resolve_editor({}, {}, make_which([])), ("vi",))
        which = make_which(["vim", "vi"])
        resolve_editor({}, {}, which)
        self.assertEqual(which.calls, ["nano", "vim"])  # type: ignore[attr-defined]  # stops at the first hit
        self.assertIn(resolve_editor({}, {})[0], ("nano", "vim", "vi"))  # the default is the real shutil.which

    def check_a_config_object_and_keyword_arguments_are_accepted(self) -> None:
        # ARCHITECTURE.md specifies resolve_editor(config: Config, env, which).
        config = Config(data=DEFAULTS, path="config.json", exists=False)
        self.assertEqual(resolve_editor(config, {"EDITOR": "ed"}, make_which([])), ("ed",))
        config = Config(data=MappingProxyType({"editor": "code --wait"}), path="config.json", exists=True)
        self.assertEqual(resolve_editor(config, {"VISUAL": "emacs"}, make_which(["nano"])), ("code", "--wait"))
        self.assertEqual(resolve_editor(MappingProxyType({"editor": "micro"}), {}, make_which([])), ("micro",))
        env: Dict[str, str] = {"EDITOR": "ed"}
        argv = resolve_editor(config={"editor": ""}, env=env, which=make_which([]))
        self.assertEqual((argv, env), (("ed",), {"EDITOR": "ed"}))  # a tuple; the inputs are untouched


class EditFileTests(unittest.TestCase):
    def test_the_path_is_appended_as_an_argument_and_the_exit_status_returned(self) -> None:
        seen: List[List[str]] = []

        def run(cmd: Sequence[str]) -> int:
            seen.append(list(cmd))
            return 3

        argv = ["code", "--wait"]
        self.assertEqual(edit_file("/srv/example.toml", argv, run), 3)
        self.assertEqual(seen, [["code", "--wait", "/srv/example.toml"]])
        self.assertEqual(argv, ["code", "--wait"])  # not mutated
        edit_file("-weird", ("vi",), run)  # a path starting with a dash must not look like an option
        self.assertEqual(seen[1][0], "vi")
        self.assertFalse(seen[1][1].startswith("-"))
        self.assertTrue(seen[1][1].endswith("-weird"))
        with self.assertRaises(ValueError):  # an empty argv is rejected
            edit_file("f", (), run)
        status = edit_file("ignored", (sys.executable, "-c", "import sys; sys.exit(int(sys.argv[1] == 'ignored') + 6)"))
        self.assertEqual(status, 7)  # the default runner is subprocess.call

if __name__ == "__main__":
    unittest.main()
