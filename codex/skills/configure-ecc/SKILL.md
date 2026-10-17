---
name: configure-ecc
description: Install, repair, or verify the migrated ECC/Claude workflows as Codex-native skills, prompt recipes, rules, scripts, and agent templates under ~/.codex or a project .codex directory.
origin: ECC migrated to Codex
---

# Configure Codex Toolkit

Use this skill when the user asks to configure ECC, install Claude workflows into Codex, repair migrated skills, or set up a project-level Codex toolkit.

## Targets

- User-level Codex home: `~/.codex`
- Project-level Codex directory: `.codex` in the current repository

Never write to `~/.claude` or project `.claude` during Codex setup. Treat Claude files as read-only source material.

## Source Priority

1. Existing Codex material in `~/.codex/skills`, `~/.codex/prompts`, `~/.codex/scripts`, and `~/.codex/agents`
2. Local Claude source material in `~/.claude/.agents/skills`, `~/.claude/skills`, `~/.claude/commands`, `~/.claude/agents`, and `~/.claude/rules`
3. Upstream ECC source, only if local source is missing:

```bash
rm -rf /tmp/everything-claude-code
git clone https://github.com/affaan-m/everything-claude-code.git /tmp/everything-claude-code
```

When using upstream ECC, convert paths and wording before installing into Codex.

## Installation Workflow

1. Decide target.
   - For global installation, use `~/.codex`.
   - For project-only installation, use `.codex` in the current repository.
   - If unclear, ask the user directly.

2. Create target structure.

```bash
mkdir -p <target>/skills <target>/prompts/codex-commands <target>/prompts/codex-agents <target>/prompts/codex-rules <target>/scripts <target>/agents <target>/memory
```

3. Install skills.
   - Copy full skill directories, not just `SKILL.md`.
   - Preserve `scripts/`, `references/`, `assets/`, `agents/openai.yaml`, and config files.
   - Do not overwrite an existing skill without creating a backup under `<target>/backups/`.
   - Ensure `SKILL.md` frontmatter has a clear Codex-oriented `name` and `description`.

4. Install prompt recipes.
   - Claude slash-command markdown becomes Codex prompt recipes under `prompts/codex-commands/`.
   - Claude agent markdown becomes prompt references under `prompts/codex-agents/`.
   - Claude rules become reusable guidance under `prompts/codex-rules/`.
   - Remove Claude-only frontmatter such as `allowed-tools`, `disable-model-invocation`, and `context`.
   - Replace command examples with `~/.codex/scripts/codex-prompt <recipe> [args...]` when possible.

5. Install scripts.
   - Codex command wrappers should live in `<target>/scripts`.
   - Prefer wrappers around native Codex commands:
     - `codex exec`
     - `codex review`
     - `codex resume`
     - `codex fork`
   - Hook-style automation should become explicit workflow scripts or git hooks; do not assume Codex supports Claude lifecycle hooks.

6. Install agent roles.
   - Codex-native roles are TOML files in `<target>/agents`.
   - Keep read-only roles separate from writer roles.
   - Use `gpt-5.5` unless the user requests a different model.

## Required Codex Rewrites

| Claude/ECC item | Codex rewrite |
|---|---|
| `CLAUDE.md` | `AGENTS.md` |
| `~/.claude` | `~/.codex` |
| `.claude/` | `.codex/` |
| Slash commands | Prompt recipes plus `codex-prompt` wrapper |
| `claude -p` | `codex exec` |
| `Read`, `Grep`, `Glob` | `sed`/file read, `rg`, `rg --files` |
| `Edit`, `Write` | `apply_patch` or explicit scripts |
| `TodoWrite` | `update_plan` |
| Claude hooks | Explicit workflow scripts, companion wrappers, or git hooks |

## Verification

After installation or repair, run:

```bash
codex mcp list
codex debug prompt-input "skill smoke test" >/tmp/codex-skill-smoke.txt
~/.codex/scripts/codex-setup --json
```

Confirm that:
- migrated skills appear in `codex debug prompt-input`
- `~/.codex/config.toml` parses
- wrapper scripts are executable
- prompt recipes no longer require Claude slash-command tooling
- no credentials were added to config files
