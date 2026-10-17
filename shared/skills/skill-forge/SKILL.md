---
name: skill-forge
description: Phased, gated workflow that turns a task or a repeatable workflow into a well-formed agent skill (SKILL.md plus optional references, scripts and Codex metadata), tested against sample prompts and placed in the right tree of this repo; use when the user says "make a skill", "write a skill", "turn this workflow into a skill", "skill for X", or wants something they keep doing packaged as a reusable skill.
origin: local
---

# Skill forge

A skill is a contract: a trigger, inputs, steps, an output and a promise about what happens when
things go wrong. Most bad skills fail at the spec, not the prose: they trigger on everything or
nothing, duplicate a skill that already exists, or leave the agent to guess what "done" looks
like. So this workflow spends its effort before the first file is written: investigate what
exists, grill the user until the spec is unambiguous, gate on their approval, and only then
draft, test, place and publish. It reads the same in Claude Code and Codex; where a host tool
matters, both are named.

Helpers beside this file: `references/question-bank.md` (what to ask in Phase 1),
`references/skill-template.md` (the skeleton filled in Phase 2) and
`references/placement-and-publishing.md` (where the result goes and how it ships in Phase 4).

Three rules that never bend:

1. **No skill file before the gate.** No directory, no SKILL.md, no draft "to react to". Until
   the user approves the spec, the spec is the only artefact.
