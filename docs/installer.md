# The installer

`./install.sh` is the front door to this repo. On a terminal it opens an interactive installer
(a curses program, no dependencies beyond Python's standard library) that can browse and install
skills, edit one central configuration file, check for upstream updates, open your config files
in your editor, compose installed skills into phased workflows and run the full install. The same engine is available without a screen as
`./install.sh skills <command>`, which is `python3 -m installer <command>`.

Two rules hold everywhere:

- **Nothing is ever deleted.** Anything the installer replaces, retires or updates is moved under
  `~/.agents/backups/<label>-<timestamp>/` first. Read [Backups and recovery](#backups-and-recovery).
- **An installed skill is never overwritten silently.** `install` only creates; `update` is a
  separate, explicit action that backs the old copy up before replacing it.

Contents: [Requirements](#requirements) · [Launching](#launching) ·
[What is yours, what is rendered](#what-is-yours-and-what-is-rendered) ·
[The interactive installer](#the-interactive-installer) · [Headless commands](#headless-commands) ·
[Central configuration](#central-configuration) · [Rendering](#rendering) · [LOCAL.md](#localmd) ·
[Extras](#extras) · [Workflows](#workflows) · [Backups and recovery](#backups-and-recovery) ·
[Troubleshooting](#troubleshooting)

---

## Requirements

| Need | For | Notes |
| --- | --- | --- |
| bash and coreutils | `install.sh` | macOS and Linux |
| Python 3.9 or newer | the interactive installer, `skills`, template rendering and `--auto` | standard library only, nothing to `pip install` |
| any `python3` | the plain headless copy (`--all`, `--shared`, ...) | path helpers only; below 3.9 the repo files are installed unrendered, with a warning |
| the `curses` module | the interactive installer | ships with python.org, Homebrew and distro Pythons |
| a terminal of at least 80x24 | the interactive installer | smaller terminals show "terminal too small (need 80x24)" |
| `git` (optional) | the Updates tab and `updates` / `pull` | without it the rest works and the Updates tab tells you how to install it |
| Python 3.11 or newer (separate) | `~/.agents/bin/sync-agents` | it uses `tomllib`; it runs under its own `python3` shebang, not `INSTALLER_PYTHON` |

`install.sh` searches for a usable interpreter in this order: `$INSTALLER_PYTHON`, `python3`,
`python3.13` down to `python3.9`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`,
`/usr/bin/python3`. The first one that is 3.9+ (and, for the interactive installer, can
`import curses`) wins. See [Troubleshooting](#troubleshooting) if none qualifies.

The Python package lives in `installer/`. Its design contract is
[`installer/ARCHITECTURE.md`](../installer/ARCHITECTURE.md); its tests run with
`python3 -m unittest discover -s installer/tests -t .`.

---

## Launching

| Command | What happens |
| --- | --- |
| `./install.sh` on a terminal | Prints one line and opens the interactive installer. If it cannot start it prints why plus the usage text and exits 1 **without installing anything** |
| `./install.sh --tui` | Same, but an error if it cannot start. Cannot be combined with any other option |
| `./install.sh` with no terminal | The headless install of everything (this is what a pipe or a CI job gets) |
| `./install.sh --headless` | The headless install of everything, even on a terminal |
| `./install.sh --all` / `--shared` / `--claude` / `--codex` | Headless install of the named sections (`--all` is all three, in order shared, claude, codex) |
| `./install.sh --auto` | Headless install of the sections `python3 -m installer sections` prints: `shared` plus each tool that your config resolves to on. This is what the Settings tab's Apply and `python3 -m installer apply` run. Cannot be combined with `--shared`, `--claude`, `--codex`, `--all` or `--tui` |
| `--dry-run` | Print what would happen and change nothing (works with every headless form) |
| `--force` | Also replace the files that are yours once installed (see below); the old copies are backed up first |
| `./install.sh skills <command>` | Forward to `python3 -m installer <command>`. `skills` must be the first argument |
| `python3 -m installer` | Opens the interactive installer when stdin is a terminal, otherwise prints `status` |

Environment variables:

| Variable | Effect |
| --- | --- |
| `INSTALLER_PYTHON` | Interpreter to prefer for the interactive installer, `skills`, rendering and `--auto` |
| `AGENTS_HOME`, `CLAUDE_CONFIG_DIR`, `CODEX_HOME` | Relocate `~/.agents`, `~/.claude`, `~/.codex` (the Python package honours them; `install.sh` itself installs under `$HOME`) |
| `INSTALLER_ASCII=1` | Use plain ASCII symbols in the interactive installer instead of Unicode glyphs |
| `INSTALLER_DEBUG=1` | Let a CLI command raise its traceback instead of printing a one-line error |

---

## What is yours and what is rendered

A headless install copies the repo into `$HOME`. Before anything is copied, `shared/`,
`claude-code/` and `codex/` are first rendered into a staging directory (see
[Rendering](#rendering)), and the rendered copies are what get installed. The staging path is
printed at the end of the summary and is never deleted.

| Kind | Files | On re-install |
| --- | --- | --- |
| Managed | `~/.agents/RULES.md`, `mcp-servers.json`, `.skill-lock.json`, `bin/sync-agents`, `~/.agents/skills/`, `~/.claude/{agents,commands,rules,hooks,scripts,skills}/`, `~/.codex/{AGENTS.md,hooks.json,agents,scripts,prompts,workflows,skills}/` | Identical files are skipped; changed files are replaced and the old copy goes to the backup folder |
| Yours | `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, `~/.codex/config.toml`, `~/.agents/config.json`, `~/.agents/LOCAL.md` | Installed from the bundled example **only when absent**. Kept otherwise, with a hint to `diff` against the example. `--force` replaces them (backed up first) |
| Links | `~/.claude/skills/<name>` and `~/.codex/skills/<name>` for each shared skill | Relative symlinks into `~/.agents/skills/<name>`; correct links are left alone, wrong ones are moved to the backup folder |

A directory that is a real directory in a tool's skills folder (one of the 14 platform-specific
pairs) is never replaced by a link; `install.sh` warns and skips it.

---

## The interactive installer

### First run: the setup wizard

When `~/.agents/config.json` does not exist, the installer opens on the **setup wizard**: the
Settings screen walked section by section (Tools, Subagents, Review, Guardrails, Paths,
Editor) with the detected tools shown at the top. `n` / `p` move between sections, `Enter` or
`space` changes the highlighted setting, and the last page is a summary where `s` saves and `A`
applies. `Esc` or `q` leaves without saving. Press `S` on the Overview tab to run the wizard again
at any time.

### Keys that work everywhere

| Key | Action |
| --- | --- |
| `1` .. `9`, `0` | Jump to a tab (`0` is the tenth, Workflows) |
| `Tab` / `Shift-Tab` | Next / previous tab |
| `q` | Back (quits from a top-level tab) |
| `Q` | Quit |
| `?` | Key reference |
| `R` | Re-check tools, git, config and the disk |
| `F` | `git fetch`, then show what changed upstream |

Lists (Skills, Installed, Issues, Updates, Extras) share their movement keys:

| Key | Action |
| --- | --- |
| `j` `k` or arrows | Move |
| `PgUp` `PgDn` | Page |
| `g` `G` | First / last row |
| `space` | Toggle selection of the row |
| `a` / `n` | Select all visible / select none |
| `/` | Filter by text (`Esc` clears) |
| `Enter` | Open the row (viewer, details) |

Symbols: `✓` installed and identical to the repo, `·` in the repo but not installed, `≠` installed
but different from the repo, `?` installed but not in the repo, `↑` changed upstream and not pulled
yet, `!` has a problem or duplicate, `■` selected. With `INSTALLER_ASCII=1` (or a non-UTF-8 locale)
they become `+` `-` `~` `?` `^` `!` `x`.

Every mutating key builds a plan, shows it on a confirm screen (`y` apply, `n` cancel), applies it,
prints a result log with the backup folder, and rescans. An empty plan shows a message instead.
A bad key never crashes the program; errors appear on the message line.

### 1 Overview

A git banner (status, hint, how long ago you last fetched), a "Detected tools" line (`claude`,
`codex`, `git`, `node`, `docker`, `obsidian`, `tmux`, `headroom`, each with a check or a cross), a
table of counts per scope (available, installed, modified, missing, foreign, problems, updates) and
a menu of the other tabs.

| Key | Action |
| --- | --- |
| `S` | Start the setup wizard |
| `c` | Detected tools in full, with install hints for the missing ones that matter |
| `j` `k` | Scroll when the terminal is short |

### 2 Skills

The repo catalog (everything in `shared/skills/`, `claude-code/skills/` and `codex/skills/`),
grouped by scope, with a state per row. Select several and install them in one go.

| Key | Action |
| --- | --- |
| `space` `a` `n` | Select |
| `i` | Install the selected skills (or the current one). Shared skills are copied to `~/.agents/skills/` and linked into both tools' skills folders; platform skills are copied into that tool's folder |
| `u` | Update the selected skills that are modified from the repo copy (the old copy is backed up first) |
| `Enter` | Open the viewer on the repo copy |

### 3 Installed

What is on disk, with its state and, for shared skills, the link state per tool
(`claude ✓ codex !`).

| Key | Action |
| --- | --- |
| `u` | Update a modified skill from the repo (the old copy is backed up first) |
| `r` | Retire: move the skill and its tool links to `~/.agents/backups/retired-skills-<timestamp>/` |
| `x` | Unlink from the tools but keep the shared copy |
| `l` | Relink: repair broken or wrong links; convert an identical real directory into a link (a differing one is never touched) |
| `p` | Push the installed copy back into the repo (a foreign skill becomes a new repo skill; a modified one replaces the repo copy after backing it up) |
| `d` | Diff the repo copy against the installed copy |
| `Enter` | Open the viewer on the installed copy |

Entries the tools manage themselves (`synced`, `learned`, `.system` and anything starting with a
dot) are listed dimmed at the bottom and are never installed, updated, retired or relinked.

### 4 Issues

Everything that needs a decision: duplicates (the same name in `shared/` and a platform tree, a
real directory where a link should be, a name installed for both tools that could be shared),
broken or wrong symlinks, foreign skills, and `SKILL.md` frontmatter problems.

| Key | Action |
| --- | --- |
| `Enter` | Show every problem text for the row |
| `l` / `r` | Relink / retire the row |

### 5 Updates

Needs `git`. Shows the branch, how many commits you are behind the upstream, the commit list, and
which skills changed upstream. When `git` is missing the tab prints the exact install command for
your platform (for example `xcode-select --install` or `brew install git` on macOS) and tells you
to press `R` after installing it; when the folder is not a git checkout it says so and suggests
cloning the repo.

| Key | Action |
| --- | --- |
| `F` | Fetch from the remote |
| `P` | Arm a `git pull --ff-only`: the footer asks, `y` runs it (then the screen rescans), any other key cancels |
| `h` `l` (or arrows, `Tab`) | Switch between the commit list and the changed-skills list |
| `j` `k`, `Enter` | Move; show details for the row |

Pulling updates the repo checkout; it does not touch your installed skills. Use the Installed tab
(`u`) or `./install.sh --auto` afterwards.

### 6 Settings

The typed editor for `~/.agents/config.json`. Rows are grouped by section and the footer shows the
help text for the highlighted row. Edits are held in memory (the title shows `[unsaved]`) until you
save.

| Key | Action |
| --- | --- |
| `Enter` / `space` | Toggle a bool, cycle an enum, or edit text and numbers inline |
| `s` | Save (the previous file is backed up first, then replaced atomically) |
| `A` | Apply: after a `y`, run `python3 -m installer apply --yes` and show the output: `./install.sh --headless --auto`, then the hook profile and Codex subagent settings you changed from the defaults are copied into your existing `settings.json` and `config.toml` (see [settings-sync](#headless-commands)). Only works when a config is saved and nothing is unsaved, because the installer reads the saved file |
| `R` | Reload from disk (asks before discarding unsaved edits) |

Lists (`paths.obsidian_vaults`, `guardrails.disabled_hooks`) open a small list editor: `a` add,
`x` remove, `d` make default (move to the front), and on the vault list `o` imports the vaults from
Obsidian's own registry (`~/Library/Application Support/obsidian/obsidian.json` on macOS,
`$XDG_CONFIG_HOME/obsidian/obsidian.json` or `~/.config/obsidian/obsidian.json` on Linux).
`Esc` or `Enter` closes the list editor. The settings themselves are described in
[Central configuration](#central-configuration).

### 7 Files

The config files the installer manages, in one list.

| Row | Kind | Note |
| --- | --- | --- |
| `~/.claude/CLAUDE.md` | yours | Installed once from the example; never overwritten |
| `~/.agents/LOCAL.md` | yours | Your personal rules; imported by Claude Code and synced into Codex |
| `~/.agents/config.json` | yours | The central config; the Settings tab edits it |
| `~/.codex/AGENTS.md` | synced | The shared-rules and local-rules blocks are regenerated by `sync-agents rules` |
| `~/.claude/settings.json` | yours | Installed once from the example |
| `~/.codex/config.toml` | yours | Installed once from the example |
| `~/.agents/RULES.md` | rendered | Overwritten on every install: edit `shared/RULES.md` in the repo instead |

| Key | Action |
| --- | --- |
| `Enter` / `e` | Open in your editor (the terminal UI suspends and comes back) |
| `v` | View in the terminal UI |
| `d` | Diff against the repo source, rendered with your current config, so you see what the installer would write |
| `c` | Create from the bundled example when the file is missing |

The editor is the `editor` setting, else `$VISUAL`, then `$EDITOR`, then the first of `nano`,
`vim`, `vi` on `PATH`.

### 8 Install

Runs the repo's `install.sh` from inside the program. Sections are pre-selected the same way
`python3 -m installer sections` chooses them (shared always, plus each tool your config resolves to
on); toggle them yourself with the keys below.

| Key | Action |
| --- | --- |
| `s` `c` `x` | Toggle shared / claude / codex |
| `D` | Dry run: `./install.sh --headless <sections> --dry-run`, output in a scrollable pane |
| `A` | Install for real, after a `y` |

Output panes scroll with the arrow keys and `PgUp` / `PgDn`; `k` stops a running command (it asks
first) and `q` closes the pane when it has finished.

### 9 Extras

External integrations that are not skills (see [Extras](#extras)): one row per extra with a
check or a cross per tool.

| Key | Action |
| --- | --- |
| `Enter` | Details: title, URL, the exact commands and the after-install note |
| `i` | Install for the tools that are on. A confirm screen first states that **third-party code will run** and lists the exact commands; `y` starts them, `n`, `q` or `Esc` cancels |
| `o` | Show the URL on the message line |

Commands run one after another, never through a shell, each in its own output pane; `q` on a
finished pane moves on to the next command, and a command that exits non-zero drops the rest.

### 0 Workflows

The tenth tab (press `0`). One row per workflow installed under `~/.agents/skills`, with its phase
and skill counts and whether it validates; `Enter` opens the editor. Keys and the editor are
described under [Workflows](#workflows).

### The viewer

`Enter` on a skill opens the viewer: a file tree on the left, the selected file on the right.

| Key | Action |
| --- | --- |
| `j` `k` / `Enter` `l` / `h` | Tree: move / expand or open / collapse (or go to the parent) |
| `J` `K` or `PgUp` `PgDn` | Scroll the file text |
| `h` `l` | With the text focused: pan left / right |
| `Tab` | Switch focus between tree and text |
| `d` | Show the diff when the skill is modified |
| `q` or `Esc` | Close |

Diffs and the per-row problem text on the Issues tab open in a small read-only pager: `j` `k` and
`PgUp` `PgDn` scroll, `h` `l` pan, `g` `G` jump to the top or bottom, `q` closes.

Files are decoded as UTF-8 with replacement characters; anything over 2 MB shows its first 2 MB, and a
binary file shows a one-line notice instead of its bytes.

---

## Headless commands

Everything the interactive installer does is also a command. The two spellings are identical:

```bash
./install.sh skills status
python3 -m installer status
```

Global options, accepted before or after the command: `--repo PATH` (the checkout to read skills
from, default this one), `--home PATH` (treat `PATH` as `$HOME`; handy for trying things in a scratch
directory) and `--version`.

Mutating commands print their plan and ask `Proceed? [y/N]`. `-y` / `--yes` skips the question;
`--dry-run` prints the plan and stops. With a non-terminal stdin and no `-y` they abort. `--scope
shared|claude|codex` picks between scopes when a name exists in more than one; without it, a name
that exists in exactly one scope is used and an ambiguous one exits 2 listing the candidates.

Exit codes: `0` ok, `1` failure, `2` usage error, `3` file excluded by a requirement (`render`).

| Command | What it does | Example |
| --- | --- | --- |
| `status [--scope S] [--category C] [--json]` | Table of every skill: state, link state, upstream changes | `./install.sh skills status --scope shared` |
| `list [--scope S] [--category C] [--json]` | Skills available in the repo with a category and an installed marker | `./install.sh skills list --category "Design & UX"` |
| `categories [--json]` | Every category with how many skills the repo offers and how many are installed | `./install.sh skills categories` |
| `issues [--json]` | Duplicates, broken links, foreign entries, bad frontmatter | `./install.sh skills issues` |
| `install NAME... [--scope S] [-y] [--dry-run]` | Install skills; never overwrites | `./install.sh skills install flow-auth flow-forms --dry-run` |
| `update NAME... [--scope S] [-y] [--dry-run]` | Replace a modified installed skill with the repo copy, backing it up | `./install.sh skills update frontend-design` |
| `retire NAME... [--scope S] [-y] [--dry-run] [--consumers-only]` | Move a skill and its tool links into a backup; `--consumers-only` unlinks from the tools and keeps the shared copy | `./install.sh skills retire bun-runtime --consumers-only` |
| `relink [NAME...] [-y] [--dry-run]` | Repair claude/codex links to shared skills (all of them when no name is given) | `./install.sh skills relink` |
| `push NAME... [--scope S] [-y] [--dry-run]` | Copy an installed skill back into the repo | `./install.sh skills push my-skill` |
| `tree NAME [--scope S]` | File tree of one skill | `./install.sh skills tree skill-forge` |
| `show NAME [FILE] [--scope S]` | Print a file of one skill (default `SKILL.md`) | `./install.sh skills show skill-forge references/question-bank.md` |
| `updates [--fetch]` | Git banner, commits behind, skills changed upstream | `./install.sh skills updates --fetch` |
| `pull [-y] [--dry-run]` | `git pull --ff-only` in the repo | `./install.sh skills pull` |
| `caps [--json]` | Which tools were detected, with versions | `./install.sh skills caps` |
| `sections` | Which of `shared`, `claude`, `codex` to install, given your config and the detected tools | `./install.sh skills sections` |
| `config list [--json]` | Every setting and its value | `./install.sh skills config list` |
| `config get KEY` | One value | `./install.sh skills config get tools.codex` |
| `config set KEY VALUE [-y]` | Change one value (validated; the previous file is backed up) | `./install.sh skills config set guardrails.hook_profile strict` |
| `config reset KEY [-y]` | Restore one value to its default | `./install.sh skills config reset editor` |
| `config path` | Print the config file path | `./install.sh skills config path` |
| `config edit` | Open the config file in your editor | `./install.sh skills config edit` |
| `edit TARGET` | Open one managed file in your editor. `TARGET` is `claude`, `local`, `config`, `agents`, `settings`, `codex-config` or `rules` | `./install.sh skills edit local` |
| `render FILE` | Print one repo file as it would be installed (exit 3 and a message when a requirement excludes it) | `./install.sh skills render shared/RULES.md` |
| `render-tree SRC OUT --rel REL [--json]` | Mirror a repo directory into `OUT` (which must not exist), rendered | `./install.sh skills render-tree shared /tmp/out/shared --rel shared` |
| `tui` | Open the interactive installer | `./install.sh skills tui` |
| `apply [-y] [--dry-run]` | Run `./install.sh --headless --auto` from the repo root, then copy the hook profile and Codex subagent settings you changed from the defaults into the existing `settings.json` / `config.toml` (nothing is pushed when no config was saved before the run; values still at their default are left alone) | `./install.sh skills apply --dry-run` |
| `settings-sync [-y] [--dry-run]` | Copy `guardrails.hook_profile`, `guardrails.disabled_hooks` and `subagents.codex.*` from `~/.agents/config.json` into the existing `~/.claude/settings.json` and `~/.codex/config.toml`. Prints the diff and asks first; only those keys change and each file is backed up | `./install.sh skills settings-sync --dry-run` |
| `doctor` | Check Python, curses, git, paths, config validity, `settings.json` warnings and tools; exits 1 only on a blocker | `./install.sh skills doctor` |
| `extras list [--json]` | Known extras and whether each is set up, per tool | `./install.sh skills extras list` |
| `extras show NAME` | Details and the install commands | `./install.sh skills extras show figma-mcp` |
| `extras install NAME [--tool claude\|codex] [-y] [--dry-run]` | Run an extra's install commands (third-party code; asks first) | `./install.sh skills extras install impeccable --dry-run` |
| `workflow ACTION` | Compose, save, retire and push workflows: `list`, `show`, `render`, `example`, `save`, `retire`, `push` (see [Workflows](#workflows)) | `./install.sh skills workflow list` |

`--json` output is meant for scripts; the table output uses plain text and degrades to ASCII
symbols when the locale is not UTF-8.

### Categories

Every skill belongs to one category, listed in `shared/skill-categories.json` (read from the repo
and installed nowhere): `{"order": [...], "categories": {"<skill name>": "<category>"}}`. `order` is
the display order and always ends up containing `Other`, the category of any unmapped name. A
Claude/Codex variant pair shares one entry. A missing or invalid file is not an error: every skill
is then `Other`.

- `status --json` and `list --json` rows carry a `"category"` string; `list` also prints a CATEGORY
  column. `status`, `list` and `categories` are the only commands that know about categories;
  `install` and the other mutating commands still take skill names.
- `--category NAME` keeps only the skills in that category. The match is case-insensitive and exact
  (`--category "design & ux"`); an unknown name exits 2 and lists the valid ones. In `status` the
  summary line counts only the rows that survived the filter.
- `categories` prints each category in `order` with `OFFERED` (distinct skill names in the repo) and
  `INSTALLED` (those present on disk, unmodified or modified, in at least one scope). `--json` gives
  `[{"category", "offered", "installed"}]`.

A new skill needs an entry in the file; `installer/tests/test_categories.py` fails when a skill
directory has none, or when an entry names a skill that no longer exists.

---

## Central configuration

One file, `~/.agents/config.json`, drives everything that adapts to your machine. It is created
from [`shared/config.example.json`](../shared/config.example.json) the first time you install
(only when absent) and is yours afterwards. Edit it in the Settings tab, with
`./install.sh skills config set <key> <value>`, or by hand. A missing key falls back to its
default, unknown keys survive a save, and invalid JSON falls back to defaults with an error shown
by `doctor`.

Settings are applied at install time: after changing one, run `./install.sh --auto` (or press `A`
in the Settings tab) so the rendered files are regenerated.

| Key | Type | Default | Effect |
| --- | --- | --- | --- |
| `tools.claude` | `auto` / `on` / `off` | `auto` | `auto` uses Claude Code when its CLI is detected; `on` / `off` forces it. Decides whether the `claude` section is installed and whether Claude-specific lines appear in the generated rules |
| `tools.codex` | `auto` / `on` / `off` | `auto` | Same for Codex. When Codex is off, Codex-only agents, commands and the review pipeline are left out (see [Rendering](#rendering)) |
| `subagents.claude.heavy` | text | `opus` | Model for heavy-tier subagents; replaces `model: opus` in `claude-code/agents/*.md` and appears in the routing text |
| `subagents.claude.light` | text | `sonnet` | Same for `model: sonnet` |
| `subagents.claude.trivial` | text | `haiku` | Same for `model: haiku` |
| `subagents.codex.model` | text | `gpt-5.6-sol` | The one model Codex subagents run on (`model` in `codex/agents/*.toml` and the top of `config.toml`) |
| `subagents.codex.heavy` | `minimal` `low` `medium` `high` `xhigh` `max` | `xhigh` | `model_reasoning_effort` for roles that were heavy (`high`, `xhigh`, `max`) |
| `subagents.codex.light` | same choices | `medium` | `model_reasoning_effort` for roles that were light (`medium`) |
| `subagents.codex.trivial` | same choices | `low` | `model_reasoning_effort` for roles that were trivial (`low`, `minimal`) |
| `subagents.codex.max_threads` | whole number, at least 1 | `6` | `[agents] max_threads` in the example `config.toml`: how many Codex subagents run in parallel |
| `subagents.codex.max_depth` | whole number | `1` | `[agents] max_depth`: how deep subagents may spawn subagents |
| `review.adversarial` | `auto` / `codex` / `claude` | `auto` | Who runs Phase 3 of `/orchestrate`. `auto` means Codex when Codex is on, else Claude |
| `guardrails.never_delete` | bool | `true` | `true` renders the hard "never run `rm`" rule in section E of the rules; `false` renders a softer "prefer `mv`, `rm` only on an explicit request this session" rule |
| `guardrails.context_budget_tokens` | whole number, at least 1 | `100000` | The subagent context cap quoted in section D (shown as `100k`) |
| `guardrails.preflight_checklist` | bool | `true` | Keeps the session pre-flight checklist in section A; `false` replaces it with a note that it is disabled |
| `guardrails.plan_approval_gate` | bool | `true` | Gate A of `/orchestrate`: pause for plan approval. `false` logs the plan as the plan of record and proceeds |
| `guardrails.fix_approval_gate` | bool | `true` | Gate C of `/orchestrate`: approve each review fix. `false` treats `confirmed` findings as approved by default and logs that list; `needs-human` findings still wait for an answer |
| `guardrails.hook_profile` | `minimal` / `standard` / `strict` | `standard` | Written to `env.ECC_HOOK_PROFILE` in the example `~/.claude/settings.json` |
| `guardrails.disabled_hooks` | list of hook ids | `[]` | Written comma-joined to `env.ECC_DISABLED_HOOKS`, for example `pre:bash:tmux-reminder` |
| `paths.obsidian_vaults` | list of paths | `[]` | Vault directories; the first is the default. Listed in the generated section F that the Obsidian skills point at |
| `paths.sessions_dir` | path | `~/.claude/sessions` | Where saved session files live (shown in section F) |
| `paths.backups_dir` | path | `~/.agents/backups` | Recorded in section F so agents know where backups live. The installer's own backups always go under `~/.agents/backups` |
| `editor` | text | `""` | Editor command; empty means `$VISUAL`, then `$EDITOR`, then `nano`, `vim` or `vi` |

The file also carries a `version` (currently `1`) and a `_comment`; neither is a setting.

### What adapts to the machine

`python3 -m installer caps` probes `claude`, `codex`, `gemini`, `git`, `gh`, `node`, `nvm`,
`docker`, `python`, `uv`, `bun`, `deno`, `go`, `cargo`, `obsidian`, `tmux`, `headroom` and
`shellcheck` (binary on `PATH`, version, Docker daemon state, nvm node versions, Obsidian CLI or
app or vault registry). No probe can fail the installer: a broken one just reads as missing.

Together with your config, the probe decides:

- Which sections `--auto` installs, and which tools' lines appear in the generated rules.
- The Docker line, the Node and nvm versions, and the whole of section F in `~/.agents/RULES.md`.
- Which Codex-only and Gemini-only agents, commands and scripts are included.
- Whether Headroom entries stay in the example settings, config and MCP files.
- Which models and reasoning efforts the agent definitions carry.

---

## Rendering

Most repo files are copied as they are. Three kinds of marker and a short list of path rules
change that. Nothing in a file without a marker is ever interpreted, so `{{ }}` examples inside a
skill (Jinja, Django, Helm) are safe.

### Template files

A file is a template when a line containing `installer:template` appears in its first five lines;
the marker line is dropped from the output (`<!-- installer:template -->` in Markdown,
`# installer:template` in TOML, shell and YAML frontmatter). Three repo files are templates:

| File | Installed as |
| --- | --- |
| `shared/RULES.md` | `~/.agents/RULES.md` (sections A to E adapt; section F is generated) |
| `claude-code/commands/orchestrate.md` | `~/.claude/commands/orchestrate.md` |
| `codex/AGENTS.md` | `~/.codex/AGENTS.md` (always rendered, even though its marker sits inside the rules block) |

Syntax: `{{ expr }}`, filters `| tilde`, `| k`, `| join(", ")`, `| default("text")`, and
`{% if %} {% elif %} {% else %} {% endif %}` and `{% for x in y %} {% endfor %}` with `loop.index`,
`loop.first`, `loop.last`. Expressions are dotted paths into `config.*`, `caps.*`, `profile.*` and
`env.HOME` / `env.USER`, plus string and integer literals, `not`, `and`, `or`, `==`, `!=` and
parentheses. An unknown path renders as empty and is reported as a warning, never an error;
unbalanced tags stop the render with `<file>:<line>` in the message.

### Requirement markers

A file is skipped entirely when a requirement is not met:

| Marker | Meaning |
| --- | --- |
| `installer:requires codex` | Needs Codex on (all listed names required) |
| `installer:requires gemini` | Needs Gemini detected |
| `installer:requires-any codex gemini` | Needs at least one of them |
| `.installer-requires` file in a directory | The whole directory needs what the file names (`any:` prefix for any-of); the file itself is never installed |

In the repo these exclude `codex-review-runner`, `multi-backend`, `multi-execute` and `multi-plan`
(Codex), `multi-frontend` (Gemini), `multi-workflow` (either) and the whole
`claude-code/scripts/codex-review-pipeline/` directory (Codex). With Codex off,
`/orchestrate` renders its Claude-only review path: Phase 3 runs on Claude reviewers, with no
mention of the Codex runner.

### Rewrite rules

These apply to specific paths without any marker:

| Path | Rewrite |
| --- | --- |
| `claude-code/agents/*.md` | `model: opus` / `sonnet` / `haiku` becomes your configured heavy / light / trivial model |
| `codex/agents/*.toml` | `model` becomes `subagents.codex.model`; `model_reasoning_effort` is mapped by tier (`xhigh` `max` `high` to heavy, `medium` to light, `low` `minimal` to trivial) |
| `codex/config.example.toml` | Top-level `model`, `[agents] max_threads` / `max_depth`; Headroom blocks and `model_provider = "headroom"` are commented out when Headroom is absent |
| `claude-code/settings.example.json` | Sets `env.ECC_HOOK_PROFILE` and `env.ECC_DISABLED_HOOKS`; with Headroom absent drops `env.ANTHROPIC_BASE_URL`, the Headroom hooks and plugin entries; with Codex off drops the Codex plugin entries |
| `codex/hooks.json` | Drops Headroom hooks when Headroom is absent |
| `shared/mcp-servers.json` | Drops the `headroom` server when Headroom is absent; removes `codex` / `claude` from every `targets` list for a tool that is off, and a server whose targets become empty |

The hook-profile and disabled-hooks values reach `~/.claude/settings.json` through the example
file, which is installed only when that file is absent (or with `--force`, which backs the old one
up). To change them on an existing `settings.json`, edit `env.ECC_HOOK_PROFILE` and
`env.ECC_DISABLED_HOOKS` there; `doctor` warns about known problems in that file, and the Files tab
(`d`) shows what the rendered example would contain.

### Checking what will be written

```bash
# one file, as it would be installed (exit 3 if a requirement excludes it)
./install.sh skills render shared/RULES.md
./install.sh skills render claude-code/commands/orchestrate.md

# a whole tree into a scratch directory (OUT must not exist yet)
./install.sh skills render-tree shared "$(mktemp -d)/shared" --rel shared
# rendered 1, copied 222, excluded 0, warnings 0

# the full install plan, rendered, nothing written to $HOME
./install.sh --headless --all --dry-run
```

`install.sh` runs `render-tree` for all three trees on every install. If rendering is impossible
(no Python, or the `installer/` folder is missing) it warns and installs the repo files verbatim.

To preview a different machine, point `--home` at a scratch directory holding a `.agents/config.json`:

```bash
mkdir -p /tmp/scratch-home/.agents
echo '{"tools":{"codex":"off"}}' > /tmp/scratch-home/.agents/config.json
./install.sh skills --home /tmp/scratch-home sections          # shared claude
./install.sh skills --home /tmp/scratch-home render claude-code/agents/codex-review-runner.md   # excluded, exit 3
```

---

## LOCAL.md

`~/.agents/LOCAL.md` holds your own rules, for this machine only. It is created from
[`shared/LOCAL.example.md`](../shared/LOCAL.example.md) only when it does not exist and is never
overwritten (not even by `--auto`; only `--force` replaces it, with a backup).

- Claude Code imports it: `claude-code/CLAUDE.md` contains `@~/.agents/LOCAL.md` right after the
  `@~/.agents/RULES.md` import.
- Codex cannot import, so `~/.agents/bin/sync-agents rules` copies it into `~/.codex/AGENTS.md`
  between `<!-- BEGIN LOCAL RULES (synced from ~/.agents/LOCAL.md) -->` and
  `<!-- END LOCAL RULES -->`, after the shared-rules block. It is skipped silently when `LOCAL.md`
  is absent. `install.sh` runs this sync at the end of the codex section.

Open it with `./install.sh skills edit local` or from the Files tab.

---

## Extras

Some recommended tools are not skills: they ship their own installer, are a plugin or MCP server,
or are too large to vendor into a public mirror. [`shared/extras.json`](../shared/extras.json) lists
them. The installer shows whether each is set up (per tool) and can run its install command, but
**only after a confirmation that says third-party code will run**, and never on its own. Commands
are run without a shell, one at a time, and need `-y` on a non-terminal.

| Extra | What it is | Install command |
| --- | --- | --- |
| `impeccable` | Design vocabulary, refinement commands and design checks ([impeccable.style](https://impeccable.style/docs/)) | `npx impeccable install`, then `/impeccable init` in Claude Code or `$impeccable` in Codex |
| `figma-mcp` | Live Figma canvas and FigJam access | Claude Code: `claude plugin install figma@claude-plugins-official`. Codex: `codex mcp add figma --url https://mcp.figma.com/mcp` |
| `ppt-master` | Editable `.pptx` decks with native shapes, charts and brand templates (about 78 MB upstream) | `npx skills add hugohe3/ppt-master` |
| `presentation-skill` | Codex-native editable `.pptx` builder with layout and accessibility QA (about 95 MB upstream) | `npx skills add sirilsengolraj-source/presentation-skill` |
| `anthropic-pptx` | Anthropic's `pptx` skill: read, create and edit PowerPoint files. Not vendored because its `LICENSE.txt` forbids redistribution | `npx skills add anthropics/skills --skill pptx --agent claude-code` (or `--agent codex`) |

`figma` is also present in `shared/mcp-servers.json` with `"enabled": false`: `sync-agents` skips
disabled servers and `sync-agents status` lists them as `disabled`. Flip that flag if you prefer the
MCP route to the plugin.

```bash
./install.sh skills extras list
./install.sh skills extras show ppt-master
./install.sh skills extras install ppt-master --tool claude --dry-run
```

---

## Workflows

A **workflow** composes skills you already have into a phased, gated procedure and ships as an
ordinary shared skill, so Claude Code and Codex run it like any other. You describe it once - a
name, the phrases that should trigger it, and an ordered list of phases, each naming the skills to
load, the steps to follow, the outputs it must produce and whether to stop for your approval - and
the installer validates the definition and renders the `SKILL.md` for you. The bundled sample,
`research-design-build`, runs research, then design, then build, and stops for approval after
research and after design.

### On disk

```
~/.agents/skills/<name>/
  workflow.json        the definition: the source of truth, edited by the installer
  SKILL.md             rendered from workflow.json; carries an <!-- ai-suite:workflow --> marker
  agents/openai.yaml   rendered Codex display metadata
```

It is a normal shared skill: `~/.claude/skills/<name>` and `~/.codex/skills/<name>` link to it, it
shows up on the Skills and Installed tabs, and retiring it moves it to a backup. Change a workflow
through the Workflows tab, or edit a copy of `workflow.json` and run `workflow save`. Saving again
writes just those three files: a hand edit of `SKILL.md`, or any other file you added to the
directory, stays in the backup folder with the previous copy (`save` lists the extra files first).

A definition **fails validation** (and is not saved) for an invalid name, an empty description, no
phases, two phases with the same name, or a phase with neither skills nor steps. It only **warns**
(and still saves) when a named skill is neither installed nor in the repo catalog.

### The Workflows tab

Press `0`. Rows show the name, phases, distinct skills, validation state and description.

| Key | Action |
| --- | --- |
| `Enter` / `e` | Open the workflow in the editor |
| `n` | New, from a blank definition with one empty phase |
| `N` | New, started from the bundled sample |
| `r` | Retire: move the workflow and its tool links into a backup (after a `y`) |
| `p` | Push it into the repo's `shared/skills` (after a `y`) |
| `v` | View the rendered `SKILL.md` |
| `/` | Filter by name or description (`Esc` clears) |

The **workflow editor** lists the header fields (name, description, triggers as a comma list,
handback) and the ordered phases. The **phase editor** has the name, goal, skills, gate, gate text,
steps and outputs; its skill picker lists installed and catalog skills with their descriptions.

| Key | Action |
| --- | --- |
| `Enter` / `e` | Edit the field under the cursor (inline prompt), or open the phase |
| `a` / `x` | Add a phase after the current one / remove the current phase |
| `J` / `K` | Move the current phase down / up |
| `s` | Validate (errors block, warnings do not), then show the plan and save after a `y` |
| `q` / `Q` | Back / quit; both ask for `y` while changes are unsaved |
| *in the phase editor* | `s` opens the skill picker; `t` or `space` toggles the gate; `a` `x` `J` `K` add, remove and move steps and outputs; every change is already part of the workflow, so `q` just goes back |
| *in the skill picker* | `space` ticks a skill, `/` filters, `a` / `n` tick all shown / none, `Enter` accepts, `q` cancels |

### From the command line

Mutating actions print their plan and ask `Proceed? [y/N]`; `-y` skips the question and `--dry-run`
prints the plan and stops. Validation errors exit 2 with every problem printed; warnings print and
never block. `save` replaces an installed workflow of the same name (its old copy goes to the backup
folder) but refuses a same-named skill that is not a workflow, even with `-y`.

| Command | What it does | Example |
| --- | --- | --- |
| `workflow list [--json]` | Installed workflows with phases, skills and validation state | `./install.sh skills workflow list` |
| `workflow show NAME` | The definition and its validation messages | `./install.sh skills workflow show research-design-build` |
| `workflow render NAME` | Print the `SKILL.md` rendered from the definition | `./install.sh skills workflow render research-design-build` |
| `workflow example [--json]` | Print the sample definition; `--json` is a file you can save and edit | `./install.sh skills workflow example --json > my-workflow.json` |
| `workflow save FILE.json [-y] [--dry-run]` | Validate, render, install under `~/.agents/skills` and link into Claude Code and Codex | `./install.sh skills workflow save my-workflow.json` |
| `workflow retire NAME [-y] [--dry-run]` | Move the workflow and its tool links into a backup | `./install.sh skills workflow retire research-design-build` |
| `workflow push NAME [-y] [--dry-run]` | Copy the installed workflow into the repo's `shared/skills` | `./install.sh skills workflow push research-design-build` |

### Pushing a workflow into the repo

A saved workflow lives only on this machine until you push it. `p` on the tab, or `workflow push
NAME`, copies `~/.agents/skills/<name>/` to `shared/skills/<name>/` in the repo after showing the
plan; a repo copy that already exists is moved to the backup folder first, and the tab leaves a
workflow alone when it is already identical to the repo copy. Then commit it like any other skill: the README
states the number of shared skills, so update that count (`ls shared/skills | wc -l`) and add a
table row in the same commit.

---

## Backups and recovery

Every operation that would remove or replace something moves it instead. Folders are named
`<label>-<YYYYmmdd-HHMMSS>` under `~/.agents/backups/` (or `paths.backups_dir`):

| Label | Created by | Holds |
| --- | --- | --- |
| `ai-suite-install-<stamp>` | `install.sh` | Files and links the install replaced, mirrored by their path under `$HOME` |
| `installer-<stamp>` | skill install, update, relink, push | The copy that was replaced (`<scope>/<name>`) |
| `retired-skills-<stamp>` | skill retire | The retired skill and any tool links (`<scope>/<name>`) |
| `config-<stamp>` | saving `config.json` | The previous `config.json` |

Skill symlinks are moved as symlinks, never by their target. Recovering is a `mv` back, or:

```bash
./install.sh skills install some-skill     # reinstall from the repo
diff -r ~/.agents/backups/<folder>/shared/some-skill ~/.agents/skills/some-skill
```

Nothing cleans these folders up for you. Move old ones out of the way yourself when you no longer
need them.

---

## Troubleshooting

**"git not found" on the Updates tab.** Install git (`xcode-select --install` or `brew install git`
on macOS, `sudo apt install git` on Debian and Ubuntu, `sudo dnf install git` on Fedora,
`winget install Git.Git` on Windows), make sure it is on your `PATH`, then press `R`. Everything
except update checks works without it. If the folder is not a git checkout (you downloaded a zip),
the tab says so; clone the repo to get update checks.

**"cannot start the interactive installer: no Python 3.9+ interpreter found", or "has no curses
module".** Install a newer Python (`brew install python`, `sudo apt install python3`, or from
python.org) and run again. The headless forms (`--all`, `--auto`) still work with any `python3`;
`--tui` and a bare `./install.sh` do not fall back to installing anything.

**Broken `/usr/bin/python3` on macOS.** On a Mac without the Xcode command-line tools,
`/usr/bin/python3` is a stub that opens an install dialog and exits non-zero. `install.sh` treats
such an interpreter as "not usable" and keeps looking, but if the one you want is somewhere unusual,
point at it explicitly:

```bash
INSTALLER_PYTHON=/opt/homebrew/bin/python3 ./install.sh
INSTALLER_PYTHON=~/.pyenv/shims/python3 ./install.sh skills doctor
```

**"terminal too small (need 80x24)".** Enlarge the window; the screen redraws on resize.

**Garbled symbols.** Use a UTF-8 locale or set `INSTALLER_ASCII=1`.

**"templates not rendered (...); installing repo files verbatim".** `install.sh` could not run
`render-tree`. The warning names the reason (no Python 3.9+, missing `installer/`, or a render
error in one tree). Fix it and re-run; the verbatim install leaves `{{ }}` placeholders in
`~/.agents/RULES.md` until you do.

**My edits to `~/.agents/RULES.md` disappeared.** It is rendered on every install. Put personal
rules in `~/.agents/LOCAL.md`, or edit `shared/RULES.md` in the repo.

**My `settings.json` / `config.toml` did not change.** Those files are yours and are only created
when absent. Diff against the rendered example with the Files tab (`d`), or use `--force` to
replace them (the old ones are backed up first).

**`doctor` is the first thing to run.** It checks Python, curses, git, the install paths, the
config file, known `settings.json` problems and the detected tools, and exits 1 only on a blocker:

```bash
./install.sh skills doctor
```

## Inside Claude Code: the ai-suite mod

The same manager is available as a pane inside Claude Code, with Overview, Install, Issues,
Updates, Workflows and Doctor views, a status line entry and the `/ai-suite` and `/skills-check`
commands. It calls this CLI's `--json` commands and nothing else. Install it from a terminal
session with:

```
/plugin install ai-suite --marketplace bhavya091213/ai-suite
```

The full guide, including options, keys, trust notes and troubleshooting, is
[mods/ai-suite/README.md](../mods/ai-suite/README.md).
