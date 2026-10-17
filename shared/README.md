# shared/ - the single source of truth

This directory mirrors `~/.agents`, which holds everything Claude Code and Codex CLI have in
common. Edit here, run the installer (and the sync script where it applies), and both tools pick
it up. Never hand-edit the rendered copies inside `~/.agents`, `~/.claude` or `~/.codex`.

## Layout

| Path | Installs to | What it holds |
| --- | --- | --- |
| `skills/` | `~/.agents/skills/` | 90 shared agent skills |
| `RULES.md` | `~/.agents/RULES.md` | Shared operating rules, loaded by both CLIs. A **template**: rendered from your config and the tools found on the machine at install time |
| `config.example.json` | `~/.agents/config.json` | Central config (tools, subagent tiers, review backend, guardrails, Obsidian vaults, editor). Installed **only when absent**; yours afterwards |
| `LOCAL.example.md` | `~/.agents/LOCAL.md` | Your personal rules. Installed **only when absent**; never overwritten |
| `extras.json` | nothing | External integrations the installer can detect and install (Impeccable, Figma MCP, ppt-master, presentation-skill, Anthropic's pptx skill); read from the repo |
| `mcp-servers.json` | `~/.agents/mcp-servers.json` | Shared MCP server definitions (9, one of them - `figma` - disabled by default) |
| `skill-lock.json` | `~/.agents/.skill-lock.json` | Pinned provenance for skills sourced from upstream repos |
| `bin/sync-agents` | `~/.agents/bin/sync-agents` | Renders rules, local rules and MCP config into both tools |

The installer that puts all of this in place lives in [`../installer`](../installer); see
[`../docs/installer.md`](../docs/installer.md).

After installation, `~/.agents/backups/` also appears: timestamped snapshots taken by
`install.sh` and by the sync tooling before any destructive-looking write. Nothing in this setup
deletes; it moves things there instead.

## Skills

Skills install as **symlinks** from `~/.agents/skills/<name>` into both `~/.claude/skills/<name>`
and `~/.codex/skills/<name>`. Because they are symlinks, adding or editing a skill is picked up by
both tools immediately, with no sync step.

Consequence for this repo: a skill that both tools can use lives **only** in `shared/skills/`. It
is never duplicated into `claude-code/skills/` or `codex/skills/` - those two directories are
reserved for the small set of skills whose body is genuinely tool-specific, and those ship as a
matched Claude/Codex pair.

Every `SKILL.md` needs `name` and `description` frontmatter; `name` must match the directory name.

Of the 90 shared skills, 23 are vendored from upstream repositories and keep their `LICENSE.txt`
in the skill folder, with provenance recorded in `skill-lock.json`: `frontend-design`
(anthropics/skills, Apache-2.0), `userflow` and the fifteen `flow-*` skills
(jpoindexter/ux-flow-skills, MIT), `information-architecture` (rampstackco/claude-skills, MIT),
`slide-deck`, `minto-pyramid`, `bluf` and `exec-summary` (patrick204nqh/skills, MIT) and
`executive-communication` (refoundai/lenny-skills, MIT). Three workflow skills are authored here:
`skill-forge`, `product-design-workflow` and `presentation-workflow`. Tools that are not skills
(or are too large or restrictively licensed to redistribute) are listed in `extras.json` instead.

## Rules

`RULES.md` is the contract. Sections A–E: session pre-flight, orchestrator pattern, model/effort
routing, the subagent context budget (100k tokens by default), and the never-delete policy.
Section F, **Environment & defaults (generated)**, lists the tools and versions found on the
machine, the review backend, Obsidian vaults, sessions and backups directories, and the hook
profile; it is produced at install time, never written by hand.

`RULES.md` here is a **template** (it carries an `installer:template` marker and `{{ }}` /
`{% %}` tags). The installer renders it from `~/.agents/config.json` and the capability probe
and installs the result as `~/.agents/RULES.md`; edits to the installed copy are overwritten on
the next install. Change this file (shared policy) or `~/.agents/LOCAL.md` (yours) instead.

- **Claude Code** imports the rendered file directly. `~/.claude/CLAUDE.md` contains
  `@~/.agents/RULES.md` and `@~/.agents/LOCAL.md`, so edits take effect on the next session with no
  sync step.
- **Codex CLI** has no import mechanism, so `~/.codex/AGENTS.md` carries synced copies between
  these markers:

  ```
  <!-- BEGIN SHARED RULES (synced from ~/.agents/RULES.md) -->
  ...
  <!-- END SHARED RULES -->

  <!-- BEGIN LOCAL RULES (synced from ~/.agents/LOCAL.md) -->
  ...
  <!-- END LOCAL RULES -->
  ```

  Run `sync-agents rules` after editing `RULES.md` or `LOCAL.md` to refresh those blocks (the LOCAL
  block is skipped when `LOCAL.md` does not exist). Everything outside the markers in `AGENTS.md`
  is left untouched. In this repo, `codex/AGENTS.md` holds the **template** text of `RULES.md`
  verbatim inside the SHARED block; keep the two in step when you edit either.

## Central config and LOCAL.md

`config.example.json` becomes `~/.agents/config.json` the first time you install and is yours
afterwards (edit it in the installer's Settings tab, with `./install.sh skills config set`, or by
hand; then run `./install.sh --auto`). Its keys are documented in
[`../docs/installer.md`](../docs/installer.md#central-configuration).

`LOCAL.example.md` becomes `~/.agents/LOCAL.md`: your own rules for this machine, imported by Claude
Code and synced into Codex, and never overwritten by the installer (`--force` replaces it, with a
backup).

## MCP servers

`mcp-servers.json` is keyed by server name:

```json
{
  "servers": {
    "example": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "some-mcp-server"],
      "env": {},
      "targets": ["claude", "codex"]
    }
  }
}
```

`type` is `stdio` (uses `command`/`args`/`env`) or `http` (uses `url`). `targets` picks which
tools receive the server - omit one to keep a server on a single CLI. An optional
`"enabled": false` keeps a server in the file without syncing it (`sync-agents status` shows it as
`disabled`); the Figma server ships that way. At install time the rendered copy also drops the
`headroom` server when Headroom is absent and removes a tool from every `targets` list when that
tool is off.

Running `sync-agents` writes the `[mcp_servers.*]` tables in `~/.codex/config.toml` as a
text-level edit, so every other line and comment is preserved byte-for-byte, and registers
Claude's **user-scope** servers through the `claude mcp` CLI. `~/.claude.json` is never edited
directly, because Claude Code rewrites that file and manual edits get clobbered.

## Using sync-agents

```bash
~/.agents/bin/sync-agents                # same as `mcp`
~/.agents/bin/sync-agents mcp --dry-run  # show the plan without changing anything
~/.agents/bin/sync-agents mcp --prune    # also drop servers missing from the JSON
~/.agents/bin/sync-agents rules          # refresh the AGENTS.md shared-rules and local-rules blocks
~/.agents/bin/sync-agents status         # table of server -> in Claude? in Codex? (or disabled)
```

`config.toml` is backed up to `~/.codex/config.toml.bak-sync` before any write and re-validated
with `tomllib` afterwards; a parse failure restores the backup and exits non-zero. `--prune` is
off by default and only ever touches servers the script knows about (Codex `[mcp_servers.*]`
tables and Claude user-scope entries) - plugin- and connector-provided servers are left alone.

**Optional:** put `~/.agents/bin` on your `PATH` so you can just type `sync-agents`:

```bash
echo 'export PATH="$HOME/.agents/bin:$PATH"' >> ~/.zshrc
```
