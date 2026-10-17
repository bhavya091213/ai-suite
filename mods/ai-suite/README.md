# ai-suite — the skills manager inside Claude Code

`ai-suite` is a [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview): a
plugin that draws its own pane inside Claude Code. It puts this repository's skills manager where
you already work, so you can see which skills are installed, install the ones you are missing,
spot broken links, pull updates from GitHub and apply your configuration without leaving the
session. Every button is one call to the repo's installer CLI (`python3 -m installer ...`), so the
mod can never do more than the installer already does, and nothing it does deletes files: retired
skills move under `~/.agents/backups/`.

```
┌ Skills ──────────────────────────────────────────────────────────┐
│ o:Overview  i:Install  s:Issues  u:Updates  w:Workflows  d:Doctor │
│ skills 57/90 · 3 updates · 2 issues                               │
│                                                                    │
│ repo   ~/code/ai-suite      main · 3 commits behind origin/main    │
│ shared   installed 57  modified 6   missing 26  problems 0         │
│ claude   installed 13  modified 1   missing 0   problems 1         │
│ codex    installed 13  modified 1   missing 0   problems 2         │
│ [ r: Refresh ]  [ a: Apply config ]                                │
└────────────────────────────────────────────────────────────────────┘
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

### Open the pane

Type `/ai-suite` at the prompt. `/skills` opens the same pane; Claude Code ships a command of
that name, and while this mod is loaded the mod answers it (if the mod's hook ever fails, the
built-in command runs instead). The pane opens beside the transcript with keyboard focus.

### Keys

| Key | What it does |
| --- | --- |
| `o` `i` `s` `u` `w` `d` | Switch view: Overview, Install, Issues, Updates, Workflows, Doctor |
| `r` | Refresh the current view (re-reads the installer's status) |
| `b` / `n` | Previous / next page when a list is longer than the pane |
| Hotkey shown on a button, e.g. `f` | Press that button |
| `Ctrl+X` then `Tab` | Give the pane keyboard focus (or click it) |
| `Ctrl+X` then an arrow key | Resize the pane: Left or Up for more room, Right or Down to give it back |
| `Esc` | Return focus to the prompt (the pane stays open) |
| `Ctrl+X` then `X` | Close the pane; `/ai-suite` reopens it |

Hotkeys work while the pane has focus; while you type in the prompt box, keys go to the prompt.

### Views

| View | What you see | Buttons |
| --- | --- | --- |
| **Overview** (`o`) | Repo path, git line (`main · 3 commits behind origin/main`), and per scope (shared / claude / codex) how many skills are installed, modified, missing and have problems | **Refresh**; **Apply config** (`a`) runs the installer's `apply --yes`: re-renders the rules and agents from `~/.agents/config.json`, installs what your machine has, and syncs hook profile and Codex limits into existing settings files |
| **Install** (`i`) | Every skill the repo offers that is not installed yet, with scope and description | **Install** per row; **Install all missing** (`a`) |
| **Issues** (`s`) | Duplicate copies, broken or wrong symlinks, foreign entries, frontmatter problems | **Relink** per row (fixes the symlink into both tools); **Retire** per row (moves the entry under `~/.agents/backups/retired-skills-<stamp>/`) |
| **Updates** (`u`) | Git banner, commits behind `origin/main`, skills changed upstream; tells you to install git when it is missing | **Fetch** (`f`), **Pull** (`p`, fast-forward only), **Update changed** (`c`: re-installs every modified skill that changed upstream, backing up your copy first) |
| **Workflows** (`w`) | The workflows you built with the installer's workflow maker: phases, skills, valid or not | **Refresh**. The editor itself is in `./install.sh`, tab `0` |
| **Doctor** (`d`) | One row per check: Python, curses, git, config, settings sanity, detected tools; `ok`, `warn` or `blocker` | **Refresh** |

Long lists show `N more` and page with `b` / `n`.

### Nothing risky runs on one press

**Retire**, **Pull**, **Apply config**, **Install all missing** and **Update changed** arm on the
first press: the button's label changes to `Confirm ...` and the message row says what will
happen. The second press runs it. Pressing anything else disarms it. Nothing runs on a timer,
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
| `register.tsx` | The hooks module: `session.start`, the three `command.run` hooks, the `Pane` render hook |
| `actions.ts` | What each button does, the two-press rule, the start check and `/skills-check` |
| `load.ts` | Reading each command into its snapshot, the busy flag |
| `state.ts` | Every `$.state` value and its accessors (declared in `types/index.d.ts`) |
| `cli.ts` | Settings, repo resolution, argv, running a command, parsing JSON |
| `summary.ts` | Pure helpers: scope counts, status line text, paging |
| `views.tsx` | The six views as a pure function of the pane's data |
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

Tested with Claude Code 2.1.301 on macOS. The mods API can change between releases; when the
declarations Claude Code writes for your version disagree with this README, trust them.
