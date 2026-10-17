"""Tests for installer.core.capabilities: probing with stubbed which/run, Obsidian registry, helpers."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from installer.core import capabilities as caps_mod
from installer.core.capabilities import (
    PROBES,
    Capabilities,
    Capability,
    obsidian_registry_path,
    obsidian_vaults,
    probe,
    resolve_tool,
    to_context,
)
from installer.tests.fixtures import write

ALL_BINARIES = ("claude", "codex", "gemini", "git", "gh", "node", "docker", "python3", "uv", "bun",
                "deno", "go", "cargo", "tmux", "shellcheck")


def done(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def make_which(*present):
    return lambda name: "/fake/bin/" + name if name in present else None


class StubRun:
    """subprocess.run stand-in. table maps "basename arg arg" -> CompletedProcess | Exception."""

    def __init__(self, table=None):
        self.table = dict(table or {})
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        label = " ".join([os.path.basename(cmd[0])] + list(cmd[1:]))
        result = self.table.get(label, done())
        if isinstance(result, BaseException):
            raise result
        return result

    @property
    def labels(self):
        return [" ".join([os.path.basename(c[0])] + c[1:]) for c, _ in self.calls]


def quiet_probe(tmp, **kwargs):
    """probe() with an empty env, a temp home and linux paths, so nothing leaks from the machine."""
    base = dict(env={}, home=tmp, platform="linux")
    base.update(kwargs)
    return probe(**base)


class CapabilitiesTest(unittest.TestCase):
    def test_probe_binaries_and_failures(self):
        """Command contract, version parsing, failures contained, docker/headroom, CLI-never-run."""
        with tempfile.TemporaryDirectory() as tmp:
            run = StubRun({"git --version": done("git version 2.47.0\n"), "node -v": done("v22.12.0\n"),
                           "python3 --version": done("Python 3.12.1\n")})
            caps = quiet_probe(tmp, which=make_which(*ALL_BINARIES), run=run)
            self.assertEqual(tuple(caps.items), PROBES)
            self.assertEqual((caps.get("git").version, caps.get("git").path, caps.get("node").version,
                              caps.get("python").version), ("git version 2.47.0", "/fake/bin/git",
                                                           "v22.12.0", "Python 3.12.1"))
            # commands are argument lists with the documented kwargs; env only when supplied
            run = StubRun()
            quiet_probe(tmp, which=make_which("node", "tmux"), run=run, only=("node", "tmux"))
            self.assertEqual([c for c, _ in run.calls], [["node", "-v"], ["tmux", "-V"]])
            for _, kwargs in run.calls:
                self.assertEqual({k: v for k, v in kwargs.items() if k != "env"},
                                 {"timeout": 5, "capture_output": True, "text": True, "errors": "replace",
                                  "check": False})
            common = dict(which=make_which("git"), home=tmp, platform="linux", only=("git",))
            with_env, without_env = StubRun(), StubRun()
            probe(env={"PATH": "/x"}, run=with_env, **common)
            probe(env=None, run=without_env, **common)
            self.assertEqual(with_env.calls[0][1]["env"], {"PATH": "/x"})
            self.assertNotIn("env", without_env.calls[0][1])
            # absent binaries are never run
            run = StubRun()
            git = quiet_probe(tmp, which=make_which(), run=run).get("git")
            self.assertEqual((run.calls, git.present, git.version, git.path, git.detail),
                             ([], False, None, None, "not found on PATH"))

        version_cases = [  # binary on PATH, probe name, stub table, version, detail fragment
            ("deno", "deno", {"deno --version": done("\n  \ndeno 2.1.0 (stable)\nv8 13.0\n")},
             "deno 2.1.0 (stable)", ""),
            ("python3", "python", {"python3 --version": done("", "Python 2.7.18\n")}, "Python 2.7.18", ""),
            ("bun", "bun", {}, None, ""),
            ("gh", "gh", {"gh --version": done("unknown flag", "", 2)}, None, "status 2"),
        ]
        for binary, name, table, version, detail in version_cases:
            with self.subTest(binary), tempfile.TemporaryDirectory() as tmp:
                cap = quiet_probe(tmp, which=make_which(binary), run=StubRun(table), only=(name,)).get(name)
                self.assertEqual((cap.present, cap.version, cap.path), (True, version, "/fake/bin/" + binary))
                self.assertIn(detail, cap.detail)
        failures = [(FileNotFoundError("gone"), "not found"), (subprocess.TimeoutExpired(["git"], 5), "timed out"),
                    (PermissionError(13, "Permission denied"), "Permission denied"), (RuntimeError("boom"), "boom")]
        for error, text in failures:
            with self.subTest(error=repr(error)), tempfile.TemporaryDirectory() as tmp:
                run = StubRun({"git --version": error})
                caps = quiet_probe(tmp, which=make_which("git", "node"), run=run, only=("git", "node"))
                git = caps.get("git")
                self.assertEqual((git.present, git.version, git.path), (False, None, "/fake/bin/git"))
                self.assertIn(text, git.detail)
                self.assertTrue(caps.present("node"), "one failing probe must not affect the others")

        def bad_which(name):
            raise RuntimeError("which exploded")
        with tempfile.TemporaryDirectory() as tmp:
            caps = quiet_probe(tmp, which=bad_which, run=StubRun(), only=("git",))
            self.assertFalse(caps.present("git"))
            self.assertIn("which exploded", caps.get("git").detail)
            for target, field in (("obsidian_vaults", "vaults"), ("_nvm_versions", "nvm_versions")):
                with self.subTest(target), mock.patch.object(caps_mod, target, side_effect=RuntimeError("x")):
                    caps = quiet_probe(tmp, which=make_which(), run=StubRun(), only=("obsidian", "nvm", "git"))
                    self.assertEqual(getattr(caps, field), ())
                    self.assertIn("git", caps.items)

            # docker: daemon states
            for info, detail in ((done("Server: ..."), "daemon running"),
                                 (done("", "Cannot connect", 1), "installed, daemon not running"),
                                 (subprocess.TimeoutExpired(["docker", "info"], 5), "installed, daemon not running")):
                run = StubRun({"docker --version": done("Docker version 27.0.1\n"), "docker info": info})
                cap = quiet_probe(tmp, which=make_which("docker"), run=run, only=("docker",)).get("docker")
                self.assertEqual((cap.present, cap.version), (True, "Docker version 27.0.1"))
                self.assertTrue(cap.detail.startswith(detail), cap.detail)
                self.assertEqual(run.labels, ["docker --version", "docker info"])

            # headroom: PATH, then ~/.local/bin, otherwise absent
            def headroom(which, table=None):
                run = StubRun(table or {"headroom --version": done("headroom 0.4.2\n")})
                return quiet_probe(tmp, which=which, run=run, only=("headroom",)).get("headroom"), run
            self.assertFalse(headroom(make_which())[0].present)
            cap, _ = headroom(make_which("headroom"))
            self.assertEqual((cap.present, cap.version, cap.detail), (True, "headroom 0.4.2", "on PATH"))
            cap, _ = headroom(make_which("headroom"), {"headroom --version": subprocess.TimeoutExpired(["h"], 5)})
            self.assertFalse(cap.present)
            local = write(os.path.join(tmp, ".local", "bin", "headroom"), "#!/bin/sh\n")
            cap, run = headroom(make_which())
            self.assertEqual((run.calls[0][0], cap.present, cap.path), ([local, "--version"], True, local))

            # the Obsidian CLI may launch the app, so it must never run
            run = StubRun()
            cap = quiet_probe(tmp, which=make_which("obsidian"), run=run, only=("obsidian",)).get("obsidian")
            self.assertEqual((cap.present, cap.path, run.calls), (True, "/fake/bin/obsidian", []))
            self.assertIn("CLI on PATH", cap.detail)

            # the default which searches the supplied PATH, not the process one
            self.assertFalse(probe(env={"PATH": ""}, home=tmp, platform="linux", only=("git",)).present("git"))

            # only= limits items and calls, keeping PROBES order
            run = StubRun()
            caps = quiet_probe(tmp, which=make_which(*ALL_BINARIES), run=run, only=("node", "git"))
            self.assertEqual(tuple(caps.items), ("git", "node"))
            self.assertEqual(sorted(run.labels), ["git --version", "node -v"])

    def test_filesystem_probes(self):
        """nvm, Obsidian app and vault registry, registry paths: all under a temp home."""
        with tempfile.TemporaryDirectory() as tmp:
            def nvm(env=None):
                return quiet_probe(tmp, env=env or {}, only=("nvm",), which=make_which(), run=StubRun())
            self.assertEqual((nvm().present("nvm"), nvm().nvm_versions), (False, ()))
            root = os.path.join(tmp, ".nvm", "versions", "node")
            for name in ("v22.12.0", "v24.12.0", "v9.11.2", "v22.9.0", "notes"):
                os.makedirs(os.path.join(root, name))
            write(os.path.join(root, "stray.txt"), "x")
            caps = nvm()
            self.assertEqual((caps.get("nvm").present, caps.get("nvm").version), (True, "v24.12.0"))
            self.assertEqual(caps.nvm_versions, ("v24.12.0", "v22.12.0", "v22.9.0", "v9.11.2", "notes"))
            custom = os.path.join(tmp, "custom-nvm")
            os.makedirs(os.path.join(custom, "versions", "node", "v20.1.0"))
            self.assertEqual(nvm({"NVM_DIR": custom}).nvm_versions, ("v20.1.0",))

        with tempfile.TemporaryDirectory() as tmp:
            apps = os.path.join(tmp, "Applications")
            common = dict(which=make_which(), run=StubRun(), only=("obsidian",))
            with mock.patch.object(caps_mod, "DARWIN_APP_DIRS", (apps,)):
                self.assertFalse(quiet_probe(tmp, platform="darwin", **common).present("obsidian"))
                os.makedirs(os.path.join(apps, "Obsidian.app"))
                self.assertIn("app installed", quiet_probe(tmp, platform="darwin", **common).get("obsidian").detail)
                self.assertFalse(quiet_probe(tmp, platform="linux", **common).present("obsidian"),
                                 "the .app only counts on darwin")
            vault = os.path.join(tmp, "notes")
            os.makedirs(vault)
            write(obsidian_registry_path(tmp, "linux", {}),
                  json.dumps({"vaults": {"a": {"path": vault, "open": True}}}))
            caps = quiet_probe(tmp, **common)
            self.assertEqual((caps.present("obsidian"), caps.vaults), (True, (vault,)))
            self.assertIn("vault registry found", caps.get("obsidian").detail)

        home = os.path.join("H", "me")
        j = os.path.join
        for platform, env, expected in (
                ("darwin", {}, j(home, "Library", "Application Support", "obsidian", "obsidian.json")),
                ("linux", {"XDG_CONFIG_HOME": j("X", "cfg")}, j("X", "cfg", "obsidian", "obsidian.json")),
                ("linux", {"XDG_CONFIG_HOME": ""}, j(home, ".config", "obsidian", "obsidian.json")),
                ("win32", {"APPDATA": j("A", "Roaming")}, j("A", "Roaming", "obsidian", "obsidian.json"))):
            self.assertEqual(obsidian_registry_path(home, platform, env), expected, platform)

        for platform in ("darwin", "linux", "win32"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                env = {"APPDATA": os.path.join(tmp, "appdata")} if platform == "win32" else {}
                dirs = {n: os.path.join(tmp, "vaults", n) for n in ("one", "two", "three", "four")}
                for path in dirs.values():
                    os.makedirs(path)
                write(obsidian_registry_path(tmp, platform, env), json.dumps({"vaults": {
                    "id1": {"path": dirs["one"], "ts": 1}, "id2": {"path": os.path.join(tmp, "vaults", "gone")},
                    "id3": {"path": dirs["two"], "open": True}, "id4": {"path": dirs["three"], "open": False},
                    "id5": {"path": dirs["one"]}, "id6": {"path": dirs["four"], "open": True}}}))
                self.assertEqual(obsidian_vaults(tmp, platform, env),
                                 (dirs["two"], dirs["four"], dirs["one"], dirs["three"]))
        for payload in ("", "{not json", "[]", '{"vaults": []}', '{"vaults": {"a": "str", "b": {"path": 5}}}'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                write(obsidian_registry_path(tmp, "linux", {}), payload)
                self.assertEqual(obsidian_vaults(tmp, "linux", {}), ())
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(obsidian_vaults(tmp, "darwin", {}), (), "missing registry")

    def test_types_and_helpers(self):
        git = Capability("git", True, "git version 2", "/x/git", "")
        caps = Capabilities(items={"git": git}, vaults=["a"])
        self.assertIs(caps.get("git"), git)
        self.assertTrue(caps.present("git"))
        self.assertFalse(caps.present("nope"))
        self.assertEqual(caps.get("nope").detail, "not probed")
        self.assertEqual((caps.vaults, caps.nvm_versions), (("a",), ()))
        with self.assertRaises(TypeError):
            caps.items["x"] = git
        with self.assertRaises(dataclasses.FrozenInstanceError):
            caps.vaults = ()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            git.present = False
        source = {"git": git}
        copied = Capabilities(items=source)
        source["gh"] = git
        self.assertNotIn("gh", copied.items)

        present, absent = Capability("x", True, None, None, ""), Capability("x", False, None, None, "")
        for setting, cap, expected in (
                ("auto", present, True), ("auto", absent, False), ("on", absent, True), ("off", present, False),
                (" ON ", absent, True), ("maybe", present, True), ("maybe", absent, False)):
            with self.subTest(setting=setting, present=cap.present):
                self.assertIs(resolve_tool(setting, cap), expected)

        full = Capabilities(items={
            "claude": Capability("claude", True, "2.0.1", "/fake/bin/claude", "ok"),
            "codex": Capability("codex", False, None, None, "not found on PATH"),
        }, vaults=("v",), nvm_versions=("v1.0.0",))
        ctx = to_context(full)
        self.assertEqual(ctx, {"claude": {"present": True, "version": "2.0.1", "path": "/fake/bin/claude"},
                               "codex": {"present": False, "version": None, "path": None}})
        json.dumps(ctx)  # plain data only
        ctx["claude"]["present"] = False  # a fresh copy each call
        self.assertTrue(to_context(full)["claude"]["present"])


if __name__ == "__main__":
    unittest.main()
