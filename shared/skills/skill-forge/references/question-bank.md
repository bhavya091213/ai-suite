# Question bank for Phase 1

Two rules apply to every group below:

- **Ask only what the answer would change.** Before asking, name the two skills the answers
  would produce. If they are the same skill, do not ask; write the assumption into the spec.
- **Stop grilling when a second pass finds nothing ambiguous.** Reread the draft spec as the
  agent executing it cold; each guess becomes a question in the next round. No new questions
  means the grill is over.

Batch the questions of one group into a single message. Use the host's structured question tool
for bounded choices, plain prose for open ones. Record every answer in the spec, including the
ones that were "no" or "does not matter".

## Trigger

- [ ] What are the exact phrases the user would type? Collect three or more, in their words.
- [ ] Which nearby requests must **not** trigger it? (The negative prompt for Phase 3 comes
      from here.)
- [ ] Should the tool invoke it on its own when the description matches, or only when named?
      (This sets `allow_implicit_invocation` in `agents/openai.yaml`.)
- [ ] Is there a file type, directory, command or error message that signals the skill applies?
- [ ] Does it start a workflow (phases, gates) or answer a one-shot question?

## Inputs

- [ ] What must the user supply, and what can the skill find on its own (files, env, git)?
- [ ] Which inputs are optional, and what is the default when they are absent?
- [ ] Where do credentials come from? (Environment or keychain only. If the answer is "a file in
      the repo", the answer is wrong; say so.)
- [ ] Which existing files does it read? Which must exist before it can start?
- [ ] Any input that costs money, sends a message or changes an account? Those get a gate.

## Outputs

- [ ] What does the skill produce: files, a chat answer, a commit, a running process?
- [ ] Exact shape: paths, file names, format, sections, a table with which columns?
- [ ] What does the handback to the user look like? (Template it in SKILL.md.)
- [ ] Does it overwrite anything? If yes, how does it avoid losing the previous version
      (`mv` to a backup, never delete)?
- [ ] Is the output consumed by another skill, agent or script? Then its shape is a contract and
      must be written down.

## Success

- [ ] How does the user know it worked, in one sentence they could check themselves?
- [ ] What should the skill verify before claiming success (a test run, a file size, a diff, a
      rendered page)?
- [ ] Which decisions stay with the user (gates), and which does the skill own?
- [ ] Is "done" a state (zero instances running, all tests green) or a deliverable (a report)?
- [ ] Which steps have side effects (write outside the project, send, spend, start an instance,
      change an account)? Phase 3 dry-runs the skill and stops before them, so say what a faithful
      stub of each reports. Record them on the spec's `Side effects to stub in tests` line.

## Failure

- [ ] What happens when a required input is missing: ask, assume, or stop?
- [ ] What happens when a tool, server or command is unavailable: fall back, or stop and say so?
- [ ] Which failure is expensive or irreversible, and how is it prevented rather than handled?
- [ ] What must the skill never do? (Delete, push, spend, send, store a secret.)
- [ ] After a context compaction, where does the skill re-read its state from?

## Overlap

- [ ] Which installed skills matched the Phase 0 scan, and for each: extend, reference or ignore?
- [ ] Does a catalog skill (`npx skills find`) cover it? If one with real adoption exists, why
      write a new one instead of installing it?
- [ ] Does the new skill call other skills by name? Then name them in SKILL.md and say what it
      does when they are not installed.
- [ ] Is this a skill, or a command, agent or rule? A one-line "always do X" is a rule; a role
      with a persona is an agent; a slash-invoked action with arguments is a command.

## Tool specifics

- [ ] Claude Code, Codex or both? If both, can the body stay identical? Anything tool-specific
      (hooks, `/compact`, session files, memory snapshots, `AskUserQuestion`, Codex roles) forces
      a decision: name both mechanisms in one body, or split into a variant pair. Never a
      single-tool skill: if only one tool has the mechanism, the other still gets a variant.
- [ ] Does it need a script? Only if a step is deterministic; then which language, which runtime
      the user has, and what the script prints before acting.
- [ ] Does it spawn subagents? Which role or agent, which model tier, what budget?
- [ ] Does it need an MCP server? Which one, and what happens without it?
- [ ] Should it be installed globally or per project?
