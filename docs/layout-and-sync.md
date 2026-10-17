# Repository Layout & Sync Model

This repo is a packaged snapshot of three live config directories. Each top-level
directory maps 1:1 onto a home-directory target:

| Repo directory | Installs to | Owner |
|---|---|---|
| `shared/` | `~/.agents/` | both tools — the source of truth |
| `claude-code/` | `~/.claude/` | Claude Code |
| `codex/` | `~/.codex/` | Codex CLI |
| `installer/` | — | the tool that installs the rest (TUI + CLI); not installed |
| `docs/` | — | this documentation, not installed |

The organising principle: **anything tool-neutral lives in `shared/` and is
rendered into both tools.** Tool-specific material stays in its own tree. Files
that carry an `installer:template` marker are additionally **rendered** from
`~/.agents/config.json` and the tools found on the machine at install time (see
[Template rendering](#template-rendering)), so the repo holds template text and
the home directory holds the result.

---

## Directory tree

```
ai-suite/
├── installer/                   (not installed) python3 -m installer: TUI + CLI
│   ├── ARCHITECTURE.md            module contract
│   ├── core/  tui/  tests/        stdlib-only Python 3.9+; cli*.py front end
├── shared/                      → ~/.agents/
│   ├── RULES.md                   shared operating rules, a template (source of truth)
│   ├── config.example.json        → ~/.agents/config.json, only when absent
│   ├── LOCAL.example.md           → ~/.agents/LOCAL.md, only when absent
│   ├── extras.json                external integrations; read from the repo, not installed
│   ├── mcp-servers.json           MCP server definitions for both tools
│   ├── skill-lock.json            provenance for externally-sourced skills
│   ├── bin/                       sync-agents
│   └── skills/                    90 tool-neutral skills
├── claude-code/                 → ~/.claude/
│   ├── CLAUDE.md                  10 lines; imports RULES.md and LOCAL.md
│   ├── settings.example.json
│   ├── agents/                    32 subagent definitions
│   ├── commands/                  57 slash commands
│   ├── rules/                     common/ + cpp, golang, kotlin, perl, php,
│   │                              python, swift, typescript
│   ├── hooks/                     hooks.json + README.md
│   ├── scripts/                   hooks/, codex-review-pipeline/,
│   │                              setup-package-manager.js
│   └── skills/                    15 Claude-only skills (incl. learned/)
├── codex/                       → ~/.codex/
│   ├── AGENTS.md                  230 lines; hosts the synced rules and local-rules blocks
│   ├── config.example.toml
│   ├── hooks.json
│   ├── agents/                    11 role .toml files
│   ├── prompts/                   codex-agents/, codex-commands/,
│   │                              codex-rules/, openai-codex-plugin/
│   ├── scripts/                   14 codex-* wrappers + ecc/
│   ├── skills/                    14 Codex variants of the Claude-only skills
│   └── workflows/                 claude-to-codex-equivalents.md
├── docs/                          this directory
└── install.sh                     front door: TUI on a terminal, headless otherwise
```

---

## The skill symlink model

Skills exist in three places and are wired differently depending on whether they
are tool-neutral.

**Shared skills (90)** live once in `~/.agents/skills/` and are **symlinked** into
both tools:

```
~/.claude/skills/api-design -> ../../.agents/skills/api-design
~/.codex/skills/api-design  -> ../../.agents/skills/api-design
```

Relative links, so the pair survives a move of the home directory. Editing
`~/.agents/skills/<name>/SKILL.md` immediately changes the skill in both tools —
there is no copy step and no drift.

**Platform-specific skills stay real directories.** The same name can exist in
both trees with genuinely different content, because the harnesses differ. Compare
the two `strategic-compact` variants:

| | `claude-code/skills/strategic-compact` | `codex/skills/strategic-compact` |
|---|---|---|
| description | "Suggests manual context compaction at logical intervals…" | "Preserve important context at phase boundaries by writing Codex memory snapshots…" |
| mechanism | lifecycle hooks + `/compact` | explicit writes to `.codex/memory/` or `~/.codex/memory/snapshots/` |
| `origin` | `ECC` | `ECC migrated to Codex` |

Same split for `continuous-learning` (`~/.claude/skills/learned/` vs
`~/.codex/skills/learned/`) and `continuous-learning-v2`
(`~/.claude/homunculus/` vs `~/.codex/homunculus/`).

The 14 names present in both tool trees —  `ai-regression-testing`,
`configure-ecc`, `continuous-learning`, `continuous-learning-v2`, `eval-harness`,
`frontend-slides`, `iterative-retrieval`, `laravel-verification`,
`mcp-server-patterns`, `plankton-code-quality`, `project-guidelines-example`,
`skill-stocktake`, `strategic-compact`, `verification-loop` — are real
directories on both sides, not links. `claude-code/skills/` has one extra:
`learned/`, the output directory for the continuous-learning system.

`shared/skill-lock.json` records provenance for skills pulled from external
repositories (source repo, `sourceUrl`, `skillPath`, `skillFolderHash`,
`installedAt`/`updatedAt`) — e.g. `remotion-best-practices` from
`remotion-dev/skills`, `find-skills` from `vercel-labs/skills`, `neon` and
`neon-postgres` from `neondatabase/agent-skills`, `frontend-design` from
`anthropics/skills`, `userflow` and the fifteen `flow-*` skills from
`jpoindexter/ux-flow-skills`, `information-architecture` from
`rampstackco/claude-skills`, `slide-deck`, `minto-pyramid`, `bluf` and
`exec-summary` from `patrick204nqh/skills`, and `executive-communication` from
`refoundai/lenny-skills`. Each vendored skill keeps its upstream `LICENSE.txt`
in its own folder. Tools that are better installed from their own source
(Impeccable, the Figma MCP server, Anthropic's `pptx` skill, `ppt-master`,
`presentation-skill`) are not vendored; they are listed in `shared/extras.json`
and offered by the installer's Extras tab — see [installer.md](installer.md#extras).

---

## How `RULES.md` reaches both tools

`shared/RULES.md` is a 173-line **template** and states its own status up front:

> Tool-neutral operating rules for any coding agent (Claude Code, Codex CLI,
> etc.). **This file is the single source of truth**; tool-specific files import
> or sync from it.

Its five rule sections: **A.** Session Pre-Flight · **B.** Orchestrator Pattern ·
**C.** Model / Effort Routing · **D.** Context Budget · **E.** Never Delete. A sixth,
**F. Environment & defaults (generated)**, lists the tools and versions found on the
machine, the review backend, the Obsidian vaults (default first), the sessions and
backups directories, the hook profile and the disabled hooks. Sections A, C, D and E
adapt to `~/.agents/config.json` (Docker and Node lines, which tools are mentioned,
the configured models and efforts, the context budget, hard vs soft never-delete).

The repo copy contains `{{ }}` / `{% %}` tags; the installed `~/.agents/RULES.md`
is the rendered result. Both tools consume the **rendered** file, by different
mechanisms because the two harnesses differ:

### Claude Code — native import

`~/.claude/CLAUDE.md` stays tiny (10 lines) and pulls the rules in at load time:

```markdown
# Global Instructions

Shared cross-tool rules live in ~/.agents/RULES.md and are imported below.

@~/.agents/RULES.md

Personal rules live in ~/.agents/LOCAL.md (yours to edit; the installer never overwrites it).
@~/.agents/LOCAL.md

See ~/.claude/rules/common/agents.md and performance.md for the fuller agent/model guidance.
```

The two `@` lines are Claude Code file imports. Nothing is copied — edit `LOCAL.md`
and the next session sees it; after changing `shared/RULES.md` or `config.json`,
re-run the installer (`./install.sh --auto`) so `~/.agents/RULES.md` is re-rendered.
No sync command is needed for Claude.

### Codex CLI — marker blocks, refreshed by `sync-agents rules`

Codex has no import directive, so the rules text is **materialised** into
`~/.codex/AGENTS.md` between markers:

```
<!-- BEGIN SHARED RULES (synced from ~/.agents/RULES.md) -->
...the rendered RULES.md...
<!-- END SHARED RULES -->

<!-- BEGIN LOCAL RULES (synced from ~/.agents/LOCAL.md) -->
...your LOCAL.md...
<!-- END LOCAL RULES -->
```

In `codex/AGENTS.md` (the repo copy) the SHARED block sits at lines 53-227 and holds
the **template text**, verbatim, with an empty LOCAL pair at lines 229-230 — Codex-specific
guidance lives above them. `codex/AGENTS.md` is always rendered at install time, so the
installed file has the rendered rules in that block. Running:

```bash
~/.agents/bin/sync-agents rules
```

replaces everything between the SHARED markers with `~/.agents/RULES.md`, then does the
same for the LOCAL markers when `~/.agents/LOCAL.md` exists (the LOCAL block is inserted
after the SHARED one if its markers are absent; with no `LOCAL.md` it is skipped silently).
If the SHARED markers are absent it appends the block and reports
`append block (markers absent)`. If everything already matches it prints
`already in sync` and exits 0. `--dry-run` reports the actions and line counts without
writing. `install.sh` runs this at the end of the codex section.

**Consequence:** after editing `shared/RULES.md` in the repo or `config.json`, run the
installer so the file is re-rendered (Claude picks it up from there). After editing
`~/.agents/LOCAL.md`, Claude needs nothing but Codex needs `sync-agents rules`, or
`AGENTS.md` goes stale.

**Keeping the repo block honest:** the block in `codex/AGENTS.md` must equal
`shared/RULES.md` byte for byte. Check with
`diff <(sed -n '/BEGIN SHARED RULES/,/END SHARED RULES/p' codex/AGENTS.md | sed '1d;$d') shared/RULES.md`
(no output means in sync) and commit the two files together. Never paste rendered
output into the repo.

---

## Template rendering

`install.sh` renders `shared/`, `claude-code/` and `codex/` into a staging directory
(`python3 -m installer render-tree <dir> <out> --rel <dir>`) before installing, and installs the
staged copies. Rendering is opt-in per file; everything else is copied byte for byte.

| Mechanism | Trigger | Effect |
| --- | --- | --- |
| Template | `installer:template` in the first five lines (`codex/AGENTS.md` is always rendered) | `{{ }}` and `{% %}` tags are filled from `config.*`, `caps.*` and `profile.*` |
| Requirement | `installer:requires <tool>` / `installer:requires-any <tool>...` in the first five lines | The file is left out when the tool is off |
| Directory requirement | a `.installer-requires` file | The whole directory is left out (the file itself is never installed) |
| Rewrite rule | path-based, no marker | Agent models and reasoning efforts, `[agents]` limits, `ECC_HOOK_PROFILE` / `ECC_DISABLED_HOOKS`, Headroom and Codex entries stripped from example JSON / TOML / MCP files |

Templates in the repo: `shared/RULES.md`, `claude-code/commands/orchestrate.md` (drops the Codex
review phase when the backend is Claude) and `codex/AGENTS.md`. Requirement markers: Codex-only
(`codex-review-runner`, `multi-backend`, `multi-execute`, `multi-plan`, the whole
`codex-review-pipeline/` directory), Gemini-only (`multi-frontend`), either (`multi-workflow`).

Inspect the result without installing anything:

```bash
./install.sh skills render shared/RULES.md                         # one file (exit 3 if excluded)
./install.sh skills render-tree shared "$(mktemp -d)/shared" --rel shared
./install.sh --headless --all --dry-run                            # the whole plan
```

Full syntax and every rewrite rule: [installer.md](installer.md#rendering).

---

## Central config and LOCAL.md

Two files in `~/.agents/` are the user's, created from examples **only when absent** and never
overwritten by a normal install (`--force` replaces them, with a backup):

| File | From | Purpose |
| --- | --- | --- |
| `config.json` | `shared/config.example.json` | Tools on/off/auto, subagent model tiers, review backend, guardrails (never-delete, context budget, approval gates, hook profile), Obsidian vaults, editor. Edited in the installer's Settings tab or with `skills config set` |
| `LOCAL.md` | `shared/LOCAL.example.md` | Personal rules. Imported by Claude Code through `CLAUDE.md`, synced into `~/.codex/AGENTS.md` by `sync-agents rules` |

Every key is documented in [installer.md](installer.md#central-configuration). `~/.agents/RULES.md`,
by contrast, is **rendered** on every install: edits there are overwritten, so personal rules
belong in `LOCAL.md` and shared policy in `shared/RULES.md`.

---

## How MCP servers reach both tools

`shared/mcp-servers.json` is the source of truth, with a `_comment` field saying
so. Schema per entry: `type` (`stdio` | `http`), `command`/`args`/`env` for
stdio, `url` for http, and `targets` listing which tools get it.

Current servers, all targeting both tools: `context7`, `exa` (http),
`github`, `headroom`, `memory`, `playwright`, `sequential-thinking`, `trello`,
plus `figma` (http), which ships with `"enabled": false`. `sync-agents` skips a
disabled server and `sync-agents status` lists it as `disabled`; flip the flag if
you prefer the Figma MCP route to the Claude plugin (see
[installer.md](installer.md#extras)). The installed copy is rendered too: the
`headroom` server is dropped when Headroom is not installed, and `codex` /
`claude` are removed from the `targets` of every server when that tool is off.

```bash
~/.agents/bin/sync-agents mcp          # default subcommand
```

renders each entry into **both**:

- `~/.codex/config.toml` as `[mcp_servers.<name>]` tables — a text-level edit
  that preserves the rest of the file, with `tomllib` used only for reading and
  validation, and a `.bak-sync` backup alongside.
- Claude Code's user-scope MCP list via the `claude mcp` CLI. The comment in
  `mcp-servers.json` is emphatic: **"Never hand-edit `~/.claude.json` — Claude
  Code rewrites it."**

The loader validates before touching anything: `type` must be `stdio` or `http`,
stdio entries need a `command`, http entries need a `url`, and `targets` must be
a list. A bad entry aborts the run with `error: <name>: …`.

---

## `sync-agents` reference

[`shared/bin/sync-agents`](../shared/bin/sync-agents) is a 446-line Python 3
script (needs `tomllib`, i.e. Python 3.11+). Running it with no subcommand, or
with only flags, defaults to `mcp`.

| Subcommand | Flags | Does |
|---|---|---|
| `mcp` (default) | `--dry-run`, `--prune` | render `mcp-servers.json` into `~/.codex/config.toml` and Claude's user scope |
| `rules` | `--dry-run` | refresh the SHARED RULES block in `~/.codex/AGENTS.md`, and the LOCAL RULES block from `~/.agents/LOCAL.md` when that file exists |
| `status` | — | table of which servers each tool currently has (or `disabled`), plus drift |

```bash
sync-agents                 # == sync-agents mcp
sync-agents mcp --dry-run   # print the plan, change nothing
sync-agents mcp --prune     # also remove servers not in mcp-servers.json
sync-agents rules
sync-agents status
```

`--dry-run` prints a `PLAN (dry run)` block instead of `APPLIED`; nothing is
written. `--prune` is opt-in and scoped: on the Claude side it only considers
user-scope server names, so project-scoped servers are never touched.

`status` output looks like:

```
server               claude  codex   targets
-------------------  ------  ------  -------
context7             yes     yes     claude,codex
exa                  yes     yes     claude,codex
...

in codex but not in mcp-servers.json: <names>
in claude user scope but not in mcp-servers.json: <names>
```

Those two trailing lines are the drift report — they tell you what `--prune`
would remove.

`mcp` exits 1 if any server failed to apply; `rules` exits 1 if
`~/.agents/RULES.md` does not exist.

---

## Installing

```bash
./install.sh                # on a terminal: the interactive installer (Python 3.9+)
./install.sh --all          # headless: shared + claude-code + codex
./install.sh --auto         # headless: shared + whichever tools this machine has
./install.sh --shared       # ~/.agents only
./install.sh --claude       # ~/.claude only
./install.sh --codex        # ~/.codex only
./install.sh --dry-run      # print the plan, change nothing (combine with the above)
./install.sh skills status  # the skill manager: python3 -m installer status
```

Config files ship as examples — `claude-code/settings.example.json`,
`codex/config.example.toml`, `shared/config.example.json`,
`shared/LOCAL.example.md` — and `claude-code/CLAUDE.md` is treated the same way,
so installing never clobbers live credentials or machine-specific settings or
your own rules. Each is installed only when its target is absent (`--force`
replaces them, with a backup); the rendered examples reflect your config at that
moment. Compare an existing file with `diff` or the installer's Files tab (`d`).

The full guide, with every key and command, is [installer.md](installer.md).

After a fresh install, run the sync pass once so Codex picks up the rules block
and both tools get the MCP list (the install already runs `sync-agents rules`):

```bash
~/.agents/bin/sync-agents rules
~/.agents/bin/sync-agents mcp
~/.agents/bin/sync-agents status     # verify
```

---

## Never delete

`shared/RULES.md` § E is a standing rule for every agent and for the tooling:

> - Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv`
>   instead.
> - If something must be retired, `mv` it into a backup location (e.g.
>   `~/.agents/backups/retired-<what>/`) and say so in the report.
> - Put this rule verbatim in every subagent brief that touches the filesystem.

The tooling follows it rather than exempting itself:

- The installer **backs up** anything it would overwrite into
  `~/.agents/backups/` instead of removing it. Its Python side obeys the same
  rule: retiring, updating and relinking a skill *move* the old copy there, and
  saving `config.json` copies the previous file there first.
- `sync-agents mcp` writes `~/.codex/config.toml.bak-sync` before editing.
- `sync-agents mcp --prune` removes *table entries from a config file* — a config
  edit, not a filesystem delete — and only for user-scope names present in the
  tool but absent from `mcp-servers.json`. It is opt-in for that reason.

`~/.agents/backups/` is a real, populated directory on a live install. Retired
config is relocated there, never deleted, so a bad sync or install is always
reversible.

---

## Editing checklist

| You changed | Then run |
|---|---|
| `shared/RULES.md` (or any template: `orchestrate.md`, `codex/AGENTS.md`) | regenerate the `codex/AGENTS.md` block in the repo (byte-for-byte copy), then `./install.sh --auto` (or Settings → Apply) to re-render; Claude picks up the rendered file automatically, Codex via the install's `sync-agents rules` |
| `~/.agents/config.json` | `./install.sh --auto` (or Settings → `A`) to re-render with the new values |
| `~/.agents/LOCAL.md` | nothing for Claude; `sync-agents rules` for Codex |
| `shared/config.example.json` or `installer/core/config.py` defaults | change both together (a test checks they match), update the key table in [installer.md](installer.md) |
| `shared/extras.json` | nothing to sync; keep the README and [installer.md](installer.md) extras tables in step |
| `shared/mcp-servers.json` | `sync-agents mcp` (after `./install.sh` if the installed copy needs re-rendering) |
| `shared/skills/<name>/` | nothing — symlinked live into both tools |
| `claude-code/skills/<name>/` | nothing — Claude-only, real directory |
| `codex/skills/<name>/` | nothing — Codex-only, real directory |
| `claude-code/agents/`, `commands/`, `rules/` | nothing — read at session start |
| `codex/agents/*.toml` | nothing — read via `config_file` in `config.toml` |
| `claude-code/hooks/hooks.json`, `codex/hooks.json` | restart the session |

When in doubt, `sync-agents status` shows the current drift between the source of
truth and what each tool actually has.
