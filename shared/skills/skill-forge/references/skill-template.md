# Skill template for Phase 2

Copy the skeleton, fill every section from the approved spec, and move anything that pushes
`SKILL.md` past 250 lines into `references/`. Replace the angle-bracket guidance with real
content as you go; none of it should survive into the finished file.

## Directory

```
<name>/
  SKILL.md                 required
  references/*.md          optional: checklists, snippets, gotchas the steps point at
  scripts/*                optional: deterministic steps as code
  agents/openai.yaml       Codex display metadata; include for shared skills and the Codex variant
```

## SKILL.md skeleton

```markdown
---
name: <name>                       # kebab-case, identical to the directory name
description: <One sentence saying what the skill does AND when to use it. Put the trigger
  phrases from the spec in verbatim: 'Use when the user says "...", "...", or asks to ...'.
  Both tools match on this line; nothing else in the file is read before the match.>
origin: local                      # local | ECC | community | <upstream repo> when adapted
---

# <Title>

<One paragraph: what the skill produces, who owns which decisions, the rules that never bend
(money, secrets, deletion). Name the files beside this one and what each is for.>

## When to use

- <trigger phrase or situation>
- <trigger phrase or situation>
- Not for: <the nearby request that must not trigger it; say which skill covers it instead>

## Inputs

| Input | Required | Source | Default |
| --- | --- | --- | --- |
| <name> | yes / no | user / file / env / git | <value or "ask"> |

## Steps

<Numbered, imperative, one action each. Name every gate explicitly:
"Gate: the user approves X before Y." A phased skill uses a phases table first, then one
section per phase, each ending with what to summarise to the user.>

1. ...
2. ...

## Output contract

<Exactly what exists when the skill is done: paths, file names, sections, a results table with
named columns, a running process and how to stop it. If another skill or script consumes the
output, this section is the interface.>

## Failure handling

| Situation | Behaviour |
| --- | --- |
| Required input missing | ask / assume <default> / stop |
| <tool or server> unavailable | fall back to <...> / stop and say so |
| <expensive or irreversible step> | gate on the user; never automatic |
| Context compacted mid-run | re-read <run-state file> instead of re-deriving |

## Examples

<Two or three request-to-result pairs in the user's wording: the prompt, what the skill asks
back (if anything), what it produces. These become the Phase 3 sample prompts.>
```

## references/

- One file per concern (`gotchas.md`, `snippets.md`, `conventions.md`), each a checklist or a
  list of commands with a one-line reason, not prose.
- Every reference file is pointed at from a specific step in `SKILL.md`; an orphan reference is
  dead weight.
- Keep commands copy-pasteable; put the variable parts in `<angle brackets>`.

## scripts/

- Only for steps that are deterministic enough to be code (API calls, file transfers, format
  conversion). Judgement stays in `SKILL.md`.
- Read credentials from the environment or the keychain; never from a tracked file or an
  argument that shows up in shell history.
- Print what the script is about to do, then do it. Exit non-zero with a one-line reason.
- Never delete: relocate with `mv` to a backup path and print the new location.
- State the runtime the user needs (`python3 >= 3.9`, `node >= 22`) at the top of the file.

## agents/openai.yaml

Codex reads this file for the skill's display metadata in its skill listing (the name shown,
the one-line blurb, the colour, the prompt offered when a user picks it, and whether Codex may
invoke the skill on its own when the description matches). Claude Code ignores it. Shared skills
and the Codex variant of a pair include it; the Claude variant does not need it.

```yaml
interface:
  display_name: "<Title Case name>"
  short_description: "<under 100 characters, what it does>"
  brand_color: "#<hex>"
  default_prompt: "<the prompt a user would send to start the skill>"
policy:
  allow_implicit_invocation: true   # false when the skill must only run when named
```
