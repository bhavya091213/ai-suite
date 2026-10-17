"""Tests for installer.core.codex_config."""

from __future__ import annotations

import os
import sys
import unittest
from typing import Callable, List, Tuple
from unittest import mock

from installer.core.codex_config import check, patch_agents, patch_model

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - older interpreters
    tomllib = None  # type: ignore[assignment]

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
EXAMPLE_PATH = os.path.join(REPO_DIR, "codex", "config.example.toml")


def read_example() -> str:
    with open(EXAMPLE_PATH, encoding="utf-8", newline="") as handle:
        return handle.read()


def changed_lines(before: str, after: str) -> List[Tuple[str, str]]:
    """Pairs of (old line, new line) for lines that differ; the line counts must match."""
    old = before.split("\n")
    new = after.split("\n")
    if len(old) != len(new):
        raise AssertionError("line count changed: %d -> %d" % (len(old), len(new)))
    return [(a, b) for a, b in zip(old, new) if a != b]


def agents(threads: int, depth: int) -> Callable[[str], str]:
    return lambda text: patch_agents(text, threads, depth)


def model(name: str = "z") -> Callable[[str], str]:
    return lambda text: patch_model(text, name)


class CodexConfigTests(unittest.TestCase):
    def assert_valid_toml(self, text: str) -> None:
        if tomllib is not None:
            tomllib.loads(text)  # raises on invalid input
        self.assertIsNone(check(text))

    def assert_edits(self, rows) -> None:
        """Each row is (label, input text, edit function, expected output); the output must stay valid TOML."""
        for label, text, edit, expected in rows:
            with self.subTest(label):
                out = edit(text)
                self.assertEqual(out, expected)
                self.assert_valid_toml(out)

    def test_edits_change_only_the_value_lines_and_keep_everything_else(self) -> None:
        text = read_example()
        with self.subTest("the example changes only the two agent value lines"):
            out = patch_agents(text, 3, 2)
            self.assertEqual(changed_lines(text, out),
                             [("max_threads = 6", "max_threads = 3"), ("max_depth = 1", "max_depth = 2")])
            self.assert_valid_toml(out)
            self.assertEqual(patch_agents(text, 6, 1), text)  # same values: byte-identical
        with self.subTest("the example changes only the model line"):
            out = patch_model(text, "gpt-9-test")
            self.assertEqual(changed_lines(text, out), [('model = "gpt-5.6-sol"', 'model = "gpt-9-test"')])
            self.assertIn('# model = "gpt-6-astra"', out)
            self.assert_valid_toml(out)
            self.assertEqual(patch_model(text, "gpt-5.6-sol"), text)
        self.assert_edits([
            ("agents: comments and spacing kept", '[agents]\n  max_threads   =   6   # keep me\nmax_depth=1 # and me\n',
             agents(8, 3), '[agents]\n  max_threads   =   8   # keep me\nmax_depth=3 # and me\n'),
            ("agents: subtables and other tables never edited",
             "[agents.x]\nmax_threads = 99\n[other]\nmax_depth = 98\n[agents]\nmax_threads = 1\nmax_depth = 1\n",
             agents(5, 6),
             "[agents.x]\nmax_threads = 99\n[other]\nmax_depth = 98\n[agents]\nmax_threads = 5\nmax_depth = 6\n"),
            ("agents: CRLF kept", "a = 1\r\n[agents]\r\nmax_threads = 6 # c\r\n\r\n[x]\r\n", agents(3, 2),
             "a = 1\r\n[agents]\r\nmax_threads = 3 # c\r\nmax_depth = 2\r\n\r\n[x]\r\n"),
            ("agents: a missing key goes inside the table",
             '[agents]\nmax_threads = 2\n\n[agents.x]\ndescription = "d"\n', agents(4, 1),
             '[agents]\nmax_threads = 4\nmax_depth = 1\n\n[agents.x]\ndescription = "d"\n'),
            ("agents: the table is created after other tables", 'model = "x"\n\n[features]\nhooks = true\n', agents(6, 1),
             'model = "x"\n\n[features]\nhooks = true\n\n[agents]\nmax_threads = 6\nmax_depth = 1\n'),
            ("agents: the table is created in empty text", "", agents(2, 3), "[agents]\nmax_threads = 2\nmax_depth = 3\n"),
            ("model: the top-level line is edited, a table's is not", 'model = "a"\n[x]\nmodel = "c"\n', model(),
             'model = "z"\n[x]\nmodel = "c"\n'),
            ("model: spacing and trailing comment", 'model   =   "a"   # why\n', model(), 'model   =   "z"   # why\n'),
            ("model: inserted at the top level, not inside a table", '[x]\nmodel = "c"\n', model(),
             'model = "z"\n\n[x]\nmodel = "c"\n'),
            ("model: the value is escaped", 'model = "a"\n', model('we"ird\\name'), 'model = "we\\"ird\\\\name"\n'),
            ("a model line inside a multi-line string is left alone", 'note = """\nmodel = "inner"\n"""\n[x]\n', model(),
             'note = """\nmodel = "inner"\n"""\nmodel = "z"\n[x]\n'),
            ("an [agents] header inside a string is not the table", 'doc = """\n[agents]\nmax_threads = 99\n"""\n',
             agents(4, 2), 'doc = """\n[agents]\nmax_threads = 99\n"""\n\n[agents]\nmax_threads = 4\nmax_depth = 2\n'),
        ])

    def test_unusable_input_is_rejected_instead_of_edited_blindly(self) -> None:
        for threads, depth in ((True, 1), (1, False), (-1, 1), (1, -2), ("3", 1), (1, 1.5), (None, 1)):
            with self.subTest(threads=threads, depth=depth), self.assertRaises(ValueError):
                patch_agents("[agents]\n", threads, depth)  # type: ignore[arg-type]
        for bad in ("", "   ", None):
            with self.subTest(model=bad), self.assertRaises(ValueError):
                patch_model('model = "a"\n', bad)  # type: ignore[arg-type]
        for label, text in (("unterminated multi-line string", 'note = """\nnever closed\n[agents]\nmax_threads = 1\n'),
                            ("unterminated array", "roles = [\n  1,\n[agents]\nmax_threads = 1\n")):
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    patch_agents(text, 2, 2)
                with self.assertRaises(ValueError):
                    patch_model(text, "z")
        with self.subTest("check reports parse errors and is silent without tomllib"):
            self.assertIsNone(check(read_example()))
            if tomllib is not None:
                self.assertTrue(check("a = \nb = 1\n"))
            with mock.patch.dict(sys.modules, {"tomllib": None}):
                self.assertIsNone(check("this is = = not toml"))


if __name__ == "__main__":
    unittest.main()
