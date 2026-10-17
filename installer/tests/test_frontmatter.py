"""Tests for installer.core.frontmatter."""

from __future__ import annotations

import os
import tempfile
import unittest

from installer.core.frontmatter import parse_frontmatter, read_meta
from installer.core.types import SkillMeta
from installer.tests import fixtures

EMPTY = SkillMeta(None, None, {})


class FrontmatterTests(unittest.TestCase):
    def test_parse_frontmatter(self) -> None:
        meta = parse_frontmatter("---\nname: alpha\ndescription: Alpha does things\n---\n# Body\n")
        self.assertEqual((meta.name, meta.description, meta.valid), ("alpha", "Alpha does things", True))
        with self.assertRaises(TypeError):
            meta.fields["name"] = "y"  # type: ignore[index]
        meta = parse_frontmatter("---\n# a comment\nname: x\nthis is not a key\n- list item\n"
                                 "description: Use when: the user says go\nname: second\n---\n")
        self.assertEqual((meta.name, meta.description), ("second", "Use when: the user says go"))
        meta = parse_frontmatter("\ufeff\r\n---\r\nname: alpha\r\ndescription: d\r\n---\r\nbody\r\n")
        self.assertEqual((meta.name, meta.description), ("alpha", "d"))
        meta = parse_frontmatter("---\nname:\ndescription: d\n---\n")
        self.assertEqual((meta.name, meta.fields["name"], meta.valid), (None, "", False))
        for label, text in {"plain markdown": "# No frontmatter here\n", "empty text": "",
                            "unterminated block": "---\nname: alpha\n# body\n",
                            "delimiter must open the text": "# Title\n\n---\nname: alpha\n---\n"}.items():
            with self.subTest(label):
                self.assertEqual(parse_frontmatter(text), EMPTY)
        self.assertEqual(parse_frontmatter(None), EMPTY)  # type: ignore[arg-type]
        cases = [  # text, expected description
            ('---\ndescription: \'Says "hi" and it\'\'s fine\'\n---\n', 'Says "hi" and it\'s fine'),
            ('---\ndescription: "say \\"deploy\\" ok"\n---\n', 'say "deploy" ok'),
            ("---\ndescription: >\n  first line\n  second line\n\n  third\nother: 1\n---\n",
             "first line second line third"),
            ("---\ndescription: |\n  line one\n    indented two\nname: x\n---\n", "line one\n  indented two"),
            ("---\ndescription:\n  collected from\n  below\nname: x\n---\n", "collected from below"),
            ("---\ndescription: starts here\n  and wraps\nname: x\n---\n", "starts here and wraps"),
        ]
        for text, description in cases:
            with self.subTest(text=text):
                self.assertEqual(parse_frontmatter(text).description, description)
        for sample in ("---", "---\n---", "---\n: value\n---\n", "---\nname: |\n---\n", "\x00\x01",
                       "---\nname: 'unterminated\n---\n"):
            with self.subTest(sample=sample):  # malformed input never raises
                self.assertIsInstance(parse_frontmatter(sample), SkillMeta)

    def test_read_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = fixtures.build(tmp)
            weird = os.path.join(tmp, "weird")
            os.makedirs(os.path.join(weird, "SKILL.md"))  # SKILL.md is a directory
            for path in (os.path.join(tmp, "does-not-exist"), os.path.join(paths.source_dir("claude"), "learned"),
                         weird):
                self.assertIsNone(read_meta(path), path)
            alpha = read_meta(os.path.join(paths.source_dir("shared"), "alpha"))
            assert alpha is not None
            self.assertEqual((alpha.name, alpha.description, alpha.valid),
                             ("alpha", "Alpha skill for testing", True))
            nometa = read_meta(os.path.join(paths.source_dir("claude"), "nometa"))
            assert nometa is not None
            self.assertEqual((nometa.name, nometa.description, nometa.valid), (None, None, False))
            binary = os.path.join(tmp, "binary")
            os.makedirs(binary)
            with open(os.path.join(binary, "SKILL.md"), "wb") as handle:
                handle.write(b"---\nname: bin\ndescription: \xff\xfe junk\n---\n")
            meta = read_meta(binary)
            assert meta is not None
            self.assertEqual(meta.name, "bin")
            self.assertIn("junk", meta.description or "")


if __name__ == "__main__":
    unittest.main()
