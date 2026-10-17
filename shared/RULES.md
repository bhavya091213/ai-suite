# Shared Agent Rules
<!-- installer:template -->

Tool-neutral operating rules for any coding agent (Claude Code, Codex CLI, etc.).
This file is the single source of truth; tool-specific files import or sync from it.

## A. Session Pre-Flight (Machine State Check)

{% if config.guardrails.preflight_checklist %}
Before starting implementation work in any project, check and report:

{% if profile.docker %}
- [ ] **Docker** — installed? daemon running? (`docker info`)
{% endif %}
- [ ] **Node version** — system `node -v` (currently {{ profile.node_version | default("not installed") }}){% if profile.nvm_versions %}; nvm has
      {{ profile.nvm_versions | join(", ") }} under `~/.nvm/versions/node/` — use `nvm use <version>` when a tool
      needs newer node{% endif %}
- [ ] **Env files** — note which of `.env`, `.env.local`, `.env.example` exist; never
      print secret values
- [ ] **Dependencies installed** — `node_modules` / venv / lockfile present; install if
      missing

Report results as a short checklist before writing code.
{% else %}
Pre-flight is disabled in ~/.agents/config.json. Set `guardrails.preflight_checklist` to
true to turn it back on.
{% endif %}

## B. Orchestrator Pattern

- The active/interactive session is the **orchestrator**, not the worker.
- Spawn subagents whenever possible for any self-contained unit of work: research,
  file sweeps, implementation units, reviews, tests.
- Independent subagents run in parallel, in one message — never sequentially when
  there's no dependency between them.
- The orchestrator keeps conclusions, not raw file dumps — subagents report back
  compact summaries, not full file contents.
- The orchestrator does direct work itself only for tiny single-fact lookups or
  one-line edits.

## C. Model / Effort Routing for Subagents

- **Heavy-reasoning tier** — planning, architecture, root-cause debugging,
  code/security reviews, anything ambiguous or open-ended.
- **Light tier** — well-specified small mechanical tasks: formatting, simple file
  writes, straightforward edits, running commands and reporting results.
- **State the tier explicitly on every subagent spawn.**

### Tool mapping

{% if profile.claude %}
- **Claude Code** — heavy = `{{ profile.claude_heavy }}`, light = `{{ profile.claude_light }}`
  (`{{ profile.claude_trivial }}` optional for trivial high-frequency tasks). Spawn via the
  Agent tool with an explicit `model`.
{% endif %}
{% if profile.codex %}
- **Codex CLI** — one model (currently `{{ profile.codex_model }}`) with reasoning effort levels:
  heavy = `{{ profile.codex_heavy }}`, light = `{{ profile.codex_light }}`
  (`{{ profile.codex_trivial }}` for trivial tasks). Subagents are the roles declared
  in `~/.codex/config.toml` under `[agents.*]`, backed by `~/.codex/agents/*.toml`; set
  `model_reasoning_effort` per role to match its tier. `[agents] max_threads` bounds
  parallelism.
{% endif %}
{% if profile.claude and not profile.codex %}

Only Claude Code is on for this machine; every subagent runs through it.
{% elif profile.codex and not profile.claude %}

Only Codex CLI is on for this machine; every subagent runs through it.
{% endif %}

## D. Context Budget (Avoid Context Rot)

- A subagent's context must never exceed **{{ profile.context_budget_k }} tokens**. Scope each task to fit;
  hand it only the files/paths it actually needs.
- If a subagent finds the task cannot be completed within {{ profile.context_budget_k }} tokens, it must
  **STOP** and ask the orchestrator for an increased budget — stating what it has
  done, what remains, and the estimated tokens needed — rather than continuing and
  degrading.
- The orchestrator then either splits the task into smaller units or explicitly
  grants more budget.
- The same guidance applies to the orchestrator itself: compact or hand off at
  logical phase boundaries rather than letting the session bloat.

