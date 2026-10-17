"""installer.core.workflows: JSON, validation, rendering, staging and saving for real."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest
from typing import Tuple

from installer.core import actions, skills, status, workflows
from installer.core.frontmatter import parse_frontmatter
from installer.core.paths import Paths
from installer.core.types import ConsumerLink, LinkState, Operation
from installer.core.workflows import Phase, WorkflowDef
from installer.tests import fixtures

KNOWN = frozenset({"alpha", "beta", "gamma"})
APPLY_KINDS = {"mkdir", "copytree", "symlink", "backup", "unlink-to-backup"}


def _wf(**changes) -> WorkflowDef:
    base = WorkflowDef(
        name="demo-flow",
        description="Demo workflow for tests.",
        triggers=("run the demo", "demo flow"),
        phases=(
            Phase("Plan", "Decide what to do.", ("alpha",), ("Read the brief.", "Write the plan."),
                  ("plan.md",), gate=True, gate_text="the user signs off the plan"),
            Phase("Do", "Do the thing.", ("beta", "gamma"), (), ("result.txt", "notes.md")),
            Phase("Check", "Check the thing.", (), ("Run the checks.",), (), gate=True),
        ),
        version=3,
    )
    return dataclasses.replace(base, **changes)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _missing_links(paths: Paths, name: str) -> Tuple[ConsumerLink, ...]:
    return tuple(
        ConsumerLink(consumer, os.path.join(paths.consumer_dir(consumer), name),
                     LinkState.MISSING, None, paths.expected_link_target(consumer, name))
        for consumer in ("claude", "codex"))


def _shared_links(paths: Paths, name: str) -> Tuple[ConsumerLink, ...]:
    catalog, issues = skills.scan_catalog(paths)
    rows = status.compute(catalog, skills.scan_installed(paths), paths, repo_issues=issues)
    return next((row.links for row in rows if row.key == ("shared", name)), ())  # () = new skill


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        self.reset("start")

    def reset(self, tag: str) -> None:
        """Point root, stage and backup at a fresh sub-directory so one test can run several scenarios."""
        self.root = os.path.join(self.base, tag)
        self.stage_dir = os.path.join(self.root, "stage")
        self.backup = os.path.join(self.root, "backup")

    def built(self) -> Paths:
        return fixtures.build(self.root)

    def save(self, wf: WorkflowDef, paths: Paths, links=None) -> Tuple[Operation, ...]:
        links = _shared_links(paths, wf.name) if links is None else links
        ops = workflows.plan_save(wf, paths, self.backup, self.stage_dir, links)
        results = actions.apply(ops)
        self.assertTrue(all(r.ok for r in results), [r.message for r in results if not r.ok])
        return ops


class DefinitionTests(unittest.TestCase):
    def test_json_round_trip_shapes_and_validation(self) -> None:
        # json round trip
        wf = _wf(handback="Report in two lines.")
        text = workflows.to_json(wf)
        self.assertEqual(workflows.from_json(text), wf)
        self.assertTrue(text.endswith("}\n"))
        self.assertTrue(text.startswith('{\n  "name": "demo-flow",\n  "description"'))
        self.assertEqual(text, workflows.to_json(workflows.from_json(text)))
        data = json.loads(text)
        self.assertEqual(list(data), ["name", "description", "triggers", "phases", "handback", "version"])
        self.assertEqual(list(data["phases"][0]),
                         ["name", "goal", "skills", "steps", "outputs", "gate", "gate_text"])
        # defaults and nulls
        wf = workflows.from_json('{"name": "x", "phases": [{"name": "P"}], "extra": 1}')
        self.assertEqual(wf, WorkflowDef("x", "", (), (Phase("P", "", ()),), "", 1))
        wf = workflows.from_json('{"name": "x", "description": null, "triggers": null, '
                                 '"phases": null, "version": null}')
        self.assertEqual(wf, WorkflowDef("x", "", (), (), "", 1))
        # bad shapes
        for text in ("[]", "null", "{not json", "", '{"name": "x", "phases": {"name": "A"}}',
                     '{"name": "x", "phases": ["A"]}', '{"name": "x", "triggers": ["ok", 3]}',
                     '{"name": "x", "phases": [{"name": "A", "gate": "yes"}]}', '{"name": "x", "version": true}',
                     '{"name": "x", "version": "2"}', '{"name": "x", "handback": []}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                workflows.from_json(text)
        for text, pattern in (('{"description": "d", "phases": []}', "name"), ('{"name": 7}', "name"),
                              ('{"name": "x", "phases": [{"name": "A"}, {"goal": "g"}]}', r"phase 2.*name"),
                              ('{"name": "x", "phases": [{"name": "A", "skills": "alpha"}]}', "skills")):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, pattern):
                workflows.from_json(text)
        # validation errors
        self.assertEqual(workflows.validate(_wf(), KNOWN), ())
        dup = (Phase("Plan", "", ("alpha",)), Phase(" plan ", "", ("beta",)))
        cases = [("invalid workflow name", _wf(name=name)) for name in ("", "a/b", "..", ".hidden", " padded ")]
        cases += [("description is empty", _wf(description="  ")),
                  ("workflow has no phases", _wf(phases=())),
                  ("phase 1 has no name", _wf(phases=(Phase("", "g", ("alpha",)),))),
                  ("duplicate phase name", _wf(phases=dup)),
                  ("neither skills nor steps", _wf(phases=(Phase("Bare", "g", ()),))),
                  ("neither skills nor steps", _wf(phases=(Phase("Bare", "g", (), ("  ",)),))),
                  ("invalid skill name", _wf(phases=(Phase("A", "g", ("a/b",)),)))]
        for fragment, wf in cases:
            with self.subTest(fragment=fragment, name=wf.name, phases=wf.phases):
                hits = [e for e in workflows.validate(wf, KNOWN) if fragment in e]
                self.assertTrue(hits)
                self.assertFalse(any(e.startswith(workflows.WARNING_PREFIX) for e in hits), hits)
        self.assertEqual(sum("duplicate phase name" in e for e in workflows.validate(_wf(phases=dup), KNOWN)), 1)
        for phase in (Phase("Steps", "g", (), ("Do it.",)), Phase("Skill", "g", ("alpha",))):
            self.assertEqual(workflows.validate(_wf(phases=(phase,)), KNOWN), ())
        # validation warnings
        phases = (Phase("A", "g", ("ghost", "alpha")), Phase("B", "g", ("ghost", "ghost")))
        messages = workflows.validate(_wf(phases=phases), KNOWN)
        self.assertEqual(len(messages), 1)
        self.assertTrue(messages[0].startswith("warning: "), messages)
        self.assertIn("'ghost'", messages[0])
        self.assertIn("phase 1, 2", messages[0])
        wf = _wf(description="", phases=(Phase("A", "g", ("ghost",)),))  # errors sort first
        flags = [m.startswith("warning: ") for m in workflows.validate(wf, KNOWN)]
        self.assertEqual(flags, [False, True])


class RenderTests(unittest.TestCase):
    def test_render_skill_md_and_openai_yaml(self) -> None:
        # frontmatter and marker
        text = workflows.render_skill_md(_wf())
        self.assertEqual(text, workflows.render_skill_md(_wf()))
        self.assertTrue(text.startswith("---\nname: demo-flow\ndescription: "))
        meta = parse_frontmatter(text)
        self.assertEqual(meta.name, "demo-flow")
        self.assertEqual(meta.description,
                         "Demo workflow for tests. Use when the user says: run the demo, demo flow")
        self.assertTrue(meta.valid)
        self.assertEqual(parse_frontmatter(workflows.render_skill_md(_wf(triggers=()))).description,
                         "Demo workflow for tests.")
        desc = 'Line one:\n  has "quotes", a back\\slash and a # hash.'  # stays one line and round-trips
        meta = parse_frontmatter(workflows.render_skill_md(_wf(description=desc, triggers=("a: b",))))
        self.assertEqual(meta.description, 'Line one: has "quotes", a back\\slash and a # hash. '
                                           'Use when the user says: a: b')
        lines = text.splitlines()
        self.assertEqual(lines.count(workflows.MARKER), 1)
        self.assertEqual(lines[lines.index("---", 1) + 1], workflows.MARKER)
        # phase sections and gates
        text = workflows.render_skill_md(_wf())
        headings = [line for line in text.splitlines() if line.startswith("## Phase ")]
        self.assertEqual(headings, ["## Phase 1 - Plan", "## Phase 2 - Do", "## Phase 3 - Check"])
        self.assertLess(text.index("## Phase 3"), text.index("## Handback"))
        self.assertIn("**Goal:** Decide what to do.", text)
        self.assertIn("Load: `alpha` (read each skill's SKILL.md before acting).", text)
        self.assertIn("Load: `beta`, `gamma` (read each skill's SKILL.md before acting).", text)
        self.assertIn("1. Read the brief.\n2. Write the plan.", text)
        self.assertIn("**Outputs:**\n\n- plan.md", text)
        self.assertIn("- result.txt\n- notes.md", text)
        check = text[text.index("## Phase 3"):text.index("## Handback")]  # no skills or outputs
        self.assertNotIn("Load:", check)
        self.assertNotIn("**Outputs:**", check)
        self.assertIn("1. Run the checks.", check)
        self.assertEqual(text.count("**Gate:**"), 2)  # gate lines only for gated phases
        self.assertIn("**Gate:** the user signs off the plan.", text)
        self.assertIn("**Gate:** " + workflows.DEFAULT_GATE_TEXT + ".", text)
        self.assertNotIn("Gate", text[text.index("## Phase 2"):text.index("## Phase 3")])
        self.assertNotIn("gate", workflows.render_skill_md(_wf(phases=(Phase("A", "g", ("alpha",)),))))
        # skills table, handback, closing line
        text = workflows.render_skill_md(_wf(phases=(
            Phase("One", "", ("alpha", "beta")), Phase("Two", "", ("beta", "beta")))))
        self.assertIn("## Skills this workflow loads", text)
        self.assertIn("| `alpha` | Phase 1 - One |", text)
        self.assertIn("| `beta` | Phase 1 - One, Phase 2 - Two |", text)
        bare = workflows.render_skill_md(_wf(phases=(Phase("A", "g", (), ("Do it.",)),)))
        self.assertIn("None; every phase is described by its steps.", bare)
        self.assertNotIn("| Skill |", bare)
        text = workflows.render_skill_md(_wf())
        handback = text[text.index("## Handback"):]
        self.assertIn("- Phase 1 - Plan: plan.md", handback)
        self.assertIn("- Phase 2 - Do: result.txt, notes.md", handback)
        self.assertIn("- Phase 3 - Check: no recorded outputs", handback)
        self.assertTrue(text.endswith(workflows.CLOSING_LINE + "\n"))
        custom = workflows.render_skill_md(_wf(handback="  Tell me three things.\n"))
        self.assertIn("## Handback\n\nTell me three things.\n\n", custom)
        self.assertNotIn("no recorded outputs", custom)
        draft = workflows.render_skill_md(WorkflowDef("blank", "", (), ()))  # an empty draft still renders
        self.assertIn("This workflow has no phases yet.", draft)
        self.assertEqual(parse_frontmatter(draft).name, "blank")
        # openai.yaml shape
        text = workflows.render_openai_yaml(_wf())
        lines = text.splitlines()
        self.assertEqual([l.split(":")[0].strip() for l in lines],
                         ["interface", "display_name", "short_description", "brand_color",
                          "default_prompt", "policy", "allow_implicit_invocation"])
        self.assertEqual(lines[1], '  display_name: "Demo Flow"')
        real = os.path.join(Paths.detect().source_dir("shared"), "lambda-gpu-training",
                            "agents", "openai.yaml")
        if os.path.isfile(real):  # same keys as the house example
            self.assertEqual([l.split(":")[0] for l in lines],
                             [l.split(":")[0] for l in _read(real).splitlines()])
        self.assertIn("Run the demo-flow workflow one phase at a time: Plan, Do, Check", text)
        self.assertIn("approval at every gate", text)
        self.assertNotIn("gate", workflows.render_openai_yaml(_wf(phases=(Phase("A", "g", ("alpha",)),))))
        # openai.yaml short description
        text = workflows.render_openai_yaml(_wf(description='Say "hi". ' + "word " * 60))
        short = next(l for l in text.splitlines() if "short_description" in l)
        value = short.split(": ", 1)[1]
        self.assertTrue(value.endswith('..."'))
        self.assertLessEqual(len(value) - 2, workflows.SHORT_DESCRIPTION_MAX)
        self.assertIn('\\"hi\\"', value)


class SaveTests(TempCase):
    def test_stage_plan_and_save_back_up_before_replacing_and_never_delete(self) -> None:
        # stage writes the three files
        self.reset("stage")
        wf = _wf()
        staged = workflows.stage(wf, self.stage_dir)
        self.assertEqual(staged, os.path.join(self.stage_dir, "demo-flow"))
        self.assertEqual(skills.list_files(staged),
                         ("SKILL.md", "agents/openai.yaml", "workflow.json"))
        self.assertEqual(_read(os.path.join(staged, "SKILL.md")), workflows.render_skill_md(wf))
        self.assertEqual(_read(os.path.join(staged, "workflow.json")), workflows.to_json(wf))
        self.assertEqual(_read(os.path.join(staged, "agents", "openai.yaml")),
                         workflows.render_openai_yaml(wf))
        staged = workflows.stage(_wf(description="Changed."), self.stage_dir)  # restage
        self.assertIn("Changed.", _read(os.path.join(staged, "SKILL.md")))
        self.assertEqual(workflows.load_def(staged).description, "Changed.")
        # stage refuses escaping names
        self.reset("stage-names")
        for name in ("../evil", "a/b", "", ".", ".."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                workflows.stage(_wf(name=name), self.stage_dir)
        self.assertFalse(os.path.exists(self.stage_dir))
        with self.assertRaises(ValueError):  # plan_save stages first, so it refuses too
            workflows.plan_save(_wf(name="a/b"), self.built(), self.backup, self.stage_dir)
        # plan: new workflow
        self.reset("plan-new")
        paths = self.built()
        ops = workflows.plan_save(_wf(), paths, self.backup, self.stage_dir,
                                  _missing_links(paths, "demo-flow"))
        self.assertEqual([o.kind for o in ops], ["copytree", "symlink", "symlink"])
        self.assertLessEqual({o.kind for o in ops}, APPLY_KINDS)
        copy, claude, codex = ops
        self.assertEqual(copy.src, os.path.join(self.stage_dir, "demo-flow"))
        self.assertEqual(copy.dst, os.path.join(paths.install_dir("shared"), "demo-flow"))
        for op, consumer in ((claude, "claude"), (codex, "codex")):
            self.assertEqual(op.dst, os.path.join(paths.consumer_dir(consumer), "demo-flow"))
            self.assertEqual(op.src, paths.expected_link_target(consumer, "demo-flow"))
        # plan: existing workflow is backed up first
        self.reset("plan-existing")
        paths = self.built()
        self.save(_wf(), paths, _missing_links(paths, "demo-flow"))
        ops = workflows.plan_save(_wf(description="v2"), paths, self.backup, self.stage_dir,
                                  _shared_links(paths, "demo-flow"))
        self.assertEqual([o.kind for o in ops], ["backup", "copytree"])
        self.assertEqual(ops[0].src, os.path.join(paths.install_dir("shared"), "demo-flow"))
        self.assertEqual(ops[0].dst, os.path.join(self.backup, "shared", "demo-flow"))
        # plan: only missing links
        self.reset("plan-links")
        paths = self.built()
        mixed = (dataclasses.replace(_missing_links(paths, "x")[0], state=LinkState.REAL_DIR),
                 _missing_links(paths, "x")[1])
        ops = workflows.plan_save(_wf(), paths, self.backup, self.stage_dir, mixed)
        self.assertEqual([o.kind for o in ops], ["copytree", "symlink"])
        self.assertTrue(ops[1].dst.startswith(paths.consumer_dir("codex")))
        for state in (LinkState.OK, LinkState.WRONG_TARGET, LinkState.BROKEN,
                      LinkState.REAL_DIR, LinkState.FILE):
            links = tuple(dataclasses.replace(l, state=state) for l in _missing_links(paths, "x"))
            kinds = [o.kind for o in workflows.plan_save(_wf(), paths, self.backup,
                                                         self.stage_dir, links)]
            self.assertEqual(kinds, ["copytree"], state)
        os.symlink("elsewhere", os.path.join(paths.consumer_dir("claude"), "demo-flow"))  # no links: scan the disk
        ops = workflows.plan_save(_wf(), paths, self.backup, self.stage_dir)
        self.assertEqual([o.kind for o in ops], ["copytree", "symlink"])
        self.assertTrue(ops[1].dst.startswith(paths.consumer_dir("codex")))
        # plan: missing directories
        self.reset("plan-mkdir")
        paths = fixtures.paths_for(self.root)
        ops = workflows.plan_save(_wf(), paths, self.backup, self.stage_dir)
        self.assertEqual([o.kind for o in ops],
                         ["mkdir", "copytree", "mkdir", "symlink", "mkdir", "symlink"])
        self.assertEqual(ops[0].dst, paths.install_dir("shared"))
        self.assertEqual(ops[2].dst, paths.consumer_dir("claude"))
        self.assertTrue(all(r.ok for r in actions.apply(ops)))
        self.assertTrue(os.path.islink(os.path.join(paths.consumer_dir("codex"), "demo-flow")))
        # plan: symlinked copy moves as a link
        self.reset("plan-symlink")
        paths = self.built()
        real = os.path.join(self.root, "elsewhere", "demo-flow")
        fixtures.make_skill(os.path.dirname(real), "demo-flow")
        os.symlink(real, os.path.join(paths.install_dir("shared"), "demo-flow"))
        ops = workflows.plan_save(_wf(), paths, self.backup, self.stage_dir, ())
        self.assertEqual(ops[0].kind, "unlink-to-backup")
        self.assertTrue(all(r.ok for r in actions.apply(ops)))
        self.assertTrue(os.path.isdir(real))  # the link's target is untouched
        # save for real
        self.reset("save-new")
        paths = self.built()
        before = skills.scan_installed(paths)
        self.save(_wf(), paths, _missing_links(paths, "demo-flow"))
        dest = os.path.join(paths.install_dir("shared"), "demo-flow")
        self.assertEqual(skills.list_files(dest),
                         ("SKILL.md", "agents/openai.yaml", "workflow.json"))
        for consumer in ("claude", "codex"):
            link = os.path.join(paths.consumer_dir(consumer), "demo-flow")
            self.assertTrue(os.path.islink(link), consumer)
            self.assertEqual(os.readlink(link), paths.expected_link_target(consumer, "demo-flow"))
            self.assertEqual(os.path.realpath(link), os.path.realpath(dest))
        self.assertEqual(_read(os.path.join(dest, "SKILL.md")), workflows.render_skill_md(_wf()))
        self.assertEqual([l.state for l in _shared_links(paths, "demo-flow")],
                         [LinkState.OK, LinkState.OK])
        after = skills.scan_installed(paths)
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(set(after) - set(before),
                         {("shared", "demo-flow"), ("claude", "demo-flow"), ("codex", "demo-flow")})
        # save again backs up
        self.reset("save-again")
        paths = self.built()
        self.save(_wf(), paths)
        dest = os.path.join(paths.install_dir("shared"), "demo-flow")
        old = _read(os.path.join(dest, "SKILL.md"))
        ops = self.save(_wf(description="A much better demo."), paths)
        self.assertEqual(ops[0].kind, "backup")
        kept = os.path.join(self.backup, "shared", "demo-flow")
        self.assertEqual(_read(os.path.join(kept, "SKILL.md")), old)
        self.assertEqual(workflows.load_def(kept).description, "Demo workflow for tests.")
        new = _read(os.path.join(dest, "SKILL.md"))
        self.assertNotEqual(new, old)
        self.assertIn("A much better demo.", new)
        self.assertEqual(workflows.load_def(dest).description, "A much better demo.")
        self.assertTrue(os.path.islink(os.path.join(paths.consumer_dir("claude"), "demo-flow")))


class LoadAndExampleTests(TempCase):
    def test_load_list_known_names_and_example(self) -> None:
        # load_def and list_workflows
        self.reset("list")
        paths = self.built()
        alpha = os.path.join(paths.install_dir("shared"), "alpha")
        self.assertIsNone(workflows.load_def(alpha))
        self.assertIsNone(workflows.load_def(os.path.join(self.root, "nowhere")))
        for broken in ("{broken", '{"phases": []}'):
            fixtures.write(os.path.join(alpha, "workflow.json"), broken)
            self.assertIsNone(workflows.load_def(alpha))
        self.assertEqual(workflows.list_workflows(paths), ())  # alpha's broken workflow.json is skipped
        nohome = fixtures.paths_for(self.root, home=self.stage_dir)
        self.assertEqual(workflows.list_workflows(nohome), ())
        self.save(_wf(name="zeta-flow"), paths)
        self.save(_wf(name="alpha-flow"), paths)
        shared = paths.install_dir("shared")
        fixtures.write(os.path.join(shared, "beta", "workflow.json"), "{broken")
        fixtures.write(os.path.join(shared, ".hidden", "workflow.json"), workflows.to_json(_wf()))
        fixtures.write(os.path.join(shared, "learned", "workflow.json"), workflows.to_json(_wf()))
        listing = workflows.list_workflows(paths)
        self.assertEqual([wf.name for _dir, wf in listing], ["alpha-flow", "zeta-flow"])
        self.assertEqual([d for d, _wf in listing],
                         [os.path.join(shared, "alpha-flow"), os.path.join(shared, "zeta-flow")])
        self.assertEqual(listing[0][1], _wf(name="alpha-flow"))
        # known skill names
        self.reset("known")
        names = workflows.known_skill_names(self.built())
        self.assertLessEqual({"alpha", "beta", "dup", "gamma", "foreign1"}, names)
        self.assertFalse(names & {"synced", "learned", ".system", "ghost", "stray.txt", "pdf"})
        # example() against the real repo catalog
        self.paths = Paths.detect()
        catalog, _issues = skills.scan_catalog(self.paths)
        self.catalog_names = frozenset(name for (_scope, name) in catalog)
        wf = workflows.example()
        self.assertEqual([p.name for p in wf.phases], ["Research", "Design", "Build"])
        self.assertEqual([p.gate for p in wf.phases], [True, True, False])
        self.assertTrue(wf.triggers)
        self.assertEqual(workflows.from_json(workflows.to_json(wf)), wf)
        meta = parse_frontmatter(workflows.render_skill_md(wf))
        self.assertEqual((meta.name, meta.valid), (wf.name, True))
        if not self.catalog_names:
            self.skipTest("no catalog in this checkout")
        self.assertEqual(workflows.validate(workflows.example(), self.catalog_names), ())
        shared = {name for (scope, name) in skills.scan_catalog(self.paths)[0] if scope == "shared"}
        used = {s for phase in workflows.example().phases for s in phase.skills}
        self.assertTrue(used)
        self.assertLessEqual(used, shared)


if __name__ == "__main__":
    unittest.main()
