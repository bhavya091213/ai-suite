# ai-suite

One configuration, two CLIs. This repo packages a working Claude Code + Codex CLI setup built
around a single idea: the lead session is an **orchestrator, not a worker**. It investigates,
gates on your approval, then hands bounded units of work to subagents with an explicit model /
reasoning-effort tier and a hard **100k-token context budget** each. Nothing is ever deleted
(retired files are moved to a backup directory, never `rm`ed), and the rules, skills and MCP
server list live in **one shared source of truth** (`shared/`, mirroring `~/.agents`) that both
tools read, so Claude Code and Codex never drift apart.

`./install.sh` opens an **interactive installer** on a terminal: browse and install skills, edit one
central config (`~/.agents/config.json`), check for upstream updates and run the full install. The
repo files are then rendered for the machine they land on - only the tools you have, your model
tiers, your guardrails, your Obsidian vaults - and your own rules live in a `LOCAL.md` the installer
never overwrites.

## What's inside

```
installer/                  interactive (curses) + CLI installer; Python 3.9+, stdlib only
  ARCHITECTURE.md           module contract; tests: python3 -m unittest discover -s installer/tests -t .
shared/                     mirrors ~/.agents - single source of truth
  RULES.md                  shared operating rules, a template (sections A-E, generated F)
  config.example.json       central config; installed to ~/.agents/config.json only when absent
  LOCAL.example.md          your personal rules; installed to ~/.agents/LOCAL.md only when absent
  extras.json               external integrations the installer can detect and install (5)
  mcp-servers.json          MCP servers, with per-tool targets (one disabled: figma)
  skill-lock.json           pinned upstream skill provenance
  bin/sync-agents           renders rules, local rules + MCP config into both tools
  skills/                   90 shared skills (symlinked into BOTH CLIs)
claude-code/                mirrors ~/.claude
  CLAUDE.md                 imports shared rules via @~/.agents/RULES.md and @~/.agents/LOCAL.md
  settings.example.json     permissions, env, hooks, model, plugins
  agents/                   32 subagent definitions
  commands/                 57 slash commands
  rules/                    common/ + cpp, golang, kotlin, perl, php, python, swift, typescript
  hooks/hooks.json          PreToolUse / PostToolUse / Stop / SessionStart wiring
  scripts/hooks/            25 hook implementations
  scripts/codex-review-pipeline/   Codex-first adversarial review runner
  skills/                   14 Claude variants of platform-specific skills + learned/
codex/                      mirrors ~/.codex
  AGENTS.md                 carries synced copies of RULES.md and LOCAL.md between markers
  config.example.toml       model, sandbox, MCP servers, profiles, [agents.*]
  hooks.json                Codex hook wiring
  agents/                   11 native multi-agent role definitions (*.toml)
  scripts/                  codex-* CLI wrappers, ecc/ toolkit, codex-companion-runtime
  prompts/                  prompt recipes (codex-commands, codex-agents, codex-rules, ...)
  skills/                   14 Codex variants of platform-specific skills
  workflows/                Claude-to-Codex equivalence map
mods/ai-suite/              Claude Code mod: the skills manager as a pane inside Claude
.claude-plugin/marketplace.json  lets /plugin install the mod from this repo
docs/                       long-form guides (installer.md, layout-and-sync.md, ...)
install.sh                  front door: TUI on a terminal, headless otherwise; renders, links, backs up
```

## Quick start

```bash
git clone https://github.com/bhavya091213/ai-suite.git
cd ai-suite

./install.sh                # on a terminal: opens the interactive installer (needs Python 3.9+)
```

That is the recommended path: the first run walks you through a short setup wizard, then you can
browse skills, review the plan and install. Prefer a script? Everything is also available headless:

```bash
./install.sh --headless --all --dry-run   # show exactly what would change, touch nothing
./install.sh --all                        # install shared + Claude Code + Codex
./install.sh --auto                       # install only what this machine has (see Settings)
```

Restart both CLIs afterwards so they re-read their config.

| Flag | Effect |
| --- | --- |
| *(none, on a terminal)* | Launch the interactive installer; with no terminal, the headless install of everything |
| `--tui` | Force the interactive installer (cannot be combined with other flags) |
| `--headless` | Headless install of everything, even on a terminal |
| `--all` | Shared + Claude Code + Codex |
| `--claude` | Only `~/.claude` |
| `--codex` | Only `~/.codex` |
| `--shared` | Only `~/.agents` (rules, skills, MCP servers) |
| `--auto` | The sections chosen by `python3 -m installer sections`: shared plus each tool your config resolves to on |
| `--dry-run` | Print the plan, change nothing |
| `--force` | Also replace the files that are yours once installed (see below); previous copies go to `~/.agents/backups/` |
| `skills <command>` | Run the skill manager headless: `./install.sh skills status`, `install`, `update`, `retire`, `config`, `doctor`, ... |
| `-h` | Help |

