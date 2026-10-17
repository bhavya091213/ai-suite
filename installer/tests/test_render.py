"""Tests for installer.core.render: every tag, filter and rule, build_context and render_tree."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import types
import unittest
from typing import Mapping, Optional
from unittest import mock

from installer.core import render
from installer.core.capabilities import Capabilities, Capability
from installer.core.paths import Paths
from installer.core.render import (ALWAYS_TEMPLATE, RenderError, RenderReport, build_context,
                                   is_template, render_text, render_tree, requirements_met,
                                   requires_of)

HOME = "/srv/demo"
MARK = "<!-- installer:template -->\n"


def cap(present: bool, version: Optional[str] = None, detail: str = "") -> Mapping:
    return {"present": present, "version": version, "path": "/bin/x" if present else None, "detail": detail}


CONFIG: Mapping = {
    "tools": {"claude": "auto", "codex": "auto"},
    "subagents": {"claude": {"heavy": "opus", "light": "sonnet", "trivial": "haiku"},
                  "codex": {"model": "gpt-x", "heavy": "xhigh", "light": "medium", "trivial": "low"}},
    "review": {"adversarial": "auto"},
    "guardrails": {"never_delete": True, "context_budget_tokens": 100000, "hook_profile": "strict",
                   "disabled_hooks": ["pre:bash:one", "post:edit:two"]},
    "paths": {"obsidian_vaults": [HOME + "/vault-a", "/elsewhere/vault-b"],
              "sessions_dir": HOME + "/.claude/sessions", "backups_dir": ""},
}
CAPS: Mapping = {
    "claude": cap(True, "2.0"), "codex": cap(True, "0.5"), "gemini": cap(False),
    "docker": cap(True, "27.1", "installed, daemon not running"), "tmux": cap(False),
    "headroom": cap(False), "obsidian": cap(True, None, "app found"), "git": cap(True, "2.45"),
    "node": cap(True, "v22.12.0"), "nvm": cap(True, "v24.12.0"),
}
PATHS = Paths(repo_dir=HOME + "/repo", agents_home=HOME + "/.agents",
              claude_home=HOME + "/.claude", codex_home=HOME + "/.codex")
ENV = {"HOME": HOME, "USER": "tester", "SECRET": "nope"}


def ctx(config: Mapping = CONFIG, caps: Mapping = CAPS, env: Mapping = ENV) -> Mapping:
    return build_context(config, caps, PATHS, env)


def out(template: str, context: Optional[Mapping] = None) -> str:
    return render_text(MARK + template, context or ctx())[0]


def warns(template: str, source: str = "t.md") -> tuple:
    return render_text(MARK + template, ctx(), source)[1]


class RenderTextTests(unittest.TestCase):
    def test_values_filters_logic_warnings_and_syntax_errors(self):
        # values and integer path segments
        self.assertEqual(out("a {{ config.subagents.codex.model }} b\n"), "a gpt-x b\n")
        context = {"v": {"items": ["a", "b"], "none": None, "yes": True, "no": False, "n": 3}}
        self.assertEqual(out("{{ v.items }}|{{ v.none }}|{{ v.yes }}|{{ v.no }}|{{ v.n }}\n", context),
                         "a, b||true|false|3\n")
        self.assertEqual(out("{{ profile.vaults.0 }}|{{ profile.vaults.1 }}\n"), HOME + "/vault-a|/elsewhere/vault-b\n")
        self.assertEqual(warns("{{ profile.vaults.9 }}\n"), ("t.md:2: unknown value profile.vaults.9",))
        # filters and literals
        near = {"env": {"HOME": HOME}, "p": HOME + "2/x"}  # a longer sibling directory is not under $HOME
        sizes = {"a": 100000, "b": 1500000, "c": 999, "d": "text"}
        cases = [
            ("{{ profile.sessions_dir | tilde }}", None, "~/.claude/sessions"),
            ("{{ env.HOME | tilde }}", None, "~"),
            ("{{ profile.vaults | tilde }}", None, "~/vault-a, /elsewhere/vault-b"),
            ("{{ p | tilde }}", near, HOME + "2/x"),
            ("{{ a | k }} {{ b | k }} {{ c | k }} {{ d | k }}", sizes, "100k 1.5M 999 text"),
            ('{{ profile.disabled_hooks | join(" / ") }}', None, "pre:bash:one / post:edit:two"),
            ('{{ profile.disabled_hooks | join("+") | default("x") }}', None, "pre:bash:one+post:edit:two"),
            ('{{ (profile.gemini or profile.tmux) | default("nope") }}', None, "nope"),
            ('{{ "a\\"b\\tc" }}{{ 42 }}{{ -7 }}', None, 'a"b\tc42-7'),
        ]
        for template, context, expected in cases:
            with self.subTest(template=template):
                self.assertEqual(out(template + "\n", context), expected + "\n")
        # operators and precedence
        cases = [
            ("not profile.gemini", True), ("profile.claude and profile.codex", True),
            ("profile.gemini or profile.codex", True), ("profile.gemini and profile.codex or profile.git", True),
            ("profile.gemini and (profile.codex or profile.git)", False),
            ('profile.review_backend == "codex"', True), ('profile.review_backend != "codex"', False),
            ("not profile.gemini and profile.git", True), ("not (profile.git and profile.claude)", False),
            ("profile.context_budget == 100000", True), ('profile.hook_profile == "strict" and not profile.tmux', True),
            ("profile.vaults.0 == config.paths.obsidian_vaults.0", True),
        ]
        for expr, expected in cases:
            with self.subTest(expr=expr):
                self.assertEqual(out("{% if " + expr + " %}Y{% else %}N{% endif %}\n"), "Y\n" if expected else "N\n")
        # conditional chains and block line consumption
        block = "a\n{% if profile.claude %}\nb\n{% else %}\nc\n{% endif %}\nd\n"
        nested = ("{% if profile.claude %}\n{% if profile.gemini %}\ng\n{% else %}\nnot-g\n{% endif %}\n"
                  "{% endif %}\nend\n")
        chain = "{% if profile.gemini %}G{% elif profile.codex %}C{% else %}N{% endif %}\n"
        cases = [
            (chain, None, "C\n"), (chain, ctx(caps={}), "N\n"), (chain, ctx(caps={"gemini": cap(True)}), "G\n"),
            (block, None, "a\nb\nd\n"),
            (block, ctx({"tools": {"claude": "off"}}, {}), "a\nc\nd\n"),
            (nested, None, "not-g\nend\n"),
            ("a\n    {% if profile.git %}  \nb\n  {% endif %}\nc\n", None, "a\nb\nc\n"),
            ("a\r\n{% if profile.git %}\r\nb\r\n{% endif %}\r\nc\r\n", None, "a\r\nb\r\nc\r\n"),
            ("x {% if profile.git %}git{% endif %} y\n", None, "x git y\n"),
            ("x {% if profile.gemini %}gem{% endif %} y\n", None, "x  y\n"),
            ("{{ env.USER }}{% if profile.git %}\n{% endif %}z\n", None, "tester\nz\n"),
        ]
        for template, context, expected in cases:
            with self.subTest(template=template):
                self.assertEqual(out(template, context), expected)
        # for loops loop variables and scope
        loop = ("{% for v in profile.vaults %}\n{{ loop.index }}:{{ v | tilde }}"
                "{% if loop.first %} first{% endif %}{% if loop.last %} last{% endif %}\n{% endfor %}\n")
        self.assertEqual(out(loop), "1:~/vault-a first\n2:/elsewhere/vault-b last\n")
        nested = ("{% for row in rows %}[{% for c in row %}{{ c }}{% if not loop.last %},{% endif %}"
                  "{% endfor %}]{% endfor %}\n")
        self.assertEqual(out(nested, {"rows": [["a", "b"], ["c"]]}), "[a,b][c]\n")
        self.assertEqual(warns("{% for v in profile.vaults %}{% endfor %}[{{ v }}]\n"),
                         ("t.md:2: unknown value v",))  # the loop variable does not leak
        # unknown paths are empty falsy and warn once with original line numbers
        text, found = render_text(MARK + "a\n[{{ nope.deep.path }}]\n", ctx(), "doc.md")
        self.assertEqual(text, "a\n[]\n")
        self.assertEqual(found, ("doc.md:3: unknown value nope.deep.path",))
        shifted = "<!-- installer:requires codex -->\n" + MARK + "x\n{% if profile.git %}\n{{ a.b }}\n{% endif %}\n"
        self.assertEqual(render_text(shifted, ctx(), "f")[1], ("f:5: unknown value a.b",))
        self.assertEqual(out("{% if what.ever %}Y{% else %}N{% endif %}\n"), "N\n")
        self.assertEqual(warns("{% if what.ever %}Y{% endif %}\n"), ("t.md:2: unknown value what.ever",))
        self.assertEqual(warns("{{ caps.gemini.version }}\n"), ())  # None is a value, not a miss
        self.assertEqual(len(warns("{{ a.b }}{{ a.b }}\n")), 1)
        # syntax errors raise with source and line
        cases = [
            ("a\n{% if profile.git %}\nb\n", "unclosed", 3),
            ("{% for v in profile.vaults %}\nb\n", "unclosed", 2),
            ("a\n{% endif %}\n", "unexpected", 3),
            ("{% for v in profile.vaults %}\n{% endif %}\n", "unexpected", 3),
            ("{% if profile.git %}\n{% else %}\n{% elif profile.git %}\n{% endif %}\n", "after", None),
            ("{% if profile.git %}\n{% else x %}\n{% endif %}\n", "takes no expression", 3),
            ("{% include other %}\n", "unknown tag", 2),
            ("{% for v profile.vaults %}\n{% endfor %}\n", "malformed", 2),
            ("{% if %}\n{% endif %}\n", "empty expression", 2),
            ("a\n{{ profile.git\n", "unterminated", 3),
            ("{% if profile.git\n", "unterminated", 2),
            ("{{ profile.git | nosuch }}\n", "unknown filter", 2),
            ("{{ profile.git | }}\n", "filter name", 2),
            ("{{ profile.git | default }}\n", "argument", 2),
            ("{% if profile.gemini %}\n{{ x | nosuch }}\n{% endif %}\n", "unknown filter", 3),  # untaken branch
            ("{{ profile.git and }}\n", "", 2), ("{{ (profile.git }}\n", "", 2),
            ("{{ profile.git profile.codex }}\n", "", 2), ("{{ == 1 }}\n", "", 2), ("{{ a $ b }}\n", "", 2),
            ('{{ profile.git | join("a" "b") }}\n', "')'", 2),
        ]
        for template, fragment, line in cases:
            with self.subTest(template=template), self.assertRaises(RenderError) as caught:
                render_text(MARK + template, ctx(), "bad.md")
            message = str(caught.exception)
            self.assertIn(fragment, message)
            self.assertTrue(message.startswith(f"bad.md:{line or ''}"), message)


class RequirementsAndContextTests(unittest.TestCase):
    def test_requires_rules_and_build_context(self):
        # requires markers parse and requirements are checked against the profile
        for header, expected in (
                ("<!-- installer:requires codex -->\nx\n", (("codex",), "all")),
                ("---\n# installer:requires codex git\n---\n", (("codex", "git"), "all")),
                ("<!-- installer:requires-any codex gemini -->\n", (("codex", "gemini"), "any")),
                ("<!--installer:requires codex-->\n", (("codex",), "all")),
                ("# installer:requires codex  # because\n", (("codex",), "all")),
                ("# nothing here\n", ((), "all")),
                ("1\n2\n3\n4\n5\n<!-- installer:requires codex -->\n", ((), "all"))):
            with self.subTest(header=header):
                self.assertEqual(requires_of(header), expected)
        for body, expected in (("codex docker\n", (("codex", "docker"), "all")),
                               ("codex\ngit\n", (("codex", "git"), "all")),
                               ("any: codex gemini\n", (("codex", "gemini"), "any")),
                               ("  \n", ((), "all"))):
            with self.subTest(body=body):
                self.assertEqual(render.parse_requires_file(body), expected)

        context = ctx()
        self.assertTrue(requirements_met((), "all", context))
        self.assertTrue(requirements_met(("codex", "git"), "all", context))
        self.assertFalse(requirements_met(("codex", "gemini"), "all", context))
        self.assertTrue(requirements_met(("gemini", "codex"), "any", context))
        self.assertFalse(requirements_met(("gemini", "tmux"), "any", context))
        self.assertFalse(requirements_met(("no_such_key",), "all", context))
        # a malformed requires marker raises instead of disabling the gate
        for header in ("<!-- installer:requires codex, gemini -->", "# installer:requires gemini,",
                       "<!-- installer:requires -->", "<!-- installer:requires-any -->",
                       "<!-- installer:requires `codex` -->"):
            with self.subTest(header=header), self.assertRaises(RenderError) as caught:
                requires_of(header + "\nbody\n")
            self.assertTrue(str(caught.exception).startswith("<text>:1:"), str(caught.exception))
            self.assertIn("installer:requires", str(caught.exception))
        for body in ("codex, gemini", "# needs gemini\ngemini", "any: gemini, tmux", "any:", "ANY: codex"):
            with self.subTest(body=body), self.assertRaises(RenderError):
                render.parse_requires_file(body)
        # tools review backend and vaults
        forced = {"tools": {"claude": "off", "codex": "on", "gemini": "on"}}
        auto = {"claude": True, "codex": True, "gemini": False, "docker": True, "tmux": False,
                "headroom": False, "obsidian": True, "git": True, "node": True, "review_backend": "codex",
                "vaults": (HOME + "/vault-a", "/elsewhere/vault-b"), "default_vault": HOME + "/vault-a"}
        for name, config, caps, expected in (
                ("auto", CONFIG, CAPS, auto),
                ("forced", forced, CAPS, {"claude": False, "codex": True, "gemini": True}),
                ("empty", {}, {}, {"claude": False, "codex": False, "vaults": (), "default_vault": ""}),
                ("codex off", {"tools": {"codex": "off"}}, CAPS, {"review_backend": "claude"}),
                ("claude pinned", {"review": {"adversarial": "claude"}}, CAPS, {"review_backend": "claude"}),
                ("codex pinned", {"review": {"adversarial": "codex"}}, {}, {"review_backend": "codex"})):
            profile = ctx(config, caps)["profile"]
            for key, value in expected.items():
                with self.subTest(name, key=key):
                    self.assertEqual(profile[key], value)
        # node nvm and docker state
        running = dict(CAPS, docker=cap(True, "27", "daemon running"), nvm_versions=["v24.12.0", "v22.1.0"])
        for caps, expected in ((CAPS, ("v22.12.0", ("v24.12.0",), "installed")),
                               (running, ("v22.12.0", ("v24.12.0", "v22.1.0"), "running")),
                               ({}, ("", (), "absent")),
                               (Capabilities(items={}), ("", (), "absent"))):
            profile = ctx(CONFIG, caps)["profile"]
            with self.subTest(expected=expected):
                self.assertEqual((profile["node_version"], profile["nvm_versions"], profile["docker_state"]), expected)
        for detail, state in (("daemon running", "running"), ("installed, daemon not running", "installed")):
            probed = Capabilities(items={"docker": Capability("docker", True, "27.1", "/bin/docker", detail),
                                         "git": Capability("git", True, "2.45", "/bin/git", "")},
                                  nvm_versions=("v24.12.0", "v22.1.0"))  # the real probe result, not a mapping
            profile = build_context(CONFIG, probed, PATHS, ENV)["profile"]
            self.assertEqual((profile["docker_state"], profile["nvm_versions"], profile["git"]),
                             (state, ("v24.12.0", "v22.1.0"), True))
        with self.assertRaises(TypeError):
            build_context(CONFIG, 42, PATHS, ENV)  # type: ignore[arg-type]
        # model tiers context budget paths and hooks
        profile = ctx()["profile"]
        self.assertEqual([profile[k] for k in ("claude_heavy", "claude_light", "claude_trivial", "codex_model",
                                               "codex_heavy", "codex_light", "codex_trivial")],
                         ["opus", "sonnet", "haiku", "gpt-x", "xhigh", "medium", "low"])
        self.assertEqual((profile["context_budget"], profile["context_budget_k"]), (100000, "100k"))
        self.assertEqual((profile["sessions_dir"], profile["backups_dir"]),
                         (HOME + "/.claude/sessions", HOME + "/.agents/backups"))
        self.assertEqual((profile["hook_profile"], profile["disabled_hooks"]),
                         ("strict", ("pre:bash:one", "post:edit:two")))
        bare = ctx({}, {})["profile"]  # defaults when the config is empty
        self.assertEqual((bare["claude_light"], bare["codex_trivial"], bare["codex_model"]),
                         ("sonnet", "low", "gpt-5.6-sol"))
        self.assertEqual((bare["hook_profile"], bare["disabled_hooks"]), ("standard", ()))
        big, bad = ({"guardrails": {"context_budget_tokens": n}} for n in (1500000, "lots"))
        self.assertEqual(ctx(big, {})["profile"]["context_budget_k"], "1.5M")
        self.assertEqual(ctx(bad, {})["profile"]["context_budget"], 100000)
        # caps config and env pass through and the context is read only
        context = ctx()
        self.assertEqual(dict(context["env"]), {"HOME": HOME, "USER": "tester"})  # SECRET is not exposed
        self.assertEqual(context["caps"]["docker"]["detail"], "installed, daemon not running")
        self.assertEqual(context["config"]["guardrails"]["hook_profile"], "strict")
        sparse = build_context({}, {"zig": {"present": True}}, None, {"HOME": HOME})
        self.assertEqual(dict(sparse["caps"]["zig"]), {"present": True, "version": None, "path": None, "detail": ""})
        config, caps = {"guardrails": {"disabled_hooks": ["a"]}}, {"git": {"present": True}}
        context = build_context(config, caps, PATHS, ENV)
        self.assertEqual((config, caps), ({"guardrails": {"disabled_hooks": ["a"]}}, {"git": {"present": True}}))
        for key, value in (("profile", {}), ("extra", 1)):
            with self.assertRaises(TypeError):
                context[key] = value  # type: ignore[index]
        with self.assertRaises(TypeError):
            context["profile"]["codex"] = False  # type: ignore[index]


# ------------------------------------------------------------------ render_tree

def write(path: str, text: str, mode: Optional[int] = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    if mode is not None:
        os.chmod(path, mode)


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def identity(rel: str, text: str, context: Mapping) -> str:
    return text


class RenderTreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.src = os.path.join(self.root, "src")
        self.dst = os.path.join(self.root, "dst")
        self.binary = b"\xff\xfe\x00\x01PNG\x80"
        outside = os.path.join(self.root, "outside.txt")
        write(outside, "outside\n")
        for rel, text, mode in (
                ("tpl.md", MARK + "Hi {{ env.USER }} {{ nope.x }}\n", None),
                ("tpl2.md", MARK + "Hi {{ env.USER }}\n", None),
                ("plain.txt", "{{ x }}\n{% if y %}\n", None),
                ("needs-gemini.md", "<!-- installer:requires gemini -->\nbody\n", None),
                ("any.md", "<!-- installer:requires-any gemini codex -->\nkept\n", None),
                ("run.sh", "#!/bin/sh\necho hi\n", 0o755), ("ro.txt", "locked\n", 0o444),
                (".DS_Store", "junk", None), ("__pycache__/x.pyc", "junk", None),
                ("real/inner.txt", "inner\n", None),
                ("gated/.installer-requires", "gemini\n", None), ("gated/file.md", "never\n", None),
                ("open/.installer-requires", "any: gemini codex\n", None), ("open/file.md", "yes\n", None)):
            write(os.path.join(self.src, rel), text, mode)
        with open(os.path.join(self.src, "blob.bin"), "wb") as handle:
            handle.write(self.binary)
        for name, target in {"linked": "real", "link-tpl.md": "tpl2.md", "link-gated.md": "needs-gemini.md",
                             "link-run.sh": "run.sh", "link-gdir": "gated", "node_modules": "real",
                             "link-out.md": outside, "link-broken.md": "missing.md"}.items():
            os.symlink(target, os.path.join(self.src, name))

    def path(self, *parts: str) -> str:
        return os.path.join(self.dst, *parts)

    def tree(self, out: str = "", prefix: str = "shared", rewrite_fn=identity, src: str = "") -> RenderReport:
        return render_tree(src or self.src, out or self.dst, ctx(), prefix, rewrite_fn)

    def test_report_output_exclusions_symlinks_modes_and_output_safety(self):
        report = self.tree()
        self.assertEqual(sorted(report.rendered), ["shared/link-tpl.md", "shared/tpl.md", "shared/tpl2.md"])
        self.assertEqual(set(report.copied), {
            "shared/plain.txt", "shared/any.md", "shared/run.sh", "shared/ro.txt", "shared/blob.bin",
            "shared/linked", "shared/real/inner.txt", "shared/open/file.md", "shared/link-run.sh"})
        excluded = dict(report.excluded)
        gated = ("shared/needs-gemini.md", "shared/gated", "shared/link-gated.md", "shared/link-gdir")
        self.assertEqual(set(excluded), set(gated) | {"shared/link-out.md", "shared/link-broken.md"})
        self.assertEqual({excluded[rel] for rel in gated}, {"requires gemini"})
        self.assertIn("outside", excluded["shared/link-out.md"])
        self.assertIn("broken", excluded["shared/link-broken.md"])
        self.assertEqual(report.warnings, ("shared/tpl.md:2: unknown value nope.x",))
        for name in ("needs-gemini.md", "gated", "link-gated.md", "link-gdir", "link-out.md", "link-broken.md",
                     ".DS_Store", "__pycache__", "node_modules"):  # excluded, gated or ignored: never written
            self.assertFalse(os.path.lexists(self.path(name)), name)
        self.assertEqual(os.listdir(self.path("open")), ["file.md"])  # .installer-requires is never copied
        self.assertEqual(read(self.path("tpl.md")), "Hi tester \n")
        self.assertEqual(read(self.path("link-tpl.md")), "Hi tester\n")  # a file link is rendered through its target
        self.assertEqual(read(self.path("plain.txt")), "{{ x }}\n{% if y %}\n")  # Jinja-looking text survives
        self.assertEqual(read(self.path("any.md")), "kept\n")  # the requires marker line is dropped
        with open(self.path("blob.bin"), "rb") as handle:
            self.assertEqual(handle.read(), self.binary)
        self.assertEqual(os.readlink(self.path("linked")), "real")  # a directory link is recreated, not followed
        for name in ("run.sh", "link-run.sh"):
            self.assertTrue(os.stat(self.path(name)).st_mode & stat.S_IXUSR, name)
        self.assertFalse(os.path.islink(self.path("link-run.sh")))
        self.assertEqual(stat.S_IMODE(os.stat(self.path("ro.txt")).st_mode), 0o444)
        alias = os.path.join(self.root, "alias")
        os.symlink(self.src, alias)
        for target in (os.path.join(self.src, "stage"), os.path.join(alias, "stage")):  # output inside the source
            with self.subTest(out=target), self.assertRaises(RenderError) as caught:
                self.tree(target)
            self.assertIn("inside", str(caught.exception))
        self.assertFalse(os.path.lexists(os.path.join(self.src, "stage")))
        self.assertIn("shared/tpl.md", self.tree(os.path.join(self.root, "src-out")).rendered)  # name prefix only
        existing = os.path.join(self.root, "existing")
        os.makedirs(existing)
        for source, target in ((self.src, existing), (os.path.join(self.root, "nope"), os.path.join(self.root, "o"))):
            with self.subTest(source=source), self.assertRaises(RenderError):
                self.tree(target, src=source)
        bad_syntax = os.path.join(self.root, "bad-syntax")
        write(os.path.join(bad_syntax, "broken.md"), MARK + "{% if profile.git %}\n")
        bad_file = os.path.join(self.root, "bad-file")
        write(os.path.join(bad_file, "bad.md"), "<!-- installer:requires gemini, tmux -->\nbody\n")
        bad_sub = os.path.join(self.root, "bad-sub")
        write(os.path.join(bad_sub, "sub", ".installer-requires"), "codex, gemini")
        write(os.path.join(bad_sub, "sub", "f.md"), "f\n")
        bad_root = os.path.join(self.root, "bad-root")
        write(os.path.join(bad_root, ".installer-requires"), "# needs gemini\ngemini")
        for source, prefix in ((bad_syntax, "shared/broken.md:"), (bad_file, "shared/bad.md:1:"),
                               (bad_sub, "shared/sub/.installer-requires:"), (bad_root, "shared/.installer-requires")):
            with self.subTest(prefix), self.assertRaises(RenderError) as caught:
                self.tree(os.path.join(self.root, "out-" + os.path.basename(source)), src=source)
            self.assertTrue(str(caught.exception).startswith(prefix), str(caught.exception))

    def test_markers_always_template_requires_files_and_rewrite_hooks(self):
        self.assertTrue(is_template("#!/bin/sh\n# installer:template\n"))
        self.assertTrue(is_template("1\n2\n3\n4\n# installer:template\n"))
        self.assertFalse(is_template("1\n2\n3\n4\n5\n# installer:template\n"))
        self.assertFalse(is_template("{{ x }}\n{% if y %}\n"))
        self.assertIn("codex/AGENTS.md", ALWAYS_TEMPLATE)
        text = MARK + "a\nb\nc\nd\ne\nf <!-- installer:template -->\ng\n"
        self.assertEqual(render_text(text, ctx())[0], "a\nb\nc\nd\ne\ng\n")
        shell = "#!/bin/sh\n# installer:template\n# installer:requires codex\necho {{ env.USER }}\n"
        self.assertEqual(render_text(shell, ctx())[0], "#!/bin/sh\necho tester\n")
        codex = os.path.join(self.root, "codex-src")  # ALWAYS_TEMPLATE renders without a marker
        write(os.path.join(codex, "AGENTS.md"), "user={{ env.USER }}\n")
        write(os.path.join(codex, "README.md"), "user={{ env.USER }}\n")
        report = self.tree(os.path.join(self.root, "codex-dst"), "codex", src=codex)
        self.assertEqual(read(os.path.join(self.root, "codex-dst", "AGENTS.md")), "user=tester\n")
        self.assertEqual(read(os.path.join(self.root, "codex-dst", "README.md")), "user={{ env.USER }}\n")
        self.assertEqual(report.rendered, ("codex/AGENTS.md",))
        gated = os.path.join(self.root, "gated-src")  # an unmet root .installer-requires excludes everything
        write(os.path.join(gated, ".installer-requires"), "gemini")
        write(os.path.join(gated, "a.md"), "a\n")
        report = self.tree(os.path.join(self.root, "gated-dst"), src=gated)
        self.assertEqual(report.excluded, (("shared", "requires gemini"),))
        self.assertEqual(os.listdir(os.path.join(self.root, "gated-dst")), [])
        calls, rewritten = [], os.path.join(self.root, "rewritten")

        def recorder(rel: str, text: str, context: Mapping) -> str:
            calls.append((rel, context is not None))
            return text.upper() if rel.endswith(("plain.txt", "tpl.md")) else text

        self.tree(rewritten, "claude-code", recorder)
        rels = {rel for rel, _ in calls}
        self.assertTrue({"claude-code/plain.txt", "claude-code/real/inner.txt", "claude-code/tpl.md"} <= rels)
        self.assertFalse(rels & {"claude-code/blob.bin", "claude-code/needs-gemini.md"})
        self.assertTrue(all(flag for _, flag in calls))
        self.assertEqual(read(os.path.join(rewritten, "plain.txt")), "{{ X }}\n{% IF Y %}\n")
        self.assertEqual(read(os.path.join(rewritten, "tpl.md")), "HI TESTER \n")  # rewrite ran after rendering
        default = render_tree(self.src, os.path.join(self.root, "dflt"), ctx(), "shared")  # core.rewrite
        self.assertEqual(sorted(default.rendered), ["shared/link-tpl.md", "shared/tpl.md", "shared/tpl2.md"])
        for name, module in (("import failure", None), ("no rewrite function", types.ModuleType("rw"))):
            with self.subTest(name), mock.patch.dict(sys.modules, {"installer.core.rewrite": module}):
                with self.assertRaises(RenderError) as caught:
                    render_tree(self.src, self.dst, ctx(), "shared")
            self.assertIn("rewrite", str(caught.exception))
            self.assertFalse(os.path.lexists(self.dst))


if __name__ == "__main__":
    unittest.main()
