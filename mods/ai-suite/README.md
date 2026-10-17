# ai-suite — the skills manager inside Claude Code

`ai-suite` is a [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview): a
plugin that draws its own pane inside Claude Code. It puts this repository's skills manager where
you already work, so you can see which skills are installed, install the ones you are missing,
spot broken links, pull updates from GitHub and apply your configuration without leaving the
session. Every button is one call to the repo's installer CLI (`python3 -m installer ...`), so the
mod can never do more than the installer already does, and nothing it does deletes files: retired
skills move under `~/.agents/backups/`.

```
AI Suite · Skills                         ~/Documents/ai-suite · main · 3 behind
 o Overview   i Install   s Installed   u Updates   t Settings   w Workflows   d Doctor
 57/90 installed · 3 updates · 2 issues

╭──────────────────────────────────────────────────────────────────╮
│ Shared                                   57 of 90 installed       │
│ ████████████████████████████░░░░░░░░░░░░░░░░                      │
│ 57 installed · 6 modified · 26 missing · 0 problems               │
╰──────────────────────────────────────────────────────────────────╯
╭──────────────────────────────────────────────────────────────────╮
│ Needs attention                                                   │
│ 3 skills changed upstream                         [Go to Updates] │
│ 2 broken links                                  [Go to Installed] │
╰──────────────────────────────────────────────────────────────────╯
 [Install 26 missing]  [Check for updates]
```

## Before you start