## E. {% if config.guardrails.never_delete %}Never Delete (No `rm`){% else %}Deleting Files (Prefer `mv`){% endif %}

{% if config.guardrails.never_delete %}
- Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv` instead.
- If something must be retired, `mv` it into a backup location (e.g.
  `~/.agents/backups/retired-<what>/`) and say so in the report.
- Put this rule verbatim in every subagent brief that touches the filesystem.
{% else %}
- Prefer `mv` into a backup location (e.g. `~/.agents/backups/retired-<what>/`) over
  `rm`, directly or via a subagent.
- Run `rm` only on an explicit user request in this session, and say what was removed
  in the report.
- Put this rule verbatim in every subagent brief that touches the filesystem.
{% endif %}

## F. Environment & defaults (generated)

Detected by `./install.sh` on this machine. Change `~/.agents/config.json`, not this section.

- **Tools detected** (with versions):
{% if caps.claude.present %}
  - `claude` {{ caps.claude.version | default("(version unknown)") }}
{% endif %}
{% if caps.codex.present %}
  - `codex` {{ caps.codex.version | default("(version unknown)") }}
{% endif %}
{% if caps.gemini.present %}
  - `gemini` {{ caps.gemini.version | default("(version unknown)") }}
{% endif %}
{% if caps.git.present %}
  - `git` {{ caps.git.version | default("(version unknown)") }}
{% endif %}
{% if caps.gh.present %}
  - `gh` {{ caps.gh.version | default("(version unknown)") }}
{% endif %}
{% if caps.node.present %}
  - `node` {{ caps.node.version | default("(version unknown)") }}
{% endif %}
{% if caps.nvm.present %}
  - `nvm`{% if profile.nvm_versions %} — node {{ profile.nvm_versions | join(", ") }}{% endif %}
{% endif %}
{% if caps.docker.present %}
  - `docker` {{ caps.docker.version | default("(version unknown)") }} — daemon state is not recorded here; check `docker info` at session start (section A)
{% endif %}
{% if caps.python.present %}
  - `python3` {{ caps.python.version | default("(version unknown)") }}
{% endif %}
{% if caps.uv.present %}
  - `uv` {{ caps.uv.version | default("(version unknown)") }}
{% endif %}
{% if caps.bun.present %}
  - `bun` {{ caps.bun.version | default("(version unknown)") }}
{% endif %}
{% if caps.deno.present %}
  - `deno` {{ caps.deno.version | default("(version unknown)") }}
{% endif %}
{% if caps.go.present %}
  - `go` {{ caps.go.version | default("(version unknown)") }}
{% endif %}
{% if caps.cargo.present %}
  - `cargo` {{ caps.cargo.version | default("(version unknown)") }}
{% endif %}
{% if caps.obsidian.present %}
  - `obsidian` {{ caps.obsidian.version | default("(version unknown)") }}
{% endif %}
{% if caps.tmux.present %}
  - `tmux` {{ caps.tmux.version | default("(version unknown)") }}
{% endif %}
{% if caps.headroom.present %}
  - `headroom` {{ caps.headroom.version | default("(version unknown)") }}
{% endif %}
{% if caps.shellcheck.present %}
  - `shellcheck` {{ caps.shellcheck.version | default("(version unknown)") }}
{% endif %}
- **Review backend**: {{ profile.review_backend }}
{% if profile.vaults %}
- **Obsidian vaults** (default first):
{% for vault in profile.vaults %}
  - {{ vault | tilde }}{% if loop.first %} (default){% endif %}
{% endfor %}
{% else %}
- **Obsidian vaults**: none configured
{% endif %}
- **Sessions dir**: {{ profile.sessions_dir | tilde }}
- **Backups dir**: {{ profile.backups_dir | tilde }}
- **Hook profile**: {{ profile.hook_profile }}
- **Disabled hooks**: {{ profile.disabled_hooks | default("none") }}

Regenerate with ./install.sh after changing ~/.agents/config.json.
