# claude-code/ - mirrors `~/.claude`

Everything in here installs into `~/.claude`. Tool-agnostic material (rules, skills, MCP servers)
lives in [`../shared`](../shared) instead and is symlinked or synced in.

## Contents

| Path | Installs to | What it is |
| --- | --- | --- |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | Global instructions; imports the shared rules and your local rules. Installed only when absent |
| `settings.example.json` | `~/.claude/settings.json` | Permissions, env, model, hooks, plugins. Installed only when absent |
| `agents/` | `~/.claude/agents/` | 32 subagent definitions (`name` + `description` frontmatter); models mapped to your configured tiers |
| `commands/` | `~/.claude/commands/` | 57 slash commands; `orchestrate.md` is a template and the Codex/Gemini-specific `multi-*` commands are left out when that tool is off |
| `rules/` | `~/.claude/rules/` | `common/` (9 files) plus cpp, golang, kotlin, perl, php, python, swift, typescript |
| `hooks/hooks.json` | merged into settings | 21 hook entries across 6 events |
| `scripts/hooks/` | `~/.claude/scripts/hooks/` | 25 hook implementations (format, typecheck, guards, session markers) |
| `scripts/codex-review-pipeline/` | `~/.claude/scripts/codex-review-pipeline/` | Codex-first adversarial review runner used by Phase 3 of `/orchestrate`. Installed only when Codex is on (a `.installer-requires` file) |
| `skills/` | `~/.claude/skills/` | 14 Claude variants of the platform-specific skills, plus an empty `learned/` landing directory |

The 89 shared skills are **not** here. They are symlinked from `~/.agents/skills` into
`~/.claude/skills` at install time, so both CLIs load the same file.

## How CLAUDE.md imports the shared rules

`CLAUDE.md` does not duplicate the rules. It contains two import lines:

```markdown
@~/.agents/RULES.md
@~/.agents/LOCAL.md
```

Claude Code resolves them at session start, so editing `~/.agents/LOCAL.md` takes effect on the
next session with no sync step. `~/.agents/RULES.md` is *rendered* from the repo's
`shared/RULES.md` template and your `~/.agents/config.json` each time you run `./install.sh`
(change shared policy in the repo, personal rules in `LOCAL.md`; edits to the installed
`RULES.md` are overwritten). Codex has no import mechanism, which is why `codex/AGENTS.md`
carries synced copies instead. `CLAUDE.md` also points at `~/.claude/rules/common/agents.md` and
`performance.md` for the longer-form agent and model routing guidance. Like `settings.json`,
`CLAUDE.md` is installed only when it does not exist, so your edits survive re-installs.

## Rendered files in this tree

Three kinds of change happen between this directory and `~/.claude`, all done by `./install.sh`
(details in [`../docs/installer.md`](../docs/installer.md#rendering)):

- **Template:** `commands/orchestrate.md` carries `installer:template`. With Codex off (or
  `review.adversarial = claude`) its Phase 3 is the Claude-only review path; the two approval gates
  follow `guardrails.plan_approval_gate` and `guardrails.fix_approval_gate`.
- **Requirement markers:** `agents/codex-review-runner.md`, `commands/multi-backend.md`,
  `multi-execute.md` and `multi-plan.md` need Codex; `multi-frontend.md` needs Gemini;
  `multi-workflow.md` needs either; `scripts/codex-review-pipeline/` needs Codex. They are not
  installed when the tool is off.
- **Rewrite rules:** `model: opus|sonnet|haiku` in `agents/*.md` becomes your configured heavy /
  light / trivial model.

## settings.example.json

Copy it to `~/.claude/settings.json` **only if that file does not already exist** - the installer
takes this approach because `settings.json` accumulates machine-local state (marketplace entries,
enabled plugins, local permissions) that must not be clobbered. If you already have one, diff the
example against it and merge the parts you want by hand.

Top-level keys: `env`, `permissions`, `model`, `hooks`, `enabledPlugins`,
`extraKnownMarketplaces`, `effortLevel`, `skipDangerousModePermissionPrompt`. The `hooks` block
mirrors `hooks/hooks.json`; keep the two consistent when you change either.

When the example is installed it is rendered first: `env.ECC_HOOK_PROFILE` and
`env.ECC_DISABLED_HOOKS` come from `guardrails.hook_profile` / `guardrails.disabled_hooks` in
`~/.agents/config.json`, and when Headroom or Codex is absent the matching `ANTHROPIC_BASE_URL`,
hooks, plugin and marketplace entries are dropped. The installer's Files tab (`d`) shows what the
rendered example would contain next to your live file.

## ECC plugin manifest gotcha

If you package any of this as a Claude Code plugin (the way the upstream Everything Claude Code
plugin does), the manifest is stricter than it looks:

- Every component field (`skills`, `commands`, `agents`, `hooks`) must be an **array**, even when
  it holds a single entry - a bare string is silently ignored.
- `agents` will not glob a directory; each agent needs an **explicit file path**.
- `version` is **required**; a manifest without it fails to load rather than defaulting.

A manifest that violates any of these tends to load "successfully" with components missing, so
verify with `/skill-doctor` or `claude plugin eval` rather than trusting a clean start.