`INSTALLER_PYTHON=/path/to/python3` makes the installer use a specific interpreter (useful on a Mac
whose `/usr/bin/python3` is a stub).

The skill manager is the same engine the interactive installer uses:

```bash
./install.sh skills status                          # every skill: state, links, upstream changes
./install.sh skills install flow-auth flow-forms    # add skills (never overwrites an installed one)
./install.sh skills update frontend-design          # replace a modified skill; the old copy is backed up
./install.sh skills retire bun-runtime              # move to ~/.agents/backups/, never delete
./install.sh skills issues                          # duplicates, broken links, foreign skills
./install.sh skills config set tools.codex off      # change the central config
./install.sh skills workflow example --json > my-workflow.json   # a sample workflow definition to edit
./install.sh skills workflow save my-workflow.json  # validate, render, install and link it into both CLIs
./install.sh skills doctor                          # check Python, curses, git, config and tools
```

The installer never deletes: anything it replaces is first moved into a timestamped folder under
`~/.agents/backups/`. A few files are **yours** once installed - `~/.claude/CLAUDE.md`,
`~/.claude/settings.json`, `~/.codex/config.toml`, `~/.agents/config.json` and `~/.agents/LOCAL.md`
- and are only created when absent (or replaced, with a backup, by `--force`).

**Want just one piece?** Grab a single skill, agent or command without installing anything else:

```bash
npx degit bhavya091213/ai-suite/shared/skills/<skill> ~/.agents/skills/<skill>
npx degit bhavya091213/ai-suite/claude-code/agents ~/.claude/agents
```

## Interactive installer

Run `./install.sh` on a terminal. It is a curses program in `installer/` (Python 3.9+, standard
library only, no dependencies) with ten tabs; press a number (`0` for the tenth) to jump, `?` for the key reference.

| Tab | What it does |
| --- | --- |
| 1 Overview | Git banner, detected tools, counts per scope, and a menu of the rest |
| 2 Skills | Browse the repo catalog, multi-select, install |
| 3 Installed | What is on disk: update a modified skill, retire to a backup, relink, push a local skill back to the repo, diff |
| 4 Issues | Duplicates, broken links, foreign skills, frontmatter problems |
| 5 Updates | `git fetch`, commits behind, which skills changed upstream, fast-forward pull |
| 6 Settings | The central config: tools on/off/auto, subagent model tiers, review backend, guardrails, Obsidian vaults, editor. Doubles as the first-run wizard |
| 7 Files | Open `CLAUDE.md`, `LOCAL.md`, `config.json`, `AGENTS.md`, `settings.json`, `config.toml` in your editor; view; diff against the repo |
| 8 Install | Dry-run or apply the full install for the sections you pick |
| 9 Extras | Detect and install external integrations (Impeccable, Figma MCP, ...) |
| 0 Workflows | Compose installed skills into a phased, gated workflow; edit, view, retire or push it into the repo |

Ideas worth knowing:

- **Never deletes.** Retire, update and relink move the old copy under `~/.agents/backups/`, and
  no installed skill is ever overwritten silently - `install` only creates, `update` is explicit.
- **Plan, then confirm.** Every mutating key shows the list of operations and waits for `y`.
- **Update checks need `git`.** Without it the rest of the installer works and the Updates tab
  tells you how to install git for your platform.
- **Headless parity.** The same actions are available as `./install.sh skills <command>`.