| You need | How to check |
| --- | --- |
| Claude Code **v2.1.287 or newer** in the terminal (mods are on by default from that version) | `claude --version` in your shell; [update Claude Code](https://code.claude.com/docs/en/setup#update-claude-code) if older |
| Claude Desktop **v2.1.286 or newer** if you use the Code tab | In a local Code-tab session type `/status` and read the **Claude Code** row |
| **Python 3.9 or newer** on your PATH (the installer is pure standard library) | `python3 --version` |
| **git** if you want the Updates view to fetch and pull | `git --version` |
| A copy of this repository (see [How the mod finds the repo](#how-the-mod-finds-the-repo)) | installed for you when you use Option A below |

Mods run in the Claude Code CLI, the Desktop app's Code tab and the VS Code extension. In
`claude -p` and cloud sessions the hooks still run but nothing is drawn, so the pane is only
useful in an interactive session.

## Install

Pick one of the three options. Option A is the one to give to someone else.

### Option A — install from GitHub (recommended)

1. Start Claude Code in a terminal (`claude`) in any folder.
2. At the prompt, type:

   ```
   /plugin install ai-suite --marketplace bhavya091213/ai-suite
   ```

   Claude Code has not seen this marketplace before, so it shows the source it resolved
   (`github:bhavya091213/ai-suite`) and asks **Add marketplace?** Answer `y`.
3. The plugin's details open. Read the **Will install** section (one hooks module, no MCP
   servers), then choose a scope:
   - **Install for you (user scope)** — the mod is available in every project on this machine.
     This is the usual choice.
   - **Install for all collaborators on this repository (project scope)** — turns it on for
     everyone who works in the current repository (they still run the install line once).
   - **Install for you, in this repo only (local scope)**.
4. An options screen appears because the mod declares settings. You can leave every field as it
   is: **Repo path** may stay empty, because Claude Code has just cloned this whole repository to
   `~/.claude/plugins/marketplaces/ai-suite` and the mod looks there. Press Enter to accept.
5. You see `Installed ai-suite. Plugin is now active.` No reload is needed in that session.

Check it loaded: type `/plugin` and look for the dim line `1 mod active · ai-suite` under the
tabs. Then type `/ai-suite` to open the pane.

The same install from your shell, without a session (loads the next time you start Claude Code,
or after `/reload-plugins` in an open session):

```bash
claude plugin install ai-suite --marketplace bhavya091213/ai-suite
```

Add `--scope project` or `--scope local` to change the scope, and
`--config repoPath=~/code/ai-suite` to point the mod at a clone you already have.

### Option B — install from a clone you already have

If you cloned this repository yourself (for example because you also run `./install.sh` from it),
add the clone as a marketplace and install from it. A plugin installed this way is loaded in
place from your clone, so editing the mod and running `/reload-plugins` picks the change up with
no reinstall.

```
/plugin marketplace add ~/code/ai-suite
/plugin install ai-suite@ai-suite
```

Give the path with `~`, `./` or `/` in front: a bare `name/name` is read as a GitHub repository.
With `repoPath` empty the mod uses the clone itself, because the plugin folder's grandparent is
the repository root.

### Option C — load it for one session only (no install)

From the repository root:

```bash
claude --plugin-dir mods/ai-suite
```

This is how to try the mod or work on it: Claude Code watches the folder and reloads the hooks
module when you save a file. In the Desktop app, which has no flag, put the folder in the `env`
block of `~/.claude/settings.json` as `CLAUDE_CODE_PLUGIN_DIRS` (absolute path; several paths
separated by `:`).

### Desktop app and VS Code

- **Desktop app (Code tab)**: the `/plugin install ...` line is not available in the Code tab's
  local session, so install from a terminal session at user scope; the mod then loads in the
  Desktop app too, because both read `~/.claude/settings.json`. In a panel 800 pixels or wider
  the pane docks beside the conversation; in a narrower panel it draws above the prompt box.
  Buttons have hotkeys in the Desktop app only while the pane has keyboard focus.
- **VS Code extension**: type `/plugins` in the prompt box to open **Manage plugins**, add
  `bhavya091213/ai-suite` on the **Marketplaces** tab, then install `ai-suite` from the
  **Plugins** tab. The pane draws in the chat panel from extension version 2.1.299. Buttons have
  no hotkeys there: click a button, or press Enter once it has focus.

## Set it up

The mod has three settings. Claude Code asks for them when you install from a session, and you
can change them at any time:

- In a session: `/plugin configure ai-suite@ai-suite` opens the same dialog.
- Through the config menu: `/config` lists each setting under the plugin's name.
- From your shell at install time: `claude plugin install ai-suite --marketplace bhavya091213/ai-suite --config repoPath=~/code/ai-suite`.

| Setting | Default | What it does |
| --- | --- | --- |
| **Repo path** (`repoPath`) | empty | Your clone of this repository: the folder that holds `install.sh` and `installer/`. `~` and paths relative to the session folder work. Leave it empty to let the mod find the repo on its own (next section). |
| **Python** (`python`) | `python3` | The interpreter the mod runs the installer with. Set it when `python3` on your PATH is older than 3.9 or broken (on some Macs `/usr/bin/python3` is only an Xcode stub): for example `/opt/homebrew/bin/python3.12`. |
| **Open the Skills pane at session start** (`openOnStart`) | on | Opens the pane (without focus) when a session starts. The row above the prompt is shown either way. |
| **Check on start** (`checkOnStart`) | on | When a session starts, read the skill status and the git state in the background (no network access) and show a summary in the status line, such as `skills 57/90 · 3 updates · 2 issues`. Turn it off if you want the mod to stay silent until you open the pane. |

A changed setting reloads the mod with the new values.

### How the mod finds the repo

The mod needs the repository because that is where the installer lives. It looks, in this order,
for a folder that contains both `install.sh` and `installer/`:

1. **Repo path**, when you set it.
2. **The plugin folder's grandparent**, which is the repository root when the mod is loaded from a
   checkout (`claude --plugin-dir mods/ai-suite`, or a marketplace added from a local path).
3. **The marketplace clone** Claude Code keeps at `~/.claude/plugins/marketplaces/ai-suite` after
   a GitHub install (`CLAUDE_CODE_PLUGIN_CACHE_DIR` moves that root; the mod honours it).

If none of them is the repo, the pane says so in its message row and names the folders it tried.
Set **Repo path** to fix it.

Note on the marketplace clone: Claude Code refreshes it when you run `/plugin marketplace update
ai-suite` or when the marketplace auto-updates. The mod's **Pull** button pulls the same clone
with git. Both are fine; prefer the marketplace update if you want Claude Code to stay in charge
of that folder.

## Use it

### What appears on its own

When a session starts, the mod opens the **Skills** pane beside the transcript (without taking
your keyboard) and draws one row above the prompt:

```
Skills · 57/90 installed · 3 updates · 2 issues   [Open]  [Hide]
```

`Open` (key `k`) brings the pane up with focus; `Hide` removes the row for this session. Turn the
automatic pane off with the **Open the Skills pane at session start** option if you prefer the
row alone. In a window too narrow for a side pane the row says so; pressing `Open` still works.

You can also type `/ai-suite` at any time. `/skills` opens the same pane; Claude Code ships a
command of that name, and while this mod is loaded the mod answers it (if the mod's hook ever
fails, the built-in command runs instead).

### Keys

| Key | What it does |
| --- | --- |
| `o` `i` `s` `u` `t` `w` `d` | Switch view: Overview, Install, Installed, Updates, Settings, Workflows, Doctor |
| `y` / `n` | Answer a confirmation card (Yes / Cancel) |
| `‹ Prev` / `Next ›` buttons | Page through a long list (5 cards per page) |
| `k` | Open the pane from the row above the prompt |
| Hotkey shown on a button | Press that button |
| `Ctrl+X` then `Tab` | Give the pane keyboard focus (or click it) |
| `Ctrl+X` then an arrow key | Resize the pane: Left or Up for more room, Right or Down to give it back |
| `Esc` | Return focus to the prompt (the pane stays open) |
| `Ctrl+X` then `X` | Close the pane; `/ai-suite` reopens it |

Hotkeys work while the pane has focus; while you type in the prompt box, keys go to the prompt.

### Views

Every view is a stack of cards with room between them. A skill card shows the name with a scope
badge and a state badge (`✓ installed`, `≠ modified`, `· missing`, `? foreign`, `! problem`),
the description on its own line, and only the buttons that apply to it.

| View | What you see | Buttons |
| --- | --- | --- |
| **Overview** (`o`) | One card per scope (shared / claude / codex) with a progress bar of installed vs offered and the counts; a "Needs attention" card listing updates, issues and missing setup, each with a button that jumps to the right view | **Install N missing**, **Check for updates**, **Set up this machine** (shown until `~/.agents/config.json` exists) |
| **Install** (`i`) | Filter chips (All / Shared / Claude / Codex), a text filter, then cards of the skills you do not have yet | **Install <name>** per card; **Install all** at the bottom (asks first) |
| **Installed** (`s`) | Filter chips (All / Modified / Problems / Foreign / Tool-managed); cards with link dots for shared skills (`claude ● codex ●`) | **Update**, **Relink**, **Retire…**, **Files** |
| **Updates** (`u`) | A git card (branch, upstream, commits behind, last fetch; the install hint when git is missing), the latest commits, and cards for skills changed upstream | **Fetch**, **Pull…**, **Update <name>**, **Update all changed…** |
| **Settings** (`t`) | Cards per section, every choice a dropdown: tools (auto / on / off), Claude model per tier (opus, sonnet, haiku, the dated ids, or Custom…), Codex model and effort per tier, parallelism, review backend, guardrails (never delete, context budget, pre-flight, approval gates, hook profile), default Obsidian vault (from Obsidian's own registry), editor | Each dropdown saves at once; **Apply to this machine…** re-renders and installs; **Reset a setting…**; **Create it with defaults** when no config exists |
| **Workflows** (`w`) | Cards for the workflows built with the installer (phases, skills, valid or not) | **Preview SKILL.md**, **Retire…**, **Push to repo…** |
| **Doctor** (`d`) | The installer's checks (ok / warn / blocker) and the tools it detected with versions | **Refresh** |

### Nothing risky runs on one press

**Retire**, **Pull**, **Apply**, **Install all** and **Update all changed** first show a
confirmation card at the top of the view: the question, one sentence on what happens (and where
the backup goes), then `[y] Yes, …` and `[n] Cancel`. Nothing else is pressed while the card is
up. Nothing runs on a timer,
one command runs at a time, and a failure (non-zero exit, unexpected output, a folder that is not
the repo) shows in the message row and as a toast instead of being thrown.

### `/skills-check` and the status line

`/skills-check` runs the installer's doctor and an `updates --fetch` (this one touches the
network: it is a `git fetch`), then shows one toast, for example
`skills check: doctor ok, 1 warning · 3 commits behind · 1 skill changed upstream`.

With **Check on start** on, every new session reads the local state only (no fetch) and writes
a status line entry such as `skills 57/90 · 3 updates · 2 issues`: installed-or-modified out of
offered, skills with upstream changes, skills with problems. Zero counts are left out, and the
line is empty when everything is in order.

## Keep it updated, turn it off, remove it

- **Get the newest version** (the pane redesign and Settings tab arrived in 0.3.0): in your
  shell run `claude plugin update ai-suite@ai-suite`, then `/reload-plugins` in any open
  session. The Desktop app picks it up on its next local session.
- **Update**: in a session, `/plugin`, open the **Installed** tab (press Tab), select
  `ai-suite` and choose **Update now**; or in your shell `claude plugin update ai-suite@ai-suite`.
  A third-party marketplace like this one has auto-update **off** by default; turn it on from the
  **Marketplaces** tab in `/plugin` (select `ai-suite`, then **Enable auto-update**). After an
  update, run `/reload-plugins` to use the new version in the open session.
- **Turn off for now**: `/plugin`, **Installed** tab, press Space on `ai-suite` (or
  `claude plugin disable ai-suite@ai-suite`). Press Space again to turn it back on.
- **Turn every mod off for one session**: start with `claude --safe-mode`.
- **Remove**: `claude plugin uninstall ai-suite@ai-suite` (add `--scope project` or `--scope
  local` if you installed at that scope). To forget the marketplace too, `/plugin marketplace
  remove ai-suite`, which also uninstalls every plugin you installed from it. The marketplace
  clone under `~/.claude/plugins/marketplaces/` is removed by Claude Code; your own clone of the
  repo and everything the installer put in `~/.agents`, `~/.claude` and `~/.codex` stay.

## Is it safe to install?

A mod runs inside Claude Code with your permissions, so install it only if you trust this
repository. What this one does:

- It runs exactly one program, `<python> -m installer --repo <repo> ...`, as an argument list
  (never through a shell), with the repository as the working directory.
- It reads files only to check that a folder is the repo (`install.sh`, `installer/`).
- It never touches the network itself. The installer does, only when you press **Fetch**,
  **Pull** or run `/skills-check` (a `git fetch`), and when you confirm **Apply config** (which
  runs the repo's `install.sh`).
- It never deletes: the installer moves retired or replaced files under `~/.agents/backups/`.

You can see all of this without running it. Clone the repo and run:

```bash
claude plugin validate mods/ai-suite
```

The `hooks:` line lists the events the mod handles (`session.start`, three `command.run`
hooks and `ui.render{component=Pane}`) and the `calls:` line every method it asks Claude Code
for (`$.command.register`, `$.ui.open`, `$.ui.status`, `$.ui.toast`, `$.process.run`, the
`$.fs` checks and `$.state`). `claude plugin details ai-suite` prints the component inventory of
an installed copy. The source is small: `hooks/register.tsx` is the entry point and the other
files under `hooks/` are listed in [Development](#development).

## Troubleshooting

| What you see | Cause and fix |
| --- | --- |
| `/plugin` shows no `mods active` line, or it does not name `ai-suite` | Your Claude Code is older than v2.1.287, or mods are turned off. Run `claude plugin test` in a folder that holds no mod: `no hooks module to load` means mods can load; `hooks modules are turned off here` means `disableAllHooks` in your settings or your organization's policy blocks them. |
| `/ai-suite` says the command is unknown | The mod did not load. Start with `claude --debug-file ./mod-debug.log` and search the log for `ai-suite`; the line after `not loaded:` gives the reason. In a `--plugin-dir` session the reason is a dim line in the transcript. |
| `/skills` opens Claude Code's own command instead of the pane | Use `/ai-suite`. The built-in name can win on some versions. |
| The message row says a folder "does not look like the ai-suite repo" | Set **Repo path** to your clone (`/plugin configure ai-suite@ai-suite`), or install from GitHub so the marketplace clone exists. |
| `python3: command not found`, or errors about Python 3.9 | Set the **Python** option to a working interpreter, e.g. `/opt/homebrew/bin/python3.12`. |
| The Updates view says git is missing | Install git (macOS: `xcode-select --install` or `brew install git`; Debian/Ubuntu: `sudo apt install git`) and make sure `git` is on your PATH, then press `r`. |
| Hotkeys do nothing | The pane does not have focus: press `Ctrl+X` then `Tab`, or click it. In VS Code there are no hotkeys; click or press Enter on a button. |
| The pane is empty or shows Claude Code's own content | Run with `--debug-file` and search for `ui.render (Pane) refused`; the reason names the element or prop. Please report it with that line. |
| You installed from your shell and nothing changed | Run `/reload-plugins` in the open session, or start a new one. |
| Edits you made to an installed copy do nothing | Claude Code runs the cached copy of the installed version. Develop with `claude --plugin-dir mods/ai-suite`, or bump `version` in `plugin.json` and update. |

More in the official [Troubleshoot a mod](https://code.claude.com/docs/en/plugins/mods/troubleshoot)
and [Troubleshoot plugins](https://code.claude.com/docs/en/plugins/troubleshooting) pages.

## Development

```bash
claude plugin validate mods/ai-suite --strict   # manifest, hooks module, the state it reads and writes
claude plugin test mods/ai-suite                # hooks/*.test.ts; the UI tests run for terminal and desktop
claude --plugin-dir mods/ai-suite               # run it from the checkout; saving a file reloads it
```

When a session loads the mod from this folder, Claude Code writes its type declarations into
`mods/ai-suite/.claude-plugin/types/` (git-ignored) with a `tsconfig.json`, after which
`npx -p typescript@5 tsc -p mods/ai-suite` type-checks it. Without that, keep a tsconfig outside
the repo whose `include` lists Claude Code's `claude-code.d.ts` plus `mods/ai-suite/hooks` and
`mods/ai-suite/types`.

Layout of `hooks/` (every file under 400 lines):

| File | Job |
| --- | --- |
| `register.tsx` | The hooks module: `session.start`, the `command.run` hooks, the `Pane` and `AbovePrompt` render hooks |
| `pane.tsx`, `band.tsx` | The pane shell (header, tabs, status strip) and the row above the prompt |
| `ui.tsx` | Shared pieces: cards, badges, confirm card, error callout, pager, empty state |
| `view_*.tsx` | One module per view (overview, install, installed, updates, settings, workflows, doctor) |
| `presets.ts` | The option lists behind the Settings dropdowns |
| `actions.ts`, `mutations.ts`, `commands.ts` | What each button does, confirmations, the installer commands they run |
| `load.ts`, `parse.ts` | Reading each command into its snapshot and parsing the JSON |
| `state.ts` | Every `$.state` value and its accessors (declared in `types/index.d.ts`) |
| `cli.ts` | Settings, repo resolution, argv, running a command |
| `summary.ts` | Pure helpers: scope counts, status line and band text, paging |
| `testkit.ts` | Canned installer output and a fake world for the tests |

Rules the hooks-module scan enforces: write every API call in full (`$.ui.open`, never
`const ui = $.ui`), pass `$` only as a bare argument to a top-level function declaration, read
and write an atom only in the module that declares it, and give `$.command.register` string
literals.

### CLI contract

Every command is `<python> -m installer --repo <repo> <args...>`. Read commands are parsed as
JSON: `status --json`, `list --json`, `issues --json`, `workflow list --json`,
`updates --json [--fetch]` (`{"git": {...}, "commits": [...], "changed": [...]}`) and
`doctor --json` (`{"checks": [{"name","state","text"}], "blockers": N}`). Mutating commands run
with `--yes` and no `--json`: `install NAME --scope S`, `relink NAME`, `retire NAME --scope S`,
`update NAME --scope S`, `pull`, `apply`. The full CLI is documented in
[docs/installer.md](../../docs/installer.md).

Tested with Claude Code 2.1.302 on macOS. The mods API can change between releases; when the
declarations Claude Code writes for your version disagree with this README, trust them.
