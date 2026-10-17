# codex/ - mirrors `~/.codex`

Everything in here installs into `~/.codex`. Tool-agnostic material (rules, skills, MCP servers)
lives in [`../shared`](../shared) instead and is symlinked or synced in.

## Contents

| Path | Installs to | What it is |
| --- | --- | --- |
| `AGENTS.md` | `~/.codex/AGENTS.md` | Global instructions, carrying synced copies of the shared rules and your local rules. Rendered at install time |
| `config.example.toml` | `~/.codex/config.toml` | Model, sandbox, MCP servers, profiles, `[agents.*]` roles. Installed only when absent |
| `hooks.json` | `~/.codex/hooks.json` | Codex hook wiring (Headroom hooks are dropped when Headroom is absent) |
| `agents/` | `~/.codex/agents/` | 11 native multi-agent role definitions (`*.toml`); model and reasoning effort mapped to your configured tiers |
| `scripts/` | `~/.codex/scripts/` | `codex-*` wrappers, the `ecc/` toolkit, `codex-companion-runtime` |
| `prompts/` | `~/.codex/prompts/` | Prompt recipes: 57 `codex-commands`, 26 `codex-agents`, `codex-rules`, `openai-codex-plugin` |
| `skills/` | `~/.codex/skills/` | 14 Codex variants of the platform-specific skills |
| `workflows/` | `~/.codex/workflows/` | `claude-to-codex-equivalents.md` mapping table |

The 89 shared skills are **not** here. They are symlinked from `~/.agents/skills` into
`~/.codex/skills` at install time, so both CLIs load the same file.

## AGENTS.md and the shared rules block

Codex has no import directive, so `AGENTS.md` carries a copy of the shared rules between two
markers, followed by a block for your personal rules:

```
<!-- BEGIN SHARED RULES (synced from ~/.agents/RULES.md) -->
...
<!-- END SHARED RULES -->

<!-- BEGIN LOCAL RULES (synced from ~/.agents/LOCAL.md) -->
...
<!-- END LOCAL RULES -->
```

In **this repo**, the SHARED block holds the verbatim *template* text of `shared/RULES.md` (with its
`{{ }}` tags), and the LOCAL block is empty. `AGENTS.md` is always rendered at install time, so the
installed `~/.codex/AGENTS.md` has the rules filled in for your machine; `sync-agents rules` then
refreshes both blocks from `~/.agents/RULES.md` and `~/.agents/LOCAL.md` (the LOCAL block only when
that file exists). Run `~/.agents/bin/sync-agents rules` after editing either. Everything outside the
markers is hand-written Codex-specific guidance and is preserved. When you edit `shared/RULES.md`,
update the SHARED block here in the same commit (see `AGENTS.md` at the repo root).

## config.example.toml

Installed to `~/.codex/config.toml` only when that file does not exist; edit it afterwards.
At install time the example is rendered: the default `model` and the `[agents]` `max_threads` /
`max_depth` follow the `subagents.codex.*` keys in `~/.agents/config.json` (so do the `model` and
`model_reasoning_effort` in each `agents/*.toml` role file), and when Headroom is absent its blocks
are commented out. Machine-specific state has been stripped from the example on purpose, because
Codex writes it itself on first use and it must not travel between machines:

- `[projects.*]` per-project trust tables
- `[hooks.state.*]` trusted hashes and the `notify` hook
- the local `node_repl` MCP server entry

What remains: default model and `model_reasoning_effort`, `approval_policy`, `sandbox_mode`,
`web_search`, the MCP server tables (github, context7, exa, memory, playwright,
sequential-thinking, trello, plus commented-out credentialed ones), `[features]` with
`multi_agent = true`, the `strict`/`yolo` profiles, and `[agents]` with `max_threads = 6`,
`max_depth = 1` followed by the 11 role registrations. Note that `~` in `command = ...` values is
expanded by the installer, not by Codex - if you hand-edit, use absolute paths.

## Scripts

| Script | What it does |
| --- | --- |
| `codex-job` | The core dispatcher; runs `codex-companion-runtime/scripts/codex-companion.mjs` |
| `codex-rescue` | `codex-job task` - hand a substantial coding task or investigation to Codex |
| `codex-review` | `codex-job review` - review the current diff |
| `codex-adversarial-review` | `codex-job adversarial-review` - the hunt/adjudicate review pass |
| `codex-status` | `codex-job status` - state of running jobs |
| `codex-result` | `codex-job result` - fetch a finished job's output |
| `codex-cancel` | `codex-job cancel` - stop a running job |
| `codex-setup` | `codex-job setup` - check the local Codex CLI and the stop-time review gate |
| `codex-prompt` | Run a prompt recipe: `codex-prompt <recipe-name\|path> [args...]` |
| `codex-knowledge` | Runs the `local-knowledge-retrieval` skill's `knowledge_index.py` indexer |
| `codex-save-context` | Writes a timestamped memory snapshot (`global` or `project` scope) |
| `codex-mcp-trello` | Launches the Trello MCP server, reading credentials from env or the macOS Keychain |
| `codex-setup-package-manager` | Runs `ecc/setup-package-manager.js` to pick npm/pnpm/yarn/bun |
| `ecc/` | The ported ECC toolkit: `ecc.js`, `doctor.js`, `claw.js`, codemaps, sessions, orchestration status, harness audit, git hooks |

## Prompts are recipes, not slash commands

Codex has no user-defined slash commands. `prompts/` holds **prompt recipes** - the Claude
commands, agents and rules re-expressed as prompt text - and you invoke one with:

```bash
codex-prompt build-fix
codex-prompt tdd 'add liquidity score tests'
```

`prompts/codex-commands/` is the 1:1 counterpart of `claude-code/commands/`,
`prompts/codex-agents/` of `claude-code/agents/`, and `prompts/codex-rules/` of
`claude-code/rules/`. `workflows/claude-to-codex-equivalents.md` is the lookup table between the
two worlds.

## codex-companion-runtime provenance

`scripts/codex-companion-runtime/` is a **vendored copy of OpenAI's Codex plugin**, licensed
Apache-2.0. Its `LICENSE` and `NOTICE` files ship unmodified alongside the code. It supplies the
job runtime (`scripts/codex-companion.mjs`) that every `codex-*` wrapper above delegates to, plus
its own agents, commands, hooks, prompts, schemas and skills. Treat it as third-party: prefer
re-vendoring an upstream release over patching it in place, and if you must patch, record it in
the commit message.