2. **Never delete.** Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv`
   instead. If something must be retired, `mv` it into a backup location (e.g.
   `~/.agents/backups/retired-<what>/`) and say so in the report.
3. **No personal paths, no secrets.** Write `~` or `$HOME`, never an expanded home directory.
   Credentials come from the environment, never from a tracked file or a command description.

## Phases

| Phase | Output | Gate |
| --- | --- | --- |
| 0 Intake | Restated task, host decision, overlap scan | none |
| 1 Grill | One-page spec | User approves the spec before any file is written |
| 2 Draft | Skill directory built from the template in the draft area (outside the repo tree) | none |
| 3 Test | Per-prompt dry-run results, frontmatter and path checks | User accepts the results |
| 4 Place and publish | Files in the right tree, README row, commit | User approves the commit; the install is a separate yes |

Keep a run note (spec, decisions, test results) in the host's scratch directory or in
`.skill-forge/<name>.md` in the project (add that directory to `.gitignore`). After a context
compaction, re-read it instead of re-deriving.

Draft area: Phase 2 builds the skill in the host's scratch directory at
`<scratch>/skill-forge/<name>/`, never inside the repo tree. A variant pair uses
`<scratch>/skill-forge/claude-code/<name>/` and `<scratch>/skill-forge/codex/<name>/`. With no
scratch directory, use `.skill-forge/draft/` in the project (ignored like the run note). Phase 3
tests and checks the draft where it is; Phase 4 is the only phase that moves anything into the
repo.

## Phase 0: intake

Restate the request in one paragraph, then settle four things from what the user already said:

- **Task**: what the skill does, one sentence, in the user's own words.
- **Operator**: who runs it (the user in chat, a subagent, a scheduled job) and how often.
- **Host**: Claude Code, Codex or both. A shared skill that works in both is the default. When
  the task needs a tool-specific mechanism (hooks, session files, memory snapshots, slash
  commands), build a matched pair of variants, one per tool. A skill never ships for one tool
  only: if the user names one tool but the body reads the same in both, make it shared; if the
  mechanism exists in only one tool, still build the pair (see
  `references/placement-and-publishing.md`).
- **Triggers**: the phrases a user would actually type. Collect their wording, not yours.

Then scan for overlap before asking a single question:

```bash
for d in ~/.agents/skills ~/.claude/skills ~/.codex/skills; do
  grep -il '<keyword>' "$d"/*/SKILL.md 2>/dev/null
done
npx skills find "<keyword>"      # the find-skills catalog; skip when offline
```

In a repo clone that is not installed yet, scan `shared/skills`, `claude-code/skills` and
`codex/skills` the same way. Read every near match in full. Report the restated task, the host
decision and the overlap list with a verdict per match: extend it, reference it, or unrelated.
If an existing skill already covers most of the request, say so and offer to extend it; a
duplicate is the most common way a skill collection rots. Extending means editing the
existing skill: copy its directory into the draft area with `cp -R`, edit the copy, and let
Phase 4 back the original up with `mv` before the new version goes in. Record the original in the
spec's `Replaces` line.

## Phase 1: grill

Work through `references/question-bank.md` group by group: trigger, inputs, outputs, success,
failure, overlap, tool specifics. Two rules govern the interrogation:

- **Ask only what the answer would change.** If every plausible answer leads to the same skill,
  do not ask; record the assumption in the spec instead.
- **Stop grilling when a second pass finds nothing ambiguous.** After each round, reread the
  draft spec as the agent that will execute it cold. Every place you would have to guess becomes
  a question in the next round. When a pass produces no new question, the grill is done. One
  round is rarely enough; four means the scope is too big and should be split.

Use the host's structured question tool for bounded choices (`AskUserQuestion` in Claude Code;
a numbered list in Codex) and plain questions otherwise. Batch related questions; never ask them
one at a time.

Write the one-page spec:

```
Name: <kebab-case>                 Scope: shared | pair (claude-code + codex)
Replaces: none | <existing skill directory this edits>
Trigger phrases: ...               Not triggered by: ...
Inputs: required / optional, and where each comes from
Steps: numbered, with any internal gates
Output contract: files or text produced, exact shape
Success: how the user knows it worked
Failure handling: what the skill does when an input is missing or a step fails
Side effects to stub in tests: writes outside the project, sends, spends, starts or changes
  anything, or "none"; for each, what a faithful dry run reports instead of doing it
Overlap: skills it extends, references or deliberately duplicates, and why
Tool specifics: hooks, slash commands, subagents, MCP servers, scripts
Assumptions made without asking: ...
Sample prompts for Phase 3: two or three, in the user's wording, plus one that must not trigger
```

**Gate: the user approves the one-page spec before any file is written.** Present it and stop.
Silence, a tangential reply or "looks interesting" is not approval; a change request means revise
and re-present. Only an explicit yes ("approved", "go", "build it") opens Phase 2.

## Phase 2: draft

Build the directory from `references/skill-template.md` in the draft area:

- `SKILL.md`: frontmatter `name` (equal to the directory name) and `description` (one sentence
  that includes the trigger conditions; both tools match on it, so the spec's trigger phrases go
  in verbatim), then When to use, Inputs, Steps, Output contract, Failure handling, Examples.
  Keep it under 250 lines; longer material moves to `references/`.
- `references/`: checklists, snippets, gotchas that a step points at. Practical, not essays.
- `scripts/`: only when a step is deterministic enough to be code. Scripts read credentials from
  the environment, print what they are about to do, and never delete.
- `agents/openai.yaml`: display metadata Codex reads for its skill listing (display name, short
  description, brand colour, default prompt, implicit-invocation policy). Claude Code ignores it.
  Include it for shared skills and for the Codex variant of a pair.

Write for the agent that reads it cold: imperative steps, named gates, a stated output. Keep the
user's trigger wording. Every claim about a tool, a path or a command must be one you verified in
this session; a skill that asserts a file exists when it does not is worse than no skill.

## Phase 3: test

1. Dry-run each approved sample prompt in a fresh context: a subagent (the `Agent` tool in
   Claude Code, a role from `codex/agents/*.toml` in Codex) or a new session of either tool.
   State the tier on the spawn (RULES.md sections B and C): light, which is Sonnet in Claude Code
   and low or medium reasoning effort in Codex. The brief holds these three things and nothing
   else from this conversation:
   - the prompt, and the path to the draft `SKILL.md` with the instruction to follow it;
   - the dry-run rule: do read-only steps for real, but stop before any step that writes outside
     a scratch directory, sends a message, spends money, starts a process or instance, or changes
     an account, and report the exact command or action it would have taken (the spec's
     `Side effects to stub in tests` line names them);
   - this rule, verbatim: **Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv` instead. If something must be retired, `mv` it into a backup location (e.g. `~/.agents/backups/retired-<what>/`) and say so in the report.**

   Record per prompt: would the description have triggered it, were the steps followed, does the
   result match the output contract, which side effects were stubbed, and where did the agent
   guess. For a variant pair, repeat the whole run for each variant.
2. Run the negative prompt the same way; the skill must not claim it.
3. A contract mismatch is a spec or draft bug, never a test bug: fix the skill, rerun that prompt.
4. Run the frontmatter and hygiene checks (the first line is the repo's verification snippet
   from `AGENTS.md`, narrowed to the new skill):

```bash
d=<scratch>/skill-forge/<name>   # the draft area; a variant pair: once per variant
f="$d/SKILL.md"
grep -q '^name:' "$f" && grep -q '^description:' "$f" || echo "MISSING FRONTMATTER: $f"
[ "$(sed -n 's/^name: *//p' "$f")" = "$(basename "$d")" ] || echo "NAME != DIRECTORY: $f"
grep -rnE '/(Users|home)/[^/ "]+' "$d" && echo "PERSONAL PATH in $d"
wc -l "$f"                                   # must stay under 250
```

5. Present the per-prompt table and the check output, then stop for the user's acceptance.
   Three rounds of fixes on the same prompt mean the description or the scope is wrong; say so
   rather than patching a fourth time.

## Phase 4: place and publish

Follow `references/placement-and-publishing.md`. Steps 1-4 prepare, step 5 is the commit gate and
step 6 is a separate install gate.

1. Pick the tree with its decision table. Shared is the default; a platform-specific variant
   earns its place only when the body genuinely differs per tool, and then both variants exist
   with the same `name`. There is no single-tool placement.
2. Move the draft into place with `mv`, after confirming the target is free:
   `[ ! -e <tree>/skills/<name> ] || echo "TARGET EXISTS"`. Never `mv` onto an existing
   directory: it nests the draft inside it. If the target exists (the extend case from Phase 0),
   first `mv` the old copy into `~/.agents/backups/retired-<name>/` as the placement reference
   shows, then move the draft, and name the backup path in the handback. Never copy a shared skill
   into a tool tree.
3. Add the README table row in the matching category and update the counts the README states.
   Add a `shared/skill-lock.json` entry when the skill was adapted from an upstream repo.
4. Run the repo checks: the frontmatter loop, the personal-path grep, `bash -n install.sh` and
   `./install.sh --dry-run --all` (a plan only, nothing is installed).
5. **Gate: the user approves the commit.** Show `git status --short` for this skill's paths (the
   skill, its README rows and counts, any lock entry) and the step 4 output, then stop. Only an
   explicit yes opens the commit. Stage those paths by name, never `git add -A`: the working tree
   may hold unrelated uncommitted work. Commit the skill and its README row together as
   `feat: add <name> skill`. Never push without being asked.
6. **Gate: the user approves the install, separately from the commit.** After the commit, offer
   it. `./install.sh --all` re-installs all of `shared/`, `claude-code/` and `codex/` from the
   working tree onto the live `~/.agents`, `~/.claude` and `~/.codex`, so it also installs
   unrelated uncommitted changes. Show the `--dry-run` plan and run it only on an explicit yes;
   the scoped alternative is `./install.sh skills install <name>` (see the placement reference).
   Without a yes, report `Installed: no` and the command to run later.

## Handback

```
# Skill: <name>
Scope: shared | pair (claude-code + codex)  Path: <repo path(s)>
Triggers: <phrases from the description>
Does: <two or three sentences>
Files: SKILL.md (<n> lines), references/<...>, scripts/<...>, agents/openai.yaml
Tests: <prompt> -> triggered / followed / contract met / stubbed: <...> / guesses: <...>
       <negative prompt> -> not triggered
Checks: frontmatter OK | personal paths none | install dry-run OK
Overlap: <skills it extends or references>
Published: commit <sha> on <branch>, not pushed | not committed (why)
Installed: yes (<command used>) | no (command to run later)
Moved or retired: <anything relocated with mv, incl. a backed-up original, and where it went>
Open follow-ups: <...>
```
