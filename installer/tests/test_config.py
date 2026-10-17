"""Tests for installer.core.config: defaults, merge, immutability, parsing, validate, save."""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import tempfile
import unittest
from types import MappingProxyType
from typing import Any, List
from unittest import mock

from installer.core import config as cfg
from installer.core.config import (DEFAULTS, SECTIONS, SETTINGS, Config, get, load, parse_value, save,
                                   setting_for, to_json, validate, with_value)
from installer.tests.fixtures import paths_for, write

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
DEFAULTS_CONFIG = Config(data=DEFAULTS, path="", exists=False)


def _leaves(node: Any, prefix: str = "") -> List[str]:
    """Dotted keys of every non-mapping value in a nested mapping."""
    out: List[str] = []
    for key, value in node.items():
        if isinstance(value, (dict, MappingProxyType)):
            out.extend(_leaves(value, prefix + key + "."))
        else:
            out.append(prefix + key)
    return out


def _raw(**sections: Any) -> Config:
    """A Config built from DEFAULTS with whole top-level keys replaced (no validation)."""
    data = {**cfg._thaw(DEFAULTS), **sections}
    return Config(data=cfg._freeze(data), path="", exists=False)


class TempHome(unittest.TestCase):
    """Each test gets a throwaway fake home and a Paths pointing into it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.paths = paths_for(self.root)
        self.config_file = os.path.join(self.paths.agents_home, "config.json")

    def write_config(self, text: str) -> str:
        return write(self.config_file, text)

    def read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def read_config_file(self) -> Any:
        return json.loads(self.read_text(self.config_file))

    def backup_dirs(self) -> List[str]:
        parent = os.path.join(self.paths.agents_home, "backups")
        names = sorted(os.listdir(parent)) if os.path.isdir(parent) else []
        return [os.path.join(parent, n) for n in names if n.startswith("config-")]

    def temp_files(self) -> List[str]:
        return [n for n in os.listdir(self.paths.agents_home) if n.endswith(".tmp")]

    def fixed_backup_root(self) -> Any:
        """Patch Paths.backup_root so two saves land in one directory (same-second clash)."""
        return mock.patch.object(
            type(self.paths), "backup_root",
            lambda p, label, ts=None: os.path.join(p.agents_home, "backups", label + "-FIXED"))


class ConfigTests(TempHome):
    @property
    def base(self) -> Config:
        return load(self.paths)

    def run_checks(self, *checks) -> None:
        """Run each check as a subTest against its own throwaway home."""
        for check in checks:
            with self.subTest(check.__name__):
                self.paths = paths_for(os.path.join(self.root, check.__name__))
                self.config_file = os.path.join(self.paths.agents_home, "config.json")
                check()

    def test_the_defaults_are_complete_and_a_file_is_merged_over_them(self) -> None:
        self.run_checks(self.check_settings_describe_every_default_leaf_once_in_section_order,
                        self.check_defaults_load_without_a_file_round_trip_and_match_the_example,
                        self.check_a_partial_file_fills_in_defaults_and_unknown_keys_survive_a_save,
                        self.check_unusable_files_give_defaults_plus_error,
                        self.check_wrong_shapes_default_with_error_and_wrong_leaf_types_are_flagged)

    def test_loaded_data_is_immutable_and_to_json_is_stable(self) -> None:
        self.run_checks(self.check_loaded_data_cannot_be_mutated,
                        self.check_with_value_returns_a_new_frozen_object_and_keeps_unknown_keys,
                        self.check_formatting_order_newline_lists_and_unicode)

    def test_values_are_parsed_and_validated_and_bad_ones_change_nothing(self) -> None:
        self.run_checks(self.check_each_kind_parses_text_and_rejects_what_it_cannot_read,
                        self.check_every_setting_parses_its_own_default,
                        self.check_each_kind_accepts_a_valid_value_and_lists_become_tuples,
                        self.check_bad_values_and_keys_are_rejected_and_change_nothing,
                        self.check_validate_reports_missing_keys_wrong_types_and_bad_enums_as_strings,
                        self.check_vault_paths_are_checked_after_expanding_the_tilde)

    def test_save_backs_up_before_replacing_writes_atomically_and_never_deletes(self) -> None:
        self.run_checks(self.check_first_save_creates_parent_and_file_without_backup,
                        self.check_save_backs_up_the_existing_file_with_copy2_even_when_it_is_broken,
                        self.check_two_saves_in_one_second_keep_both_backups_under_backup_root,
                        self.check_write_is_atomic_temp_in_same_directory_then_os_replace,
                        self.check_failed_write_keeps_original_and_moves_temp_aside,
                        self.check_no_delete_calls_terminal_use_personal_paths_or_oversize)

    def check_settings_describe_every_default_leaf_once_in_section_order(self) -> None:
        keys = [s.key for s in SETTINGS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(_leaves(DEFAULTS)) - {"version"}, set(keys))
        for s in SETTINGS:
            self.assertTrue(s.label and s.help, s.key)
            self.assertIn(s.kind, ("bool", "int", "str", "enum", "pathlist", "strlist", "path"))
            self.assertEqual(bool(s.choices), s.kind == "enum", s.key)
        order = [SECTIONS.index(s.section) for s in SETTINGS]
        self.assertEqual(order, sorted(order))
        self.assertEqual({s.section for s in SETTINGS}, set(SECTIONS))

    def check_defaults_load_without_a_file_round_trip_and_match_the_example(self) -> None:
        loaded = load(self.paths)
        self.assertEqual((loaded.data, loaded.path, loaded.exists, loaded.error, validate(loaded)),
                         (DEFAULTS, self.config_file, False, None, ()))
        self.assertNotIn("_comment", DEFAULTS)
        text = to_json(loaded)
        self.assertEqual(json.loads(text), cfg._thaw(DEFAULTS))
        self.assertEqual(save(loaded, self.paths), self.config_file)
        again = load(self.paths)
        self.assertEqual((again.exists, again.data, to_json(again)), (True, DEFAULTS, text))
        example_path = os.path.join(REPO_ROOT, "shared", "config.example.json")
        if os.path.isfile(example_path):
            with open(example_path, encoding="utf-8") as fh:
                example = json.load(fh)
            example.pop("_comment", None)
            self.assertEqual(cfg._freeze(example), DEFAULTS)

    def check_a_partial_file_fills_in_defaults_and_unknown_keys_survive_a_save(self) -> None:
        self.write_config('﻿{"tools": {"codex": "off"}, "guardrails": {"hook_profile": "strict"}}')  # BOM ok
        loaded = load(self.paths)
        self.assertTrue(loaded.exists)
        self.assertIsNone(loaded.error)
        expected = {"tools.codex": "off", "tools.claude": "auto", "guardrails.hook_profile": "strict",
                    "guardrails.never_delete": True, "subagents.claude.heavy": "opus"}
        for key, value in expected.items():
            self.assertEqual(get(loaded, key), value, key)

        self.write_config(json.dumps({"editor": "nano", "_comment": "keep me", "future": {"flag": [1, 2]},
                                      "tools": {"claude": "on", "gemini": "auto"},
                                      "paths": {"obsidian_vaults": ["~/a", "~/b"]}}))
        loaded = load(self.paths)
        self.assertEqual(get(loaded, "future.flag"), (1, 2))
        self.assertEqual(get(loaded, "paths.obsidian_vaults"), ("~/a", "~/b"))
        self.assertEqual(list(json.loads(to_json(loaded)))[0], "_comment")  # comment keys lead
        save(loaded, self.paths)
        on_disk = self.read_config_file()
        self.assertEqual((on_disk["_comment"], on_disk["future"]), ("keep me", {"flag": [1, 2]}))
        self.assertEqual(on_disk["tools"], {"claude": "on", "codex": "auto", "gemini": "auto"})
        self.assertEqual(on_disk["paths"]["obsidian_vaults"], ["~/a", "~/b"])

    def check_unusable_files_give_defaults_plus_error(self) -> None:
        cases = [
            (b'{"tools": {', "invalid JSON"), (b"[1, 2, 3]", "JSON object"), (b"", "invalid JSON"),
            (b"\xff\xfe\x00bad", "cannot read"),
        ]
        for raw, fragment in cases:
            with self.subTest(raw=raw):
                os.makedirs(self.paths.agents_home, exist_ok=True)
                with open(self.config_file, "wb") as fh:
                    fh.write(raw)
                loaded = load(self.paths)
                self.assertEqual(loaded.data, DEFAULTS)
                self.assertTrue(loaded.exists)
                self.assertIn(fragment, loaded.error or "")

    def check_wrong_shapes_default_with_error_and_wrong_leaf_types_are_flagged(self) -> None:
        self.write_config('{"tools": "everything", "subagents": {"codex": 7}, '
                          '"guardrails": {"never_delete": "yes"}, "review": {"adversarial": "maybe"}}')
        loaded = load(self.paths)
        self.assertEqual((get(loaded, "tools.claude"), get(loaded, "subagents.codex.model")), ("auto", "gpt-5.6-sol"))
        self.assertIn("tools", loaded.error or "")
        self.assertIn("subagents.codex", loaded.error or "")
        self.assertEqual(get(loaded, "guardrails.never_delete"), "yes")  # leaf kept as written
        problems = validate(loaded)
        self.assertEqual([w.split(":")[0] for w in problems], ["review.adversarial", "guardrails.never_delete"])
        self.assertIn("maybe", problems[0])

    def check_loaded_data_cannot_be_mutated(self) -> None:
        self.write_config('{"paths": {"obsidian_vaults": ["~/a"]}}')
        loaded = load(self.paths)
        for target, key in ((loaded.data, "editor"), (loaded.data["tools"], "claude"),
                            (loaded.data["subagents"]["codex"], "max_depth"), (DEFAULTS, "editor"),
                            (DEFAULTS["guardrails"], "never_delete")):
            with self.assertRaises(TypeError, msg=key):
                target[key] = "x"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            get(loaded, "paths.obsidian_vaults").append("~/b")  # type: ignore[attr-defined]
        self.assertEqual(get(loaded, "paths.obsidian_vaults"), ("~/a",))
        self.assertIsInstance(DEFAULTS["guardrails"]["disabled_hooks"], tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            loaded.exists = True  # type: ignore[misc]

    def check_with_value_returns_a_new_frozen_object_and_keeps_unknown_keys(self) -> None:
        old = load(self.paths)
        before = to_json(old)
        new = with_value(old, "guardrails.hook_profile", "strict")
        self.assertIsNot(new.data, old.data)
        self.assertEqual(get(new, "guardrails.hook_profile"), "strict")
        self.assertEqual((to_json(old), old.data), (before, DEFAULTS))
        self.assertEqual((new.path, new.exists, new.error), (old.path, old.exists, old.error))
        self.assertIsInstance(new.data["tools"], MappingProxyType)
        with self.assertRaises(TypeError):
            new.data["tools"]["codex"] = "on"  # type: ignore[index]
        newer = with_value(new, "guardrails.hook_profile", "minimal")  # a chain never leaks backwards
        self.assertEqual([get(c, "guardrails.hook_profile") for c in (old, new, newer)],
                         ["standard", "strict", "minimal"])

        self.write_config('{"extra": {"x": 1}}')
        self.assertEqual(json.loads(to_json(with_value(load(self.paths), "editor", "nano")))["extra"], {"x": 1})
        bare = Config(data=MappingProxyType({}), path="", exists=False)  # missing branches are built
        self.assertEqual(get(with_value(bare, "subagents.codex.max_depth", 3), "subagents.codex.max_depth"), 3)
        self.assertEqual(len(bare.data), 0)

    def assertParses(self, key: str, cases: Any) -> None:
        for text, expected in cases:
            with self.subTest(key=key, text=text):
                self.assertEqual(parse_value(setting_for(key), text), expected)
                self.assertIs(type(parse_value(setting_for(key), text)), type(expected))

    def assertRejects(self, key: str, texts: Any) -> None:
        for text in texts:
            with self.subTest(key=key, text=text):
                with self.assertRaises(ValueError):
                    parse_value(setting_for(key), text)

    def check_each_kind_parses_text_and_rejects_what_it_cannot_read(self) -> None:
        self.assertParses("guardrails.never_delete", [(t, True) for t in ("true", "True", " TRUE ", "yes", "on", "1")])
        self.assertParses("guardrails.never_delete", [(t, False) for t in ("false", "False", "no", "off", "0")])
        self.assertRejects("guardrails.never_delete", ["", "maybe", "2", "tru"])
        self.assertParses("subagents.codex.max_threads", [("8", 8), (" 12 ", 12)])
        self.assertRejects("subagents.codex.max_threads", ["", "x", "1.5", "six", "0", "-3"])
        self.assertParses("subagents.codex.max_depth", [("0", 0)])  # depth may be zero, threads may not
        self.assertRejects("subagents.codex.max_depth", ["-1"])
        self.assertParses("subagents.codex.model", [("  gpt-x  ", "gpt-x")])
        self.assertParses("paths.sessions_dir", [(" ~/sessions ", "~/sessions")])
        self.assertParses("editor", [("", ""), ("code --wait", "code --wait")])
        self.assertRejects("subagents.codex.model", ["", "   "])
        self.assertRejects("paths.sessions_dir", [""])
        self.assertRejects("editor", [None, 5])  # not text at all
        self.assertParses("review.adversarial", [("codex", "codex"), (" Claude ", "claude")])  # canonical case
        self.assertRejects("review.adversarial", ["", "gemini", "cod"])
        self.assertParses("paths.obsidian_vaults", [("~/a, ~/b ,,~/c", ("~/a", "~/b", "~/c")),
                                                    ("~/only", ("~/only",)), ("", ()), (" , ", ())])
        self.assertParses("guardrails.disabled_hooks", [("pre:bash:a, post:edit:b", ("pre:bash:a", "post:edit:b"))])

    def check_every_setting_parses_its_own_default(self) -> None:
        for setting in SETTINGS:
            default = get(DEFAULTS_CONFIG, setting.key)
            text = (",".join(default) if isinstance(default, tuple)
                    else str(default).lower() if isinstance(default, bool) else str(default))
            self.assertEqual(parse_value(setting, text), default, setting.key)

    def assertRejected(self, key: str, values: Any) -> None:
        for value in values:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    with_value(self.base, key, value)

    def check_each_kind_accepts_a_valid_value_and_lists_become_tuples(self) -> None:
        cases = [("guardrails.never_delete", False), ("subagents.codex.max_threads", 3),
                 ("subagents.claude.heavy", "claude-opus-4"), ("subagents.codex.heavy", "high"),
                 ("paths.sessions_dir", "~/elsewhere"), ("editor", "")]
        for key, value in cases:
            self.assertEqual(get(with_value(self.base, key, value), key), value, key)
        updated = with_value(self.base, "paths.obsidian_vaults", ["~/a", "~/b"])
        self.assertEqual(get(updated, "paths.obsidian_vaults"), ("~/a", "~/b"))
        updated = with_value(updated, "guardrails.disabled_hooks", ("x:y:z",))
        self.assertEqual(get(updated, "guardrails.disabled_hooks"), ("x:y:z",))
        self.assertEqual(json.loads(to_json(updated))["paths"]["obsidian_vaults"], ["~/a", "~/b"])

    def check_bad_values_and_keys_are_rejected_and_change_nothing(self) -> None:
        self.assertRejected("tools.claude", ["maybe", "", None, True, "AUTO"])
        self.assertRejected("review.adversarial", ["gemini"])
        self.assertRejected("guardrails.hook_profile", ["loud"])
        self.assertRejected("subagents.codex.max_threads", ["6", 6.0, 2.5, True, None, -1, 0, [6]])
        self.assertRejected("guardrails.context_budget_tokens", [0])
        self.assertRejected("guardrails.never_delete", ["true", "false", 1, 0, None, "yes"])
        self.assertRejected("subagents.codex.model", [5, "", None])
        self.assertRejected("paths.backups_dir", ["", None])
        self.assertRejected("editor", [None, 3])
        self.assertRejected("paths.obsidian_vaults", ["~/a", [1], [""]])
        self.assertRejected("guardrails.disabled_hooks", ["x", ["ok", None]])
        for key in ("nope", "tools", "tools.gemini", "subagents.claude"):
            with self.assertRaises(KeyError, msg=key):
                with_value(self.base, key, "x")
        self.assertEqual(self.base.data, DEFAULTS)

    def check_validate_reports_missing_keys_wrong_types_and_bad_enums_as_strings(self) -> None:
        warnings = validate(Config(data=MappingProxyType({}), path="", exists=False))
        self.assertEqual(len(warnings), len(SETTINGS))
        self.assertTrue(all(w.endswith(": missing") for w in warnings))

        guardrails = {**cfg._thaw(DEFAULTS["guardrails"]), "never_delete": "yes",
                      "context_budget_tokens": "lots", "disabled_hooks": "pre:bash:x"}
        threads = {**cfg._thaw(DEFAULTS["subagents"]), "codex": {**cfg._thaw(DEFAULTS["subagents"]["codex"]),
                                                               "max_threads": True}}  # bool is not an int
        result = validate(_raw(guardrails=guardrails, editor=7, subagents=threads))
        self.assertIsInstance(result, tuple)
        self.assertTrue(all(isinstance(w, str) for w in result))
        for key in ("guardrails.never_delete", "guardrails.context_budget_tokens",
                    "guardrails.disabled_hooks", "editor", "subagents.codex.max_threads"):
            self.assertIn(key, "\n".join(result))

        (warning,) = validate(_raw(review={"adversarial": "gemini"}))
        for fragment in ("review.adversarial", "gemini", "auto, codex, claude"):
            self.assertIn(fragment, warning)

    def check_vault_paths_are_checked_after_expanding_the_tilde(self) -> None:
        vault = os.path.join(self.root, "vault")
        os.makedirs(vault)
        ghost = os.path.join(self.root, "no", "such", "vault")
        file_path = write(os.path.join(self.root, "notes.txt"), "x")
        self.assertEqual(validate(with_value(self.base, "paths.obsidian_vaults", [vault])), ())
        warnings = validate(with_value(self.base, "paths.obsidian_vaults", [vault, ghost, file_path]))
        self.assertEqual(len(warnings), 2)  # one per bad entry
        self.assertTrue("does not exist" in warnings[0] and ghost in warnings[0])
        self.assertIn("not a directory", warnings[1])
        os.makedirs(os.path.join(self.root, "my-vault"))
        with mock.patch.dict(os.environ, {"HOME": self.root, "USERPROFILE": self.root}):
            self.assertEqual(validate(with_value(self.base, "paths.obsidian_vaults", ["~/my-vault"])), ())
            (warning,) = validate(with_value(self.base, "paths.obsidian_vaults", ["~/my-vault", "~/other-vault"]))
        self.assertIn("~/other-vault", warning)

    def check_formatting_order_newline_lists_and_unicode(self) -> None:
        text = to_json(load(self.paths))
        self.assertTrue(text.startswith('{\n  "version": 1,\n  "tools": {\n    "claude": "auto",'))
        self.assertTrue(text.endswith("}\n") and not text.endswith("\n\n"))
        self.assertIn('"disabled_hooks": []', text)
        parsed = json.loads(text)
        self.assertEqual(list(parsed), ["version", "tools", "subagents", "review", "guardrails", "paths", "editor"])
        self.assertEqual(list(parsed["subagents"]["codex"])[:2], ["model", "heavy"])
        text = to_json(with_value(load(self.paths), "paths.obsidian_vaults", ["~/café", "~/b"]))
        self.assertIn('"~/café"', text)  # tuples come back as lists, unicode is not escaped
        self.assertEqual(json.loads(text)["paths"]["obsidian_vaults"], ["~/café", "~/b"])

    def check_first_save_creates_parent_and_file_without_backup(self) -> None:
        self.assertFalse(os.path.exists(self.paths.agents_home))
        updated = with_value(load(self.paths), "editor", "nano")
        self.assertEqual(save(updated, self.paths), self.config_file)
        self.assertEqual(self.read_text(self.config_file), to_json(updated))
        self.assertEqual(self.backup_dirs(), [])
        self.assertEqual(stat.S_IMODE(os.stat(self.config_file).st_mode), 0o644)
        os.chmod(self.config_file, 0o600)  # an existing file keeps its mode across a save
        save(updated, self.paths)
        self.assertEqual(stat.S_IMODE(os.stat(self.config_file).st_mode), 0o600)
        elsewhere = os.path.join(self.root, "other", "cfg.json")  # the target follows Config.path
        self.assertEqual(save(dataclasses.replace(load(self.paths), path=elsewhere), self.paths), elsewhere)
        self.assertTrue(os.path.isfile(elsewhere))
        self.assertEqual(save(Config(data=DEFAULTS, path="", exists=False), self.paths), self.config_file)

    def check_save_backs_up_the_existing_file_with_copy2_even_when_it_is_broken(self) -> None:
        original = '{\n  "editor": "emacs",\n  "mine": true\n}\n'
        self.write_config(original)
        os.utime(self.config_file, (1_000_000_000, 1_000_000_000))
        save(with_value(load(self.paths), "editor", "nano"), self.paths)
        (backup_dir,) = self.backup_dirs()
        backup = os.path.join(backup_dir, "config.json")
        self.assertEqual(self.read_text(backup), original)
        self.assertEqual(int(os.stat(backup).st_mtime), 1_000_000_000)  # copy2 keeps metadata
        self.assertEqual((self.read_config_file()["editor"], self.read_config_file()["mine"]), ("nano", True))

        self.write_config("{not json")  # a file that failed to load is backed up too, then replaced
        loaded = load(self.paths)
        self.assertIsNotNone(loaded.error)
        save(loaded, self.paths)
        backed_up = [self.read_text(os.path.join(d, n)) for d in self.backup_dirs() for n in os.listdir(d)]
        self.assertIn("{not json", backed_up)
        self.assertEqual(self.read_config_file()["tools"]["claude"], "auto")

    def check_two_saves_in_one_second_keep_both_backups_under_backup_root(self) -> None:
        self.write_config('{"editor": "first"}')
        with self.fixed_backup_root():
            save(with_value(load(self.paths), "editor", "second"), self.paths)
            save(with_value(load(self.paths), "editor", "third"), self.paths)
        folder = os.path.join(self.paths.agents_home, "backups", "config-FIXED")
        saved = {}
        for name in sorted(os.listdir(folder)):
            saved[name] = json.loads(self.read_text(os.path.join(folder, name)))["editor"]
        self.assertEqual(saved, {"config.1.json": "second", "config.json": "first"})
        self.assertEqual(self.read_config_file()["editor"], "third")

    def check_write_is_atomic_temp_in_same_directory_then_os_replace(self) -> None:
        self.write_config("{}")
        real_replace, calls = os.replace, []

        def spy(src: str, dst: str) -> None:
            calls.append((src, dst))
            real_replace(src, dst)

        with mock.patch("installer.core.config.os.replace", side_effect=spy):
            save(load(self.paths), self.paths)
        ((src, dst),) = calls
        self.assertEqual(os.path.dirname(src), os.path.dirname(os.path.realpath(self.config_file)))
        self.assertNotEqual(src, dst)
        self.assertEqual(os.path.realpath(dst), os.path.realpath(self.config_file))
        self.assertEqual(self.temp_files(), [])

    def check_failed_write_keeps_original_and_moves_temp_aside(self) -> None:
        original = '{"editor": "keepme"}\n'
        self.write_config(original)
        with mock.patch("installer.core.config.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save(with_value(load(self.paths), "editor", "nano"), self.paths)
        self.assertEqual(self.read_text(self.config_file), original)
        self.assertEqual(self.temp_files(), [])
        (backup_dir,) = self.backup_dirs()
        names = sorted(os.listdir(backup_dir))
        self.assertIn("config.json", names)  # the pre-save copy
        self.assertTrue(any(n.startswith(".config.") for n in names))  # the quarantined temp file

    def check_no_delete_calls_terminal_use_personal_paths_or_oversize(self) -> None:
        with open(cfg.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for needle in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", "print(", "input(", "curses",
                       "sys.stdin", "tomllib", "/Users" + "/", "/home" + "/"):
            self.assertNotIn(needle, source, needle)
        self.assertLess(len(source.splitlines()), 500)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