**Workflow maker.** The Workflows tab (`0`) turns skills you already have into a *workflow*: an
ordered list of phases, each naming the skills to load, the steps, the outputs and whether to stop
for your approval. The installer validates it and saves it as an ordinary shared skill
(`~/.agents/skills/<name>/` with a `workflow.json` source of truth and a rendered `SKILL.md`),
linked into both CLIs; `p` pushes it into `shared/skills/` when you want it in the repo. Start from
the sample with `./install.sh skills workflow example --json > my-workflow.json`, edit it, then
`./install.sh skills workflow save my-workflow.json` - see
[Workflows](docs/installer.md#workflows).

Full guide, every key and every command: [docs/installer.md](docs/installer.md).

## The Claude mod

The same skills manager runs inside Claude Code as a mod. When a session starts it opens a Skills
pane (Overview, Install, Installed, Updates, Settings with preset dropdowns, Workflows, Doctor)
and a one-line row above the prompt (`Skills · 57/90 installed · 3 updates  [Open] [Hide]`).
Install it with one line in a terminal session:

```
/plugin install ai-suite --marketplace bhavya091213/ai-suite
```

It needs Claude Code v2.1.287 or newer and Python 3.9+. Everything it does is one installer CLI
call, nothing deletes, and risky actions take two presses. Full instructions, options, keys and
troubleshooting: [mods/ai-suite/README.md](mods/ai-suite/README.md).

## Central configuration

`~/.agents/config.json` is the one file that adapts the repo to your machine. It is created from
`shared/config.example.json` on first install and is yours afterwards; edit it in the Settings tab,
with `./install.sh skills config set <key> <value>`, or by hand, then run `./install.sh --auto` (or
Settings, `A`) to re-render.

| Key | Default | Controls |
| --- | --- | --- |
| `tools.claude`, `tools.codex` | `auto` | `auto` / `on` / `off` per CLI; decides which sections install and which tools the rules mention |
| `subagents.claude.{heavy,light,trivial}` | `opus` / `sonnet` / `haiku` | Models the Claude agent definitions and routing text use |
| `subagents.codex.model` | `gpt-5.6-sol` | The one model Codex roles run on |
| `subagents.codex.{heavy,light,trivial}` | `xhigh` / `medium` / `low` | `model_reasoning_effort` per tier |
| `subagents.codex.{max_threads,max_depth}` | `6` / `1` | Codex `[agents]` parallelism and nesting |
| `review.adversarial` | `auto` | `auto` / `codex` / `claude`: who runs Phase 3 of `/orchestrate` |
| `guardrails.never_delete` | `true` | Hard "no `rm`" rule vs a softer "prefer `mv`" rule in section E |
| `guardrails.context_budget_tokens` | `100000` | The per-subagent context cap in section D |
| `guardrails.preflight_checklist` | `true` | Keep the session pre-flight checklist in section A |
| `guardrails.plan_approval_gate`, `fix_approval_gate` | `true` | Gate A (plan) and Gate C (each review fix) of `/orchestrate` |
| `guardrails.hook_profile` | `standard` | `minimal` / `standard` / `strict`; becomes `ECC_HOOK_PROFILE` in `settings.json` |
| `guardrails.disabled_hooks` | `[]` | Hook ids to switch off; becomes `ECC_DISABLED_HOOKS` |
| `paths.obsidian_vaults` | `[]` | Vault directories, default first; importable from Obsidian's own registry |
| `paths.sessions_dir`, `paths.backups_dir` | `~/.claude/sessions`, `~/.agents/backups` | Recorded in the generated rules |
| `editor` | `""` | Editor command; empty means `$VISUAL`, then `$EDITOR`, then `nano`/`vim`/`vi` |

**What adapts to the machine.** The installer probes for `claude`, `codex`, `gemini`, `git`, `gh`,
`node`/`nvm`, `docker`, `python`, `uv`, `bun`, `deno`, `go`, `cargo`, `obsidian`, `tmux`, `headroom`
and `shellcheck`. Files carrying an `installer:template` marker (`shared/RULES.md`,
`claude-code/commands/orchestrate.md`, `codex/AGENTS.md`) are rendered from the config plus that probe
at install time; `installer:requires codex` / `gemini` markers leave out Codex-only and Gemini-only
agents, commands and the Codex review pipeline when that tool is off; and rewrite rules map agent
models and reasoning efforts to your tiers and strip Headroom entries from the example settings,
config and MCP files when Headroom is absent. With Codex off, `/orchestrate` drops its Codex review
phase and reviews with Claude instead. Check any file with
`./install.sh skills render <file>`. Details: [docs/installer.md](docs/installer.md#rendering).

**Your own rules.** `~/.agents/LOCAL.md` (from `shared/LOCAL.example.md`) is imported by Claude Code
through `~/.claude/CLAUDE.md` and synced into `~/.codex/AGENTS.md` by `sync-agents rules`. The
installer creates it when absent and never overwrites it.

## The orchestration workflow

`/orchestrate` runs a phased, gated pipeline instead of a single long-running session:

| Phase | What happens |
| --- | --- |
| 0. Model & reasoning check | Confirm the orchestrator is on the highest-capability model with extended thinking on |
| 1. Investigate & grill | Parallel read-only investigators (code / research / risk), then the user is interrogated until requirements are unambiguous. **Gate A: plan approval** |
| 2. Implement | Each approved unit goes to one `unit-implementer` with a bounded file scope; independent units run in parallel |
| 3. Adversarial review | Codex-first: gpt-5.5 hunts bugs, gpt-5.6-sol adjudicates, findings are triaged and each fix is individually approved. **Gate C**. With Codex off (or `review.adversarial = claude`) the same phase runs on Claude reviewers |
| 4. Handback | Compact summary, run log, no silent rollover |

The two gates can be switched off in the central config (`guardrails.plan_approval_gate`,
`guardrails.fix_approval_gate`); the plan or fix list is then logged instead of waited on.
Run state lives in `.orchestrate/<slug>/` in the project so a compaction event cannot lose the run.
Full detail: [docs/orchestration-workflow.md](docs/orchestration-workflow.md).

## Model routing

Every subagent spawn declares its tier explicitly. The table shows the defaults; the model names and
efforts come from `subagents.*` in the [central config](#central-configuration) and are written into
the agent definitions at install time.

| Tier | Claude Code | Codex CLI | Use for |
| --- | --- | --- | --- |
| Heavy | Opus | `model_reasoning_effort = "xhigh"` | Planning, architecture, root-cause debugging, reviews |
| Light | Sonnet | `low` / `medium` | Mechanical edits, formatting, running commands |
| Trivial | Haiku (optional) | `low` | High-frequency, low-stakes tasks |

Full detail: [docs/model-routing.md](docs/model-routing.md).

## Shared rules

`shared/RULES.md` is the contract both CLIs load. It is a template: the installed `~/.agents/RULES.md`
is rendered from your config and the tools found on the machine. Five rule sections plus one generated one:

- **A. Session pre-flight** - check Docker, Node version, env files and installed dependencies, and report a short checklist before writing code.
- **B. Orchestrator pattern** - the interactive session delegates; independent subagents are spawned in parallel in one message; the orchestrator keeps conclusions, not raw file dumps.
- **C. Model / effort routing** - every spawn names its tier (heavy vs light) and the tool-specific model or reasoning effort that maps to it.
- **D. Context budget** - no subagent may exceed 100k tokens; if it cannot finish it STOPs and reports work done, work remaining and tokens needed rather than degrading.
- **E. Never delete** - no `rm`, ever. Retire things by moving them to `~/.agents/backups/retired-<what>/` and say so in the report. (`guardrails.never_delete = false` renders a softer "prefer `mv`" version.)
- **F. Environment & defaults (generated)** - the tools and versions the installer detected, the review backend, Obsidian vaults (default first), sessions and backups directories, hook profile and disabled hooks. Not hand-written: change `~/.agents/config.json` and re-run the installer.

Personal additions go in `~/.agents/LOCAL.md`, not in the rendered `RULES.md`.

## Skills

104 skills total: **90 shared** (symlinked into both `~/.claude/skills` and `~/.codex/skills`) and
**14 platform-specific**, which ship as a matched pair of Claude and Codex variants because their
bodies reference tool-specific mechanics (hooks, session files, memory snapshots). Of the 89
shared skills, 23 are vendored from upstream repositories (provenance pinned in
`shared/skill-lock.json`, each license kept in the skill's folder; see
[Acknowledgements](#acknowledgements)) and three workflow skills - `skill-forge`,
`product-design-workflow` and `presentation-workflow` - are authored here. Everything is
installable one skill at a time from the installer's Skills tab.

### Orchestration, context & harness

| Skill | Scope | What it does |
| --- | --- | --- |
| dmux-workflows | shared | Multi-agent orchestration with dmux (tmux pane manager) across Codex, OpenCode, Gemini |
| token-efficient-orchestration | shared | Coordinating Codex subagents, Trello tickets, Obsidian memory and CI verification cheaply |
| find-skills | shared | Discover and install agent skills when the user asks "is there a skill for X" |
| skill-forge | shared | Phased, gated workflow that turns a task or repeatable workflow into a well-formed skill, tests it on sample prompts and places it in the right tree |
| iterative-retrieval | claude + codex | Progressively refine context retrieval to solve the subagent context problem |
| strategic-compact | claude + codex | Compact at logical phase boundaries instead of arbitrary auto-compaction |
| continuous-learning | claude + codex | Extract reusable patterns from sessions and save them as learned skills |
| continuous-learning-v2 | claude + codex | Instinct-based learning with confidence scoring and project-scoped instincts |
| eval-harness | claude + codex | Formal eval-driven-development framework for sessions |
| verification-loop | claude + codex | Comprehensive end-of-work verification system |
| skill-stocktake | claude + codex | Audit skills and commands for quality (quick scan or full portfolio) |
| configure-ecc | claude + codex | Interactive installer for the ECC skill/rule set |
| project-guidelines-example | claude + codex | Template for a project-specific skill, based on a real app |

### Engineering practice: quality, testing, security

| Skill | Scope | What it does |
| --- | --- | --- |
| coding-standards | shared | Universal standards for TypeScript, JavaScript, React and Node |
| tdd-workflow | shared | Enforces tests-first with 80%+ coverage across unit, integration and E2E |
| security-review | shared | Checklist and patterns for auth, user input, secrets, endpoints and payments |
| api-design | shared | REST resource naming, status codes, pagination, errors, versioning, rate limiting |
| e2e-testing | shared | Playwright patterns, Page Object Model, CI integration, flaky-test strategy |
| endpoint-testing | shared | Backend endpoint testing: auth, validation, DB schema sync, frontend data flow |
| ai-regression-testing | claude + codex | Sandbox-mode API testing and blind-spot checks for AI-written code |
| plankton-code-quality | claude + codex | Write-time formatting, linting and config protection |

### Languages & frameworks

| Skill | Scope | What it does |
| --- | --- | --- |
| python-patterns / python-testing | shared | Pythonic idioms, PEP 8, type hints; pytest, fixtures, mocking, coverage |
| golang-patterns / golang-testing | shared | Idiomatic Go; table-driven tests, subtests, benchmarks, fuzzing |
| rust-patterns / rust-testing | shared | Ownership, error handling, traits, concurrency; async and property-based tests |
| kotlin-patterns / kotlin-testing | shared | Idiomatic Kotlin, coroutines, DSL builders; Kotest, MockK, Kover |
| kotlin-coroutines-flows | shared | Structured concurrency, Flow operators, StateFlow, error handling |
| kotlin-ktor-patterns | shared | Ktor routing DSL, plugins, auth, Koin DI, kotlinx.serialization, WebSockets |
| kotlin-exposed-patterns | shared | Exposed ORM DSL/DAO, transactions, HikariCP, Flyway, repository pattern |
| android-clean-architecture | shared | Clean Architecture module structure and dependency rules for Android/KMP |
| compose-multiplatform-patterns | shared | Compose state management, navigation, theming, platform-specific UI |
| java-coding-standards | shared | Spring Boot naming, immutability, Optional, streams, exceptions, layout |
| springboot-patterns / -tdd / -verification | shared | Layered services and data access; JUnit 5, Mockito, Testcontainers; release gate |
| cpp-coding-standards / cpp-testing | shared | C++ Core Guidelines; GoogleTest/CTest, sanitizers, coverage |
| perl-patterns / perl-testing | shared | Modern Perl 5.36+ idioms; Test2::V0, prove, Devel::Cover |
| django-patterns / -tdd / -verification | shared | DRF APIs, ORM, caching, signals; pytest-django, factory_boy; release checks |
| laravel-patterns / laravel-tdd | shared | Eloquent, service layers, queues, events; PHPUnit and Pest |
| laravel-verification | claude + codex | Env checks, static analysis, coverage, security scan, deploy readiness |
| bun-runtime | shared | Bun as runtime, package manager, bundler and test runner; Bun vs Node |
| nextjs-turbopack | shared | Next.js 16+ incremental bundling, FS caching, Turbopack vs webpack |

### Web, API & data platform

| Skill | Scope | What it does |
| --- | --- | --- |
| frontend-patterns | shared | React/Next.js structure, state management, performance, UI practices |
| backend-patterns | shared | Node/Express/Next API routes, database optimization, server-side practices |
| claude-api | shared | Messages API, streaming, tool use, vision, thinking, batches, prompt caching |
| x-api | shared | X/Twitter posting, threads, timelines, search and analytics |
| neon | shared | Router for Neon's backend primitives: Postgres, Auth, Data API, storage, AI gateway |
| neon-postgres | shared | Lakebase Postgres setup, pooling, branching, migrations, vector and hybrid search |
| lambda-gpu-training | shared | Phased model training on Lambda cloud GPUs: intake questions, access, runs, monitoring, teardown, report |
| mcp-server-patterns | claude + codex | Build MCP servers with the Node/TS SDK: tools, resources, Zod, stdio vs HTTP |

### Design & UX

| Skill | Scope | What it does |
| --- | --- | --- |
| product-design-workflow | shared | Five-phase gated design workflow: brief, UX architecture (sitemap, flows), two or three visual directions, prototype (Figma when the MCP is connected, else clickable HTML), build verified in the browser |
| frontend-design | shared | Distinctive, intentional UI design: aesthetic direction, typography, avoiding templated defaults (vendored, Apache-2.0) |
| information-architecture | shared | Sitemap, navigation, URL structure, content types, taxonomy and labeling (vendored, MIT) |
| userflow | shared | Router for the `flow-*` family: describe what you are building and it pulls in the right flow guidance (vendored, MIT) |
| flow-ai-chat, flow-app-shell, flow-auth, flow-checkout, flow-empty-states, flow-errors, flow-forms, flow-navigation, flow-onboarding, flow-paywall, flow-permissions, flow-search, flow-settings, flow-sharing, flow-tables | shared | Fifteen proven UX flow guides: AI chat/agent interfaces, app layout shells, signup/login/2FA, checkout, empty/loading states, errors and offline, forms and wizards, navigation, onboarding, pricing and paywalls, OS permissions and notifications, search and filters, settings and account management, sharing and invites, data tables and feeds (vendored, MIT) |

### Research & knowledge

| Skill | Scope | What it does |
| --- | --- | --- |
| deep-research | shared | Multi-source research with firecrawl and exa, delivered as a cited report |
| exa-search | shared | Neural web, code, company and people search via the Exa MCP |
| documentation-lookup | shared | Fetch current library docs through Context7 instead of training data |
| defuddle | shared | Strip clutter from web pages into clean markdown to save tokens |
| local-knowledge-retrieval | shared | Index and retrieve bounded context from repo-local vaults, docs and notes |
| market-research | shared | Market sizing, competitive analysis and due diligence with source attribution |
| obsidian-markdown | shared | Obsidian Flavored Markdown: wikilinks, embeds, callouts, properties |
| obsidian-cli | shared | Drive an Obsidian vault from the CLI; plugin and theme development |
| obsidian-bases | shared | Create and edit `.base` files: views, filters, formulas, summaries |
| json-canvas | shared | Create and edit `.canvas` files: nodes, edges, groups, connections |

### Content & media

| Skill | Scope | What it does |
| --- | --- | --- |
| article-writing | shared | Long-form articles, guides and newsletters in a voice derived from examples |
| content-engine | shared | Platform-native content systems for X, LinkedIn, TikTok, YouTube, newsletters |
| crosspost | shared | Distribute across X, LinkedIn, Threads and Bluesky without identical reposts |
| video-editing | shared | AI-assisted cutting, structuring and augmenting of real footage |
| remotion-best-practices | shared | Video creation in React with Remotion |
| fal-ai-media | shared | Image, video and audio generation through the fal.ai MCP |
| frontend-slides | claude + codex | Animation-rich HTML presentations, from scratch or converted from PPTX |

### Presentations & communication

Editable `.pptx` builders are offered as [extras](#extras) instead of being vendored; for HTML decks
see `frontend-slides` above.

| Skill | Scope | What it does |
| --- | --- | --- |
| presentation-workflow | shared | Story first, deck second: audience, one-sentence takeaway, BLUF, Minto pyramid, outline and Q&A bank, then picks the format (`.pptx` or HTML), builds and QAs the deck |
| slide-deck | shared | Turn content into a short deck: one idea per slide, takeaway headlines, speaker notes (vendored, MIT) |
| minto-pyramid | shared | Structure a long argument or proposal: answer first, two to four MECE reasons, detail underneath (vendored, MIT) |
| bluf | shared | Short messages - Slack, email, PR comments - that lead with the answer or the ask (vendored, MIT) |
| exec-summary | shared | Explain a decision, incident or proposal to a busy decision-maker in 60 seconds (vendored, MIT) |
| executive-communication | shared | High-stakes communication for executive reviews, board meetings and strategic decisions (vendored, MIT) |

### Business & career

| Skill | Scope | What it does |
| --- | --- | --- |
| investor-materials | shared | Pitch decks, one-pagers, memos, models and accelerator applications |
| investor-outreach | shared | Cold emails, warm intros, follow-ups and investor update emails |
| ats-optimize | shared | Make a resume survive ATS parsing and match a target job description |

### Extras

Recommended tools that are **not** vendored here because they ship their own installer, are a plugin
or MCP server, or are too large or restrictively licensed to redistribute. They are listed in
`shared/extras.json`; the installer (Extras tab, or `./install.sh skills extras`) shows whether each
is set up for Claude Code and Codex and runs its install command only after a confirmation that
third-party code will run.

| Extra | What it is | Install |
| --- | --- | --- |
| impeccable | Design vocabulary, refinement commands and design checks | `npx impeccable install` |
| figma-mcp | Live Figma canvas and FigJam access for the agent | Claude Code: plugin `figma@claude-plugins-official`; Codex: `codex mcp add figma --url https://mcp.figma.com/mcp`. A disabled `figma` entry is also in `shared/mcp-servers.json` if you prefer the MCP route |
| anthropic-pptx | Anthropic's `pptx` skill: read, create and edit PowerPoint files. Not vendored - its `LICENSE.txt` forbids redistribution | `npx skills add anthropics/skills --skill pptx` |
| ppt-master | Editable `.pptx` decks with native shapes, charts and brand templates (78 MB upstream) | `npx skills add hugohe3/ppt-master` |
| presentation-skill | Codex-native editable `.pptx` builder with layout and accessibility QA (95 MB upstream) | `npx skills add sirilsengolraj-source/presentation-skill` |

## Agents

### Claude Code subagents (32)

| Agent | Purpose |
| --- | --- |
| planner | Implementation planning for complex features and refactors |
| architect | System design, scalability and technical decision-making |
| investigator-code | Read-only codebase investigation for Phase 1, citation-backed |
| investigator-research | External research via web search, library docs and API references |
| investigator-risk | Blast-radius and risk analysis; higher reasoning depth |
| unit-implementer | Executes exactly one minimal implementation unit within its file scope |
| tdd-guide | Enforces write-tests-first and 80%+ coverage |
| code-reviewer | General quality, security and maintainability review |
| security-reviewer | Secrets, injection, auth, SSRF, unsafe crypto, OWASP Top 10 |
| database-reviewer | PostgreSQL query optimization, schema design, performance |
| codex-review-runner | Thin runner for the Codex review pipeline; returns status, not findings (installed only when Codex is on) |
| review-triage | Ranks and de-duplicates review findings for user approval |
| fix-implementer | Applies one user-approved fix when the Codex implement stage is unavailable |
| build-error-resolver | Build and TypeScript errors, minimal diffs |
| cpp-build-resolver / cpp-reviewer | C++ build, CMake and linker fixes; memory safety and modern idiom review |
| go-build-resolver / go-reviewer | Go build and vet fixes; idiomatic Go and concurrency review |
| rust-build-resolver / rust-reviewer | Cargo and borrow-checker fixes; ownership, lifetimes and unsafe review |
| java-build-resolver / java-reviewer | Maven/Gradle fixes; layered architecture, JPA and concurrency review |
| kotlin-build-resolver / kotlin-reviewer | Kotlin/Gradle fixes; coroutine safety, Compose and clean-architecture review |
| python-reviewer | PEP 8, Pythonic idioms, type hints, security and performance |
| e2e-runner | Generates, runs and maintains E2E journeys; quarantines flaky tests |
| refactor-cleaner | Dead code and duplicate removal via knip, depcheck and ts-prune |
| doc-updater | Codemaps, READMEs and guides |
| docs-lookup | Library, framework and API docs through Context7 |
| harness-optimizer | Tunes this harness for reliability, cost and throughput |
| loop-operator | Runs autonomous agent loops and intervenes when they stall |
| chief-of-staff | Multi-channel message triage with drafted replies and follow-through |

### Codex CLI roles (11)

Declared in `codex/config.example.toml` under `[agents.*]`, backed by `codex/agents/*.toml`.

| Role | Purpose |
| --- | --- |
| explorer | Read-only codebase explorer gathering evidence before changes are proposed |
| reviewer | Owner-style review of correctness, security, regressions and missing tests |
| docs_researcher | Verifies APIs, framework behavior and release notes |
| planner | Plans complex features, refactors, risks and phased task breakdowns |
| architect | System design, scalability, integration boundaries and tradeoffs |
| security_reviewer | Secrets, injection, auth, SSRF, unsafe crypto, dependency and data-leak risk |
| tdd_guide | Tests-first feature work and behavior-focused bug fixes |
| build_resolver | Build, typecheck, lint and dependency errors with minimal diffs |
| e2e_runner | Playwright journeys, artifacts and flake triage |
| refactor_cleaner | Dead-code cleanup and consolidation that preserves behavior |
| markdown_writer | Lower-cost writer for Markdown, notes, prompt recipes, AGENTS.md and SKILL.md |

`[agents] max_threads = 6` and `max_depth = 1` bound how much parallelism Codex will take on.

## Commands

57 slash commands in `claude-code/commands/`. Each also exists as a Codex prompt recipe under
`codex/prompts/codex-commands/`, run with `codex-prompt <name>`. Commands that need a tool you do
not have are left out at install time: `/multi-plan`, `/multi-execute` and `/multi-backend` need
Codex, `/multi-frontend` needs Gemini and `/multi-workflow` needs either.

**Orchestration & planning** - `/orchestrate` phased multi-agent pipeline with gates · `/plan`
restate requirements, assess risk, produce a step-by-step plan · `/multi-plan`, `/multi-execute`,
`/multi-workflow`, `/multi-frontend`, `/multi-backend` multi-model collaborative variants ·
`/devfleet` parallel Claude agents in isolated worktrees · `/model-route` pick the model tier ·
`/prompt-optimize` rewrite a draft prompt · `/aside` answer a side question without losing context ·
`/claw` persistent zero-dependency REPL with model routing.

**Review & quality** - `/code-review` general review · `/python-review`, `/go-review`,
`/rust-review`, `/cpp-review`, `/kotlin-review` language-specific reviews · `/quality-gate` block
on unmet quality bars · `/verify` verification loop · `/test-coverage` coverage report and gaps ·
`/refactor-clean` dead code and duplicate cleanup · `/harness-audit` audit this configuration.

**Build & test per language** - `/build-fix` and `/tdd` (generic) · `/go-build` + `/go-test` ·
`/rust-build` + `/rust-test` · `/cpp-build` + `/cpp-test` · `/kotlin-build` + `/kotlin-test` ·
`/gradle-build` Android and KMP builds · `/e2e` Playwright journeys · `/eval` run the eval harness.

**Sessions & learning** - `/save-session`, `/resume-session`, `/sessions`, `/checkpoint` ·
`/learn` and `/learn-eval` extract reusable patterns from a session · `/instinct-status`,
`/instinct-export`, `/instinct-import`, `/promote`, `/evolve`, `/projects` manage learned instincts ·
`/skill-create`, `/skill-health` author and audit skills · `/loop-start`, `/loop-status`
autonomous loops.

**Docs & misc** - `/docs` Context7 lookup · `/update-docs`, `/update-codemaps` · `/setup-pm`
choose a package manager · `/pm2` PM2 process setup.

## Hooks

`claude-code/hooks/hooks.json` wires 21 hook entries across `PreToolUse`, `PostToolUse`,
`PreCompact`, `SessionStart`, `Stop` and `SessionEnd`, implemented by 25 scripts in
`claude-code/scripts/hooks/` (auto-format, typecheck, console-log guard, dev-server block,
git-push reminder, cost tracking, session markers, compaction suggestions, quality gate).
Codex has its own wiring in `codex/hooks.json`. How many hooks run is set by
`guardrails.hook_profile` (`minimal` / `standard` / `strict`) and `guardrails.disabled_hooks` in the
central config, which become `ECC_HOOK_PROFILE` and `ECC_DISABLED_HOOKS` in `~/.claude/settings.json`
(written when that file is first created from the example; `./install.sh skills settings-sync`
pushes a later change into the existing file).
Full detail: [docs/hooks-and-automation.md](docs/hooks-and-automation.md).

## Keeping it in sync

Change the source - `shared/RULES.md` in the repo, or `~/.agents/config.json` and `~/.agents/LOCAL.md`
on the machine - never the rendered copies (`~/.agents/RULES.md` is overwritten on every install),
then re-render:

```bash
./install.sh --auto                  # re-render and install after editing RULES.md or config.json
~/.agents/bin/sync-agents            # MCP servers into both tools (skips "enabled": false entries)
~/.agents/bin/sync-agents rules      # refresh the shared-rules and local-rules blocks in ~/.codex/AGENTS.md
~/.agents/bin/sync-agents status     # table of server -> in Claude? in Codex? (or disabled)
~/.agents/bin/sync-agents mcp --dry-run
./install.sh skills settings-sync    # push the hook profile and Codex subagent settings into the existing settings.json / config.toml
```

`~/.claude/settings.json` and `~/.codex/config.toml` are created once and are yours afterwards, so a
later change to `guardrails.hook_profile`, `guardrails.disabled_hooks` or `subagents.codex.*` does not
reach them by itself. `./install.sh skills settings-sync` copies those settings across (it shows the
diff and asks first; `--dry-run` only shows it), and `./install.sh skills apply` - the Settings tab's
`A` - installs and then pushes just the values you changed from the defaults.

Skills need no sync step at all: they are symlinked out of `~/.agents/skills` into both tools, so
an edit is live immediately. Claude Code imports `~/.agents/RULES.md` and `~/.agents/LOCAL.md`
directly from `~/.claude/CLAUDE.md`; Codex cannot import, so `sync-agents rules` copies both files
into the marked blocks in `~/.codex/AGENTS.md`.
Full detail: [docs/layout-and-sync.md](docs/layout-and-sync.md).

## Acknowledgements

- Much of the base content here derives from **Everything Claude Code (ECC)** by
  [Affaan Mustafa](https://github.com/affaan-m/everything-claude-code) (MIT) - the skill, agent,
  command and rule scaffolding, the hook library and the `ecc` toolkit all trace back to it.
- `codex/scripts/codex-companion-runtime` vendors **OpenAI's Codex plugin** (Apache-2.0); its
  `LICENSE` and `NOTICE` are preserved in place.
- Vendored skills keep their upstream license file in their own folder, and their provenance
  (repo, path, folder hash, install date) is pinned in `shared/skill-lock.json`:
  - `frontend-design` from [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0)
  - `userflow` and the fifteen `flow-*` skills from
    [jpoindexter/ux-flow-skills](https://github.com/jpoindexter/ux-flow-skills) (MIT)
  - `information-architecture` from
    [rampstackco/claude-skills](https://github.com/rampstackco/claude-skills) (MIT)
  - `slide-deck`, `minto-pyramid`, `bluf` and `exec-summary` from
    [patrick204nqh/skills](https://github.com/patrick204nqh/skills) (MIT)
  - `executive-communication` from
    [refoundai/lenny-skills](https://github.com/refoundai/lenny-skills) (MIT)
- The [extras](#extras) belong to their authors and are installed from their own sources on request:
  Impeccable, the Figma MCP server and plugin, Anthropic's `pptx` skill,
  [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master) and
  [sirilsengolraj-source/presentation-skill](https://github.com/sirilsengolraj-source/presentation-skill).

## License

MIT. See [LICENSE](LICENSE).
