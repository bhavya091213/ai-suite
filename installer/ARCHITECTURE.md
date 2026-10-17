# installer/ - architecture and module contract

Interactive (curses) and scriptable (CLI) installer for the skills in this repo. This file is
the contract every module is written against. Read it before touching anything under
`installer/`.

## Hard constraints

1. **Python 3.9+, standard library only.** No `tomllib`, no `match`, no `X | Y` unions at
   runtime, no `dataclass(slots=...)`. Use `from __future__ import annotations` everywhere.
2. **Never delete.** No `os.remove`, `os.unlink`, `os.rmdir`, `shutil.rmtree`, `rm`. Anything
   that must go away is *moved* under `~/.agents/backups/` (`Paths.backup_root`). A symlink is
   moved as a symlink (`shutil.move` / `os.rename` on the link itself, never on its target).
3. **Never overwrite an installed skill silently.** `install` only creates. `update` is a
   separate, explicit action that backs the existing copy up first.
4. **Immutability.** All value types are frozen dataclasses (`installer/core/types.py`). Build
   new ones with `dataclasses.replace`; never mutate collections that live in them.
5. **Core is terminal-free.** Nothing under `installer/core/` imports `curses`, prints, or reads
   stdin. It returns data; callers render it.
6. **Files stay small.** 200–400 lines typical, 500 max. Functions under 50 lines.
7. **No machine-specific paths in source or docs.** Use `~`, `$HOME`, or `Paths`.
8. **Tool-managed directories are invisible to actions.** `synced`, `learned`, `.system` and any
   dot-prefixed entry are reported as `State.IGNORED` and never installed, updated, retired or
   relinked (`types.IGNORED_DIR_REASONS`).

## Package layout

```
installer/
  __init__.py            version string
  __main__.py            python3 -m installer -> cli.main(argv)
  ARCHITECTURE.md        this file
  cli.py                 argparse front end; `tui` subcommand (default on a TTY) + headless commands
  core/
    types.py             frozen dataclasses + enums (DONE - do not change shapes without updating this file)
    paths.py             Paths: repo/source/install/consumer/backup locations (DONE)
    frontmatter.py       parse_frontmatter(text) -> SkillMeta
    skills.py            scanning: catalog (repo) and installed (disk), digests, file lists
    status.py            merge catalog + installed + git into SkillStatus rows; counts; diff text
    git.py               git detection, fetch, ahead/behind, changed paths, ff-pull
    actions.py           plan_* -> Operation lists; apply(ops) -> OpResult list
    tree.py              TreeNode for a directory; flatten for rendering; ascii/unicode renderers
  tui/
    listmodel.py         ListModel: cursor/scroll/selection/filter over a sequence (pure, testable)
    draw.py              curses helpers: colors, safe_addstr, boxes, list rows, text pane, glyphs
    app.py               App: curses.wrapper entry, screen stack, global keys, rescan/fetch, confirm flow
    screens/
      overview.py        counts per scope, git banner, menu
      browse.py          catalog with multi-select + install
      installed.py       what is on disk; update / retire / relink / push-to-repo / diff
      issues.py          duplicates, broken links, foreign, frontmatter problems
      updates.py         git fetch results, commits behind, changed skills, ff-pull
      viewer.py          skill tree (left) + file contents (right)
      confirm.py         operation list -> y/n -> results log
      fullinstall.py     run ./install.sh --dry-run / --all for rules, agents, commands, hooks
      help.py            key reference
  tests/
    fixtures.py          make_repo / make_home / build / paths_for (DONE)
    test_*.py            unittest modules (run: python3 -m unittest discover -s installer/tests -t .)
```

## core/frontmatter.py

```python
def parse_frontmatter(text: str) -> SkillMeta
def read_meta(skill_dir: str) -> Optional[SkillMeta]   # None when SKILL.md missing/unreadable
```

Rules: frontmatter is the block between a first line `---` and the next line `---`. Keys are
`key: value` at column 0. Values: strip surrounding single/double quotes; a value of `>` or `|`
or an empty value followed by indented lines collects those lines (joined with a space for `>`
and empty, newline for `|`), stopping at the next column-0 key. Unknown keys are kept in
`fields`. No frontmatter -> `SkillMeta(None, None, {})`. Never raises on malformed input.

## core/skills.py

```python
def list_files(root: str) -> Tuple[str, ...]
    # sorted relative paths of regular files under root; skips IGNORED_FILE_NAMES and
    # anything inside IGNORED_DIR_NAMES; follows the root if it is a symlink; never follows
    # symlinked subdirectories (lists the link as a file entry)
def digest(root: str) -> str
    # sha256 over, for each path in list_files order: path + "\0" + sha256(content) + "\n"
def size_of(root: str) -> int
def scan_catalog(paths: Paths) -> Tuple[Dict[Tuple[str, str], SkillSource], Tuple[RepoIssue, ...]]
    # one SkillSource per <source_dir(scope)>/<name>/ that contains SKILL.md.
    # RepoIssue kinds: "missing-skill-md" (a directory without SKILL.md, except `learned`),
    # "missing-frontmatter" (no name or description), "name-mismatch" (frontmatter name != dir),
    # "duplicate-scope" (same name in shared AND claude/codex; one issue per extra scope).
    # Directories named in IGNORED_DIR_REASONS or starting with "." are skipped silently.
def is_valid_name(name: str) -> bool
    # a single path component: non-empty, no os.sep or "/", not "." or "..", not starting
    # with "."; CLI and TUI refuse anything else before planning
def scan_installed(paths: Paths) -> Dict[Tuple[str, str], InstalledSkill]
    # every entry in install_dir(scope) for each scope. kind per os.path.islink/isdir/isfile.
    # Dot-prefixed names and IGNORED_DIR_REASONS names get ignored_reason set and no digest.
    # Symlinks: link_target = os.readlink; resolved = realpath if exists else None;
    #   kind "broken-symlink" when the target is missing; digest computed through the link
    #   when it resolves to a directory.
    # Missing install_dir -> empty mapping (not an error).
```

## core/status.py

```python
def compute(catalog, installed, paths: Paths, remote: Optional[Dict[Tuple[str,str], RemoteChange]] = None,
            repo_issues: Tuple[RepoIssue, ...] = ()) -> Tuple[SkillStatus, ...]
def counts(statuses) -> Tuple[Counts, ...]            # one per scope, in SCOPES order
def diff_text(source: SkillSource, installed: InstalledSkill) -> str
    # unified diff of SKILL.md (repo -> installed) followed by "only in repo:" / "only installed:"
    # file lists; text files only (decode utf-8, errors="replace"); binary files compared by hash
def problems(statuses) -> Tuple[SkillStatus, ...]     # rows with issues, duplicates or link problems
```

State rules, per (scope, name):

| repo | disk | state |
|---|---|---|
| yes | no | NOT_INSTALLED |
| yes | yes, digest equal | INSTALLED |
| yes | yes, digest differs or unreadable | MODIFIED |
| no | yes | FOREIGN |
| any | ignored entry | IGNORED |

Shared rows also carry `links`: one `ConsumerLink` per consumer, with `expected =
paths.expected_link_target(consumer, name)`. `LinkState.OK` when the entry is a symlink whose
realpath equals realpath of `install_dir("shared")/<name>` (absolute or relative target both
count). `REAL_DIR` when a real directory sits there. `WRONG_TARGET` when it is a symlink to
somewhere else that exists. `BROKEN` when a symlink to nothing. `FILE` for a plain file.

`duplicates` (human strings) are added when:
- the repo has the same name in shared and a platform scope (from `RepoIssue` duplicate-scope);
- a consumer has a REAL_DIR for a shared name; say whether its content is identical to the
  shared copy ("identical copy - can be converted to a symlink") or different;
- a name exists as real directories in BOTH consumers and in no other scope of the repo
  (info: "same name installed for both tools - candidate for shared/").

`issues` (human strings) are added for: link problems (one per consumer), broken/wrong
symlinks in platform scopes, kind "file", missing/invalid frontmatter on the installed copy,
frontmatter name mismatch, and every `RepoIssue` for that key.

Rows are ordered: scope in SCOPES order, then name. Consumer-directory entries are attributed
like this, in priority order, so nothing is reported twice:
1. name is in the platform catalog for that consumer (claude/codex) -> a platform row
   (INSTALLED / MODIFIED), whatever the entry's kind;
2. else name is in the shared catalog OR installed under ~/.agents/skills -> the entry is
   described only through the shared row's `links` (OK / REAL_DIR / WRONG_TARGET / BROKEN /
   FILE) and `duplicates`; no separate row;
3. else -> a FOREIGN row in that consumer scope (real dir, stray symlink, broken symlink or
   plain file), with an issue string when it is not a plain directory.
Shared rows always carry `links` for both consumers, even when the shared copy is absent
(then a dangling consumer symlink shows as BROKEN).

## core/git.py

```python
def detect(paths: Paths, env: Optional[Mapping[str, str]] = None, run=subprocess.run) -> GitInfo
def fetch(paths: Paths, run=subprocess.run, timeout: float = 60) -> GitInfo       # git fetch --prune, then detect
def changed_paths(paths: Paths, run=subprocess.run) -> Tuple[str, ...]           # git diff --name-only HEAD...<upstream>
def commits_behind(paths: Paths, run=subprocess.run, limit: int = 50) -> Tuple[str, ...]  # git log --oneline HEAD..<upstream>
def remote_changes(paths: Paths, catalog, run=subprocess.run) -> Dict[Tuple[str, str], RemoteChange]
    # map changed_paths onto catalog keys by prefix "<REPO_SOURCE[scope]>/<name>/"
def pull_ff(paths: Paths, run=subprocess.run, timeout: float = 120) -> Tuple[bool, str]      # git pull --ff-only
def install_hint(platform: str = sys.platform) -> str
```

`detect` semantics: `shutil.which("git")` None -> `available=False`,
`message="git not found on PATH"`, `hint=install_hint()`. The hint names the exact command
per platform: macOS `xcode-select --install` (or `brew install git`), Debian/Ubuntu
`sudo apt install git`, Fedora `sudo dnf install git`, Windows `winget install Git.Git`, and
always ends with "then make sure `git` is on your PATH (or symlink it into ~/.local/bin) and
press R to re-check". Not a repo (`git rev-parse --is-inside-work-tree` fails) ->
`is_repo=False`, hint "this folder is not a git checkout; clone it to get update checks:
`git clone <README url>`". Otherwise fill branch (`rev-parse --abbrev-ref HEAD`), head
(`rev-parse --short HEAD`), upstream (`rev-parse --abbrev-ref @{u}`; None when unset),
ahead/behind (`rev-list --left-right --count HEAD...@{u}`), dirty (`status --porcelain`
non-empty), last_fetch (mtime of `.git/FETCH_HEAD`, resolve `.git` via `rev-parse --git-dir`),
remote_url (`remote get-url origin`, None if absent). `message` examples: "up to date with
origin/main", "3 commits behind origin/main - updates available", "no upstream configured",
"never fetched". Every subprocess call has a timeout and `check=False`; any failure becomes
`error` text, never an exception out of this module.

## core/actions.py

```python
def plan_install(status: SkillStatus, paths: Paths, consumers: Tuple[str, ...] = CONSUMERS) -> Tuple[Operation, ...]
    # NOT_INSTALLED only (else empty). shared: copytree repo->agents + symlink per consumer whose
    # link state is MISSING (OK links: nothing; REAL_DIR/WRONG_TARGET/BROKEN/FILE: skipped with a
    # note op kind "note"? -> NO: return them as issues; plan only what is safe).
    # claude/codex: copytree repo->install_dir(scope).
def plan_update(status, paths, backup_root: str) -> Tuple[Operation, ...]
    # MODIFIED only. backup installed dir -> <backup_root>/<scope>/<name>, then copytree repo copy.
def plan_retire(status, paths, backup_root: str, consumers_only: bool = False) -> Tuple[Operation, ...]
    # move installed entry (dir or symlink) -> <backup_root>/<scope>/<name>; for shared also move
    # each consumer symlink that points at it -> <backup_root>/<consumer>/<name>.
    # consumers_only=True moves just the consumer links (unlink from tools, keep shared copy).
def plan_relink(status, paths, backup_root: str) -> Tuple[Operation, ...]
    # shared only: for each consumer link in BROKEN/WRONG_TARGET/REAL_DIR(identical)/MISSING:
    # backup whatever is there (if anything), then symlink expected target. REAL_DIR with
    # different content is NOT touched (returned as nothing; UI explains).
def plan_push_to_repo(status, paths, backup_root: str) -> Tuple[Operation, ...]
    # copy the installed directory into source_dir(scope)/<name>; when the repo already has one,
    # back it up first. Works for FOREIGN (adds a new skill to the repo) and MODIFIED.
def apply(ops, dry_run: bool = False) -> Tuple[OpResult, ...]
    # executes in order; stops at the first failure; dry_run reports every op as ok "(dry run)".
    # "mkdir": os.makedirs(dst, exist_ok=True)
    # "copytree": shutil.copytree(src, dst, symlinks=True, ignore=<IGNORED names>) - dst must not exist
    # "symlink": os.symlink(src, dst) - dst must not exist; src is the (relative) target string
    # "backup" / "unlink-to-backup": makedirs(dirname(dst)); shutil.move(src, dst)
def describe(op: Operation, paths: Paths) -> str     # one-line, ~-shortened, for confirm screens
```

Backup roots: install/update/relink/push use `paths.backup_root("installer")`; retire uses
`paths.backup_root("retired-skills")`. One root per confirm, shared by all ops in it.

## core/tree.py

```python
@dataclass(frozen=True) class TreeNode: name, path, is_dir, size, children: Tuple[TreeNode, ...], is_link: bool
def build_tree(root: str, max_depth: int = 8) -> TreeNode     # sorted dirs first, ignored names skipped
def flatten(node, expanded: FrozenSet[str]) -> Tuple[Row, ...]  # Row(depth, node, prefix) with box-drawing prefix
def render(node, ascii_only: bool = False) -> Tuple[str, ...]   # classic `tree` output lines
```

## tui/listmodel.py (pure)

```python
class ListModel(Generic[T]):
    items, cursor, offset, selected: FrozenSet[int] (indices into items), query: str
    def with_items(items) -> ListModel; def visible(height) -> slice of filtered rows
    def filtered() -> Tuple[Tuple[int, T], ...]   # (original index, item) where key_fn(item) contains query
    def move(delta, height), page(delta, height), home(height), end(height)
    def toggle(), select_all_visible(), select_none(), set_query(q), current() -> Optional[T]
```
Immutable: every mutator returns a new ListModel. `key_fn` supplied at construction.

## tui/draw.py

Glyphs with ASCII fallback (`use_unicode = locale/encoding is UTF-8` and not
`INSTALLER_ASCII=1`): installed ✓/`+`, not-installed ·/`-`, modified ≠/`~`, foreign ?/`?`,
remote ↑/`^`, problem !/`!`, selected ■/`x`. Color pairs (degrade gracefully when
`curses.has_colors()` is false): 1 title, 2 ok/green, 3 warn/yellow, 4 error/red, 5 selected
row (reverse), 6 dim. `safe_addstr(win, y, x, text, attr=0)` clips to the window and swallows
`curses.error`. `draw_frame(stdscr, title, tabs, active_tab, footer)` draws the chrome used by
every screen. Minimum size 80x24: below it draw only "terminal too small (need 80x24)".

## tui/app.py

- `run(paths: Paths, start_screen: str = "overview") -> int` wraps `curses.wrapper`.
- `App` owns: `paths`, `statuses`, `catalog`, `repo_issues`, `git: GitInfo`, `remote`, a screen
  stack, a transient message line. `App.rescan()` recomputes everything except git fetch.
  `App.refresh_git()` calls `git.detect`; `App.fetch()` calls `git.fetch` then `remote_changes`
  then `rescan()`.
- Global keys (every screen, unless the screen is editing a filter): `q` back (quit on the
  root), `Q` quit, `?` help, `R` rescan, `F` fetch, `1`..`6` jump to a tab, `Tab`/`Shift-Tab`
  next/previous tab. Screen keys: `j/k/↑/↓` move, `PgUp/PgDn`, `g/G`, `space` toggle select,
  `a` select all visible, `n` select none, `/` filter (Esc clears), `Enter` open viewer,
  `i` install, `u` update, `r` retire, `l` relink, `p` push to repo, `d` diff, `x` unlink from
  tools, `P` pull (updates screen), `D` dry-run / `A` apply (full install screen).
- Every mutating key builds a plan with `core.actions`, pushes `ConfirmScreen(plan)`, and on
  `y` applies it, shows results, then `rescan()`. Empty plans show a message instead.
- Resize (`KEY_RESIZE`) just redraws. All exceptions in a key handler are caught and shown on
  the message line; the app never dies on a bad key.

Screens (`screens/*.py`) each implement:

```python
class Screen:
    title: str
    def draw(self, stdscr, app) -> None
    def handle_key(self, key: int, app) -> Optional[str]   # return "pop" to close, "quit" to exit
```

Overview: git banner (3 lines: status line, hint line when relevant, last fetch), a table of
`Counts` per scope, and the menu listing tabs 2–6 with one-line descriptions.
Browse: rows = all statuses with a source (not FOREIGN/IGNORED), grouped by scope, columns:
select box, glyph, scope, name, state, remote marker, description (truncated). `i` installs
selected or current.
Installed: rows = statuses with `installed` set and state != IGNORED, plus IGNORED rows listed
at the bottom dimmed. Columns: glyph, scope, name, kind (dir/link), state, link summary for
shared (`claude ✓ codex !`), description.
Issues: rows = `status.problems(...)` plus repo issues; each row shows the first issue; Enter
shows all issue text in a text pane; `l` relink, `r` retire.
Updates: git banner, commits behind (list), skills with remote changes (list); `F` fetch,
`P` pull --ff-only (confirm), then rescan.
Viewer: header (scope, name, state, description), left pane tree (30 cols, `j/k` move,
`Enter`/`l` expand or open, `h` collapse), right pane file text (`J/K` or `PgUp/PgDn` scroll,
`h/l` horizontal scroll when the pane is focused); `Tab` switches focus; `d` shows diff when
MODIFIED. Text files decoded utf-8 with `errors="replace"`; files over 2 MB show the first 2 MB.
Confirm: numbered operation list, `y` apply / `n` cancel; afterwards the results log with
ok/FAILED per op and the backup root path; any key returns.
Full install: explanation + `D` run `./install.sh --dry-run --all` and `A` run `--all`
(after confirm); output streams into a scrollable pane; sections selectable with `s/c/x`
toggles mapping to `--shared/--claude/--codex`.

## cli.py

```
python3 -m installer                       -> tui when stdin is a TTY, else `status`
python3 -m installer tui
python3 -m installer status  [--scope S] [--json]      table: glyph scope name state links remote
python3 -m installer list    [--scope S] [--json]      catalog (repo) with installed marker
python3 -m installer install NAME... [--scope S] [--dry-run] [--yes]
python3 -m installer update  NAME... [--scope S] [--dry-run] [--yes]
python3 -m installer retire  NAME... [--scope S] [--dry-run] [--yes]
python3 -m installer relink  [NAME...] [--dry-run] [--yes]
python3 -m installer push    NAME... [--scope S] [--dry-run] [--yes]     installed -> repo
python3 -m installer updates [--fetch] [--json]        git banner + commits behind + changed skills
                                                       --json: {git:{message,hint,branch,upstream,ahead,behind,last_fetch},
                                                                commits:["<sha> <subject>"], changed:[{scope,name,files}]}
python3 -m installer pull                              git pull --ff-only
python3 -m installer tree NAME [--scope S]
python3 -m installer show NAME [FILE] [--scope S]      print a file (default SKILL.md)
python3 -m installer issues [--json]
python3 -m installer doctor [--json]                   python, curses, git, paths, dirs - exit 1 on a blocker
                                                       --json: {checks:[{name,state:ok|warn|blocker,text}], blockers:N}
```
Without `--yes` a mutating command prints the plan and asks `Proceed? [y/N]` (reads stdin;
non-TTY stdin without `--yes` aborts with exit 2). `--scope` disambiguates names that exist
in several scopes; without it, a name matching exactly one scope is used, otherwise exit 2
with the candidates listed. Exit codes: 0 ok, 1 failure, 2 usage. `--repo PATH` and
`--home PATH` global options feed `Paths.detect` (tests use them).

## install.sh integration

- No arguments + stdin and stdout are TTYs + a usable python3 => print one line
  (`launching the interactive installer; run ./install.sh --all for the headless install`)
  and `exec` the TUI. `--tui` forces it; `--all`, `--shared`, `--claude`, `--codex`, `--dry-run`,
  `--force` keep today's headless behaviour unchanged; `--headless` is the old no-arg default.
- `./install.sh skills ...` forwards everything after `skills` to `python3 -m installer`.
- Python discovery (`find_python`): try `$INSTALLER_PYTHON`, then `python3`, `python3.13` ..
  `python3.9`, `/opt/homebrew/bin/python3`, `/usr/local/bin/python3`, `/usr/bin/python3`; the
  first that runs `import sys; assert sys.version_info >= (3, 9)` wins. The TUI additionally
  needs `import curses`; if none qualifies, print why and fall back to headless with a hint.
- The headless path still requires python3 only for `resolve`/`relpath` (unchanged).

## Tests

- `python3 -m unittest discover -s installer/tests -t .` from the repo root; also
  collectable by pytest. Each core module gets `test_<module>.py`; fixtures come from
  `installer/tests/fixtures.py` built into `tempfile.mkdtemp()` (clean up with
  `shutil.rmtree`? NO - tests may leave temp dirs; use `tempfile.TemporaryDirectory`, which the
  stdlib removes - that is the one sanctioned deletion, scoped to a temp dir the test created).
- `test_git.py`: skip when `shutil.which("git")` is None; builds a bare "origin" + a clone in a
  temp dir, commits a change on origin, asserts behind=1 and `remote_changes` maps to the skill.
  Simulate "git missing" by passing `env={"PATH": ""}` or a stub `run`.
- `test_actions.py` asserts: install never touches an existing dir; update moves the old copy
  under the backup root; retire moves dir + consumer links; relink fixes BROKEN/WRONG_TARGET and
  converts an identical REAL_DIR; a differing REAL_DIR is left alone; dry_run changes nothing;
  no test ever observes a path disappearing without reappearing under backups.
- `test_tui_smoke.py`: spawn `python3 -m installer tui --repo <fixture> --home <fixture>` in a
  pty (stdlib `pty`), size 100x30 via `TIOCSWINSZ`, send `2`, `j`, `Enter`, `q`, `q`, `Q`;
  assert exit 0 within 10 s. Skip on platforms without `pty`.
- `test_cli.py` runs `cli.main([...])` in-process with `--repo/--home` and captures stdout.

Target: 80%+ line coverage of `installer/core` and `installer/tui/listmodel.py` + `tree.py`.

---

# Part 2 - configuration, capability probing and rendering

The installer is also the setup and configuration manager for the whole mirror. One central
config, one probe of what the machine has, one renderer that turns repo files into the
installed files. Everything below follows the hard constraints of Part 1.

## Additional package layout

```
installer/
  core/
    config.py          Config: defaults, load/save, typed settings schema, get/with_value/validate
    capabilities.py    probe(): which CLIs/tools exist, versions, Obsidian vault registry
    render.py          template engine (opt-in markers), requires markers, build_context, render_text, render_tree
    rewrite.py         path-specific rewrite rules (agent model tiers, codex efforts, JSON/TOML stripping)
    claude_settings.py patch ~/.claude/settings.json env block; doctor warnings
    codex_config.py    patch ~/.codex/config.toml [agents] table and model line (text-level)
    editor.py          resolve the user's editor; run it with curses suspended (helper used by tui)
  tui/screens/
    settings.py        typed settings editor; also drives the first-run wizard (section by section)
    files.py           config files: view in TUI / open in $EDITOR / diff against the repo
    capabilities.py    what was detected, with hints
shared/
  config.example.json  installed to ~/.agents/config.json only when absent (user-owned afterwards)
  LOCAL.example.md     installed to ~/.agents/LOCAL.md only when absent (personal rules, never overwritten)
```

## Central config: ~/.agents/config.json

Repo source `shared/config.example.json`. `core/config.py` holds the same structure as
`DEFAULTS`; the file may omit any key (defaults fill in) and unknown keys are preserved on save.

```json
{
  "_comment": "Central configuration for the ai-suite installer. Edit with ./install.sh (Settings tab) or ./install.sh skills config set <key> <value>. Keys are documented in docs/installer.md.",
  "version": 1,
  "tools": { "claude": "auto", "codex": "auto" },
  "subagents": {
    "claude": { "heavy": "opus", "light": "sonnet", "trivial": "haiku" },
    "codex": { "model": "gpt-5.6-sol", "heavy": "xhigh", "light": "medium", "trivial": "low",
               "max_threads": 6, "max_depth": 1 }
  },
  "review": { "adversarial": "auto" },
  "guardrails": {
    "never_delete": true,
    "context_budget_tokens": 100000,
    "preflight_checklist": true,
    "plan_approval_gate": true,
    "fix_approval_gate": true,
    "hook_profile": "standard",
    "disabled_hooks": []
  },
  "paths": {
    "obsidian_vaults": [],
    "sessions_dir": "~/.claude/sessions",
    "backups_dir": "~/.agents/backups"
  },
  "editor": ""
}
```

Semantics: `tools.*` is `auto` (use it when the CLI is detected), `on` or `off`.
`review.adversarial` is `auto` (Codex when Codex is on, else Claude), `codex` or `claude`.
`subagents.claude.*` are model ids or aliases passed to the Agent tool; `subagents.codex.*` are
`model_reasoning_effort` values. `guardrails.hook_profile` is one of `minimal`, `standard`,
`strict`; `guardrails.disabled_hooks` holds ECC hook ids such as `pre:bash:tmux-reminder`
(these two render into `ECC_HOOK_PROFILE` / `ECC_DISABLED_HOOKS` in `~/.claude/settings.json`).
`paths.obsidian_vaults[0]` is the default vault. `editor` empty means `$VISUAL`, then `$EDITOR`,
then the first of `nano`, `vim`, `vi` on PATH.

### core/config.py

```python
DEFAULTS: Mapping            # the structure above minus _comment
@dataclass(frozen=True)
class Setting: key: str; kind: str; label: str; help: str; section: str; choices: Tuple[str, ...] = ()
    # kind: "bool" | "int" | "str" | "enum" | "pathlist" | "strlist" | "path"
SETTINGS: Tuple[Setting, ...]   # one per leaf key above (tools.claude, ..., editor), in display order
@dataclass(frozen=True)
class Config: data: Mapping; path: str; exists: bool; error: Optional[str] = None
def load(paths: Paths) -> Config            # deep-merge DEFAULTS <- file; bad JSON => defaults + error text
def save(config: Config, paths: Paths) -> str
    # back up an existing file to <paths.backup_root("config")>/config.json (shutil.copy2), then write
    # atomically (temp file in the same dir + os.replace); returns the path written
def get(config: Config, key: str) -> Any       # dotted key; KeyError when unknown
def with_value(config: Config, key: str, value: Any) -> Config   # validates against SETTINGS, returns new Config
def parse_value(setting: Setting, text: str) -> Any   # "true"/"false", ints, comma lists; ValueError on bad input
def validate(config: Config) -> Tuple[str, ...]  # type/enum problems, vault paths that do not exist (warning text)
def to_json(config: Config) -> str               # indent=2, sorted=False, trailing newline
def setting_for(key: str) -> Setting             # KeyError when unknown
```

`Config.data` is immutable to callers: nested dicts are wrapped in `types.MappingProxyType` and
lists become tuples on load; `with_value` rebuilds. `to_json` converts back to plain lists.

### core/capabilities.py

```python
@dataclass(frozen=True)
class Capability: name: str; present: bool; version: Optional[str]; path: Optional[str]; detail: str
@dataclass(frozen=True)
class Capabilities: items: Mapping[str, Capability]; vaults: Tuple[str, ...]; nvm_versions: Tuple[str, ...]
    def get(self, name) -> Capability; def present(self, name) -> bool
PROBES = ("claude", "codex", "gemini", "git", "gh", "node", "nvm", "docker", "python", "uv", "bun",
          "deno", "go", "cargo", "obsidian", "tmux", "headroom", "shellcheck")
def probe(env=None, which=shutil.which, run=subprocess.run, home=None, platform=sys.platform,
          only: Optional[Tuple[str, ...]] = None) -> Capabilities
def obsidian_registry_path(home: str, platform: str, env: Mapping) -> str
    # darwin: ~/Library/Application Support/obsidian/obsidian.json; linux: $XDG_CONFIG_HOME or ~/.config/obsidian/obsidian.json;
    # win32: %APPDATA%/obsidian/obsidian.json
def obsidian_vaults(home, platform, env) -> Tuple[str, ...]   # vault paths from the registry that exist, "open" ones first
def resolve_tool(setting: str, cap: Capability) -> bool          # auto->cap.present, on->True, off->False
def to_context(caps: Capabilities) -> Mapping                     # {"claude": {"present":..,"version":..,"path":..}, ...}
```

Probe details: every binary via `which`; versions via `<bin> --version` / `node -v` /
`python3 --version` with a 5 s timeout, output trimmed to the first line; `docker` detail is
"daemon running" / "installed, daemon not running" (`docker info`, 5 s timeout); `nvm` present when
`~/.nvm/versions/node` exists (versions sorted descending); `headroom` present when on PATH or
`~/.local/bin/headroom` exists; `obsidian` present when the CLI is on PATH or the app exists
(`/Applications/Obsidian.app` on darwin) or the registry file exists, detail says which. No
exception escapes: a failing probe is `present=False` with the error in `detail`.

### core/render.py - template syntax

Rendering is **opt-in per file**: a line containing `installer:template` within the first five
lines turns it on, and that marker line is dropped from the output. (`<!-- installer:template -->`
in Markdown, `# installer:template` in TOML/shell.) `codex/AGENTS.md` is always rendered
(`ALWAYS_TEMPLATE` tuple), because its synced rules block is a copy of the RULES.md template.

```
{{ expr }}                        value; lists joined with ", "; None/missing -> ""
{{ expr | tilde }}                $HOME prefix shown as ~
{{ expr | k }}                    100000 -> "100k"
{{ expr | join(" / ") }}          list join with a custom separator
{{ expr | default("text") }}      fallback when falsy
{% if expr %} ... {% elif expr %} ... {% else %} ... {% endif %}
{% for name in expr %} ... {{ name }} ... {% endfor %}      (loop.index, loop.first, loop.last available)
```

`expr`: dotted paths (`config.tools.codex`, `profile.vaults.0`), string literals in double quotes,
integer literals, `not`, `and`, `or`, `==`, `!=`, parentheses. Python truthiness. An unknown path
evaluates to `None` and is recorded as a warning (never an error). A block tag that is the only
thing on its line consumes the whole line. Unbalanced tags raise `RenderError("<source>:<line>: …")`.
Nothing in a non-template file is ever interpreted, so Jinja/Django examples inside skills are safe.

Requires markers (file is skipped entirely when unmet): a line with
`installer:requires <name> [<name>...]` (all required) or `installer:requires-any <name> ...`
within the first five lines; for a whole directory, a file named `.installer-requires` whose
content is the names, optionally prefixed by `any:`. Names are keys of `profile` (below).
The marker line is dropped from rendered output; `.installer-requires` files are never copied.

Context (`build_context(config, caps, paths, env=None) -> Mapping`):

```
config.*                  the config values
caps.<name>.present / .version / .path / .detail
profile.claude, profile.codex, profile.gemini, profile.docker, profile.tmux, profile.headroom,
profile.obsidian, profile.git, profile.node        booleans (tools.* resolved; others = present)
profile.review_backend    "codex" | "claude"
profile.vaults            tuple of vault paths (config.paths.obsidian_vaults, ~ expanded for existence checks, shown as given)
profile.default_vault     profile.vaults[0] or ""
profile.node_version, profile.nvm_versions, profile.docker_state ("running"|"installed"|"absent")
profile.claude_heavy / claude_light / claude_trivial / codex_model / codex_heavy / codex_light / codex_trivial
profile.context_budget    int;  profile.context_budget_k  e.g. "100k"
profile.sessions_dir, profile.backups_dir, profile.hook_profile, profile.disabled_hooks
env.HOME, env.USER (only those two)
```

```python
class RenderError(Exception)
def is_template(text: str) -> bool
def requires_of(text: str) -> Tuple[Tuple[str, ...], str]       # (names, "all"|"any"); ((), "all") when none
def requirements_met(names, mode, context) -> bool
def render_text(text: str, context: Mapping, source: str = "<text>") -> Tuple[str, Tuple[str, ...]]  # (output, warnings)
@dataclass(frozen=True)
class RenderReport: rendered: Tuple[str, ...]; copied: Tuple[str, ...]; excluded: Tuple[Tuple[str, str], ...]; warnings: Tuple[str, ...]
def render_tree(src_dir: str, out_dir: str, context: Mapping, rel_prefix: str) -> RenderReport
    # mirrors src_dir under out_dir (created; must not already exist): each regular file is read as
    # bytes; if it decodes as UTF-8 it goes through (1) requires check, (2) template render when
    # is_template, (3) rewrite.rewrite(rel_path, text, context); otherwise copied verbatim.
    # rel_path = rel_prefix + "/" + path-within-src (POSIX). Mode bits preserved (shutil.copymode).
    # IGNORED_FILE_NAMES / IGNORED_DIR_NAMES skipped; symlinked directories not followed (copied as links).
```

### core/rewrite.py - path-specific rules (no marker needed)

```python
def rewrite(rel_path: str, text: str, context: Mapping) -> str   # dispatches on rel_path; identity otherwise
```

1. `claude-code/agents/*.md`: in the frontmatter, `model: opus|sonnet|haiku` becomes
   `profile.claude_heavy|claude_light|claude_trivial`. Other values untouched.
2. `codex/agents/*.toml`: `model = "..."` -> `profile.codex_model`; `model_reasoning_effort`
   mapped by tier: `xhigh|max|high` -> heavy, `medium` -> light, `low|minimal` -> trivial.
3. `codex/config.example.toml`: first top-level `model = "..."` -> `profile.codex_model`;
   inside `[agents]`, `max_threads` / `max_depth` -> config values; when `profile.headroom` is
   false, every non-comment line between a `# --- Headroom ... ---` marker and its matching
   `# --- end Headroom ... ---` is commented out with `# ` (markers kept, so re-enabling is
   obvious); also `model_provider = "headroom"` and `openai_base_url` lines are commented out.
4. `claude-code/settings.example.json` (parse JSON, write back indent=2, key order kept):
   always set `env.ECC_HOOK_PROFILE` and, when non-empty, `env.ECC_DISABLED_HOOKS` (comma
   joined; removed when empty); when `profile.headroom` is false drop `env.ANTHROPIC_BASE_URL`,
   every hook whose command contains "headroom" (and then empty matcher groups / event keys),
   `enabledPlugins["headroom@headroom-marketplace"]` and
   `extraKnownMarketplaces["headroom-marketplace"]`; when `profile.codex` is false drop
   `enabledPlugins["codex@openai-codex"]` and `extraKnownMarketplaces["openai-codex"]`.
5. `codex/hooks.json`: when `profile.headroom` is false drop hooks whose command contains
   "headroom" (leaving `{"hooks": {}}` when nothing remains).
6. `shared/mcp-servers.json`: when `profile.headroom` is false drop the `headroom` server; drop
   `"codex"` / `"claude"` from every `targets` list when that tool is off, and the whole server
   when its targets become empty. The `_comment` key is preserved.

Every rule is a pure function of (text, context) and must leave the file valid (JSON parses,
TOML parses on Python 3.11+ via tomllib when available in tests).

### core/claude_settings.py and core/codex_config.py

```python
# claude_settings.py
def patch_env(text: str, updates: Mapping[str, Optional[str]]) -> str   # None removes; creates "env" when absent; preserves everything else; indent=2
def warnings(text: str, context: Mapping) -> Tuple[str, ...]
    # e.g. "env.ANTHROPIC_BASE_URL points at http://127.0.0.1:8787 but headroom is not installed - every request will fail"
# codex_config.py
def patch_agents(text: str, max_threads: int, max_depth: int) -> str   # edits/creates keys inside the [agents] table only
def patch_model(text: str, model: str) -> str                         # first top-level `model = "..."`
def check(text: str) -> Optional[str]   # tomllib.loads error message when tomllib exists, else None
```
Both are text-level edits that keep comments and ordering (same philosophy as
`shared/bin/sync-agents`). Callers back the file up before writing.

### core/editor.py

```python
def resolve_editor(config: Config, env: Mapping, which=shutil.which) -> Tuple[str, ...]   # argv prefix; ("vi",) as last resort
def edit_file(path: str, argv: Tuple[str, ...], run=subprocess.call) -> int    # plain call; the TUI wraps it with curses suspend/resume
```

## Content that becomes templates (authored in Part 2 content units)

- `shared/RULES.md` becomes a template: section A lists only the tools present (Docker line when
  docker is installed; Node/nvm versions from `profile`); section C's tool-mapping bullets appear
  per tool and quote the configured models/efforts; section D uses `{{ profile.context_budget_k }}`;
  section E is the hard never-delete rule when `config.guardrails.never_delete` is true and a
  softer "prefer mv to a backup; rm only on an explicit user request in this session, and say what
  was removed" rule otherwise; a new section **F. Environment & defaults (generated)** lists detected
  tools and versions, the review backend, the Obsidian vaults (default first), sessions and backups
  dirs, hook profile and disabled hooks, and ends with "Regenerate with ./install.sh after changing
  ~/.agents/config.json."
- `shared/LOCAL.example.md`: a short header explaining this file is the user's own rules, imported
  by Claude Code and synced into Codex, never overwritten by the installer.
- `claude-code/CLAUDE.md` gains `@~/.agents/LOCAL.md` after the RULES import.
- `shared/bin/sync-agents rules` also syncs `~/.agents/LOCAL.md` into `~/.codex/AGENTS.md` between
  `<!-- BEGIN LOCAL RULES (synced from ~/.agents/LOCAL.md) -->` / `<!-- END LOCAL RULES -->`
  (appended after the shared block; skipped silently when LOCAL.md is absent).
- `claude-code/commands/orchestrate.md`: Phase 3 becomes `{% if profile.review_backend == "codex" %}`
  Codex-first text (3a–3e as today) `{% else %}` a Claude-only Phase 3 (the 3f fallback promoted to the
  main path, with no mention of exit codes or the runner) `{% endif %}`; 3f/3g adjusted accordingly;
  Gate A and Gate C text wrapped in `{% if config.guardrails.plan_approval_gate %}` /
  `fix_approval_gate` conditionals whose else-branch says the gate is disabled in config and the
  plan/fix list is logged instead; the Agent Routing Table shows the codex-review-runner row only
  when the backend is codex. Model names in the routing table use `{{ profile.claude_heavy }}` etc.
- `installer:requires codex` on `claude-code/agents/codex-review-runner.md`,
  `claude-code/commands/multi-backend.md`, `multi-execute.md`, `multi-plan.md`;
  `installer:requires gemini` on `multi-frontend.md`; `installer:requires-any codex gemini` on
  `multi-workflow.md`; `.installer-requires` containing `codex` in
  `claude-code/scripts/codex-review-pipeline/`.
- Obsidian skills (`obsidian-cli`, `obsidian-markdown`, `obsidian-bases`, `json-canvas`,
  `local-knowledge-retrieval`, `token-efficient-orchestration`): one sentence under the first
  heading: "When the user does not name a vault, use the default vault listed under
  'Environment & defaults' in ~/.agents/RULES.md (set it with ./install.sh → Settings)."
  Shared skills are copied, not rendered, so this is plain text, not a placeholder.

## install.sh (round 2)

- Before any section runs, render the three repo trees into a staging root:
  `STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ai-suite-stage.XXXXXX")"`, then
  `"$PY" -m installer render-tree "$REPO_DIR/shared" "$STAGE/shared" --rel shared` (and
  `claude-code`, `codex`). All `install_*` functions read from `$SRC_ROOT` (= `$STAGE`, or
  `$REPO_DIR` with a warning when rendering is impossible). Staging dirs are left for the OS to
  clean (never deleted by us).
- `claude-code/CLAUDE.md` is installed with `install_example` semantics (never overwrite an
  existing `~/.claude/CLAUDE.md`); `shared/config.example.json` -> `~/.agents/config.json` and
  `shared/LOCAL.example.md` -> `~/.agents/LOCAL.md` likewise.
- `--auto` installs the sections chosen by `"$PY" -m installer sections` (prints e.g.
  `shared claude`), which is what the TUI's Install/Apply actions use.
- After the codex section: `sync-agents rules` as today (it now also syncs LOCAL.md).

## cli.py additions

```
python3 -m installer caps [--json]                          detected tools table with hints
python3 -m installer config list [--json] | get KEY | set KEY VALUE | path | edit | reset KEY
python3 -m installer sections                               which of shared/claude/codex to install
python3 -m installer render FILE                            print the rendered file (exit 3 when excluded; exit 2 when FILE resolves outside the repo)
python3 -m installer render-tree SRC OUT --rel REL [--json] mirror SRC into OUT, rendered
python3 -m installer edit claude|local|config|agents|settings|codex-config|rules
python3 -m installer apply [--dry-run]                      ./install.sh --headless --auto (via subprocess), then settings-sync of the changed values
python3 -m installer settings-sync [--dry-run]              push hook profile + codex subagent settings into existing settings.json / config.toml
python3 -m installer doctor [--json]                        + caps, config validation, settings warnings
```

## tui additions

Tabs: `1` Overview `2` Skills `3` Installed `4` Issues `5` Updates `6` Settings `7` Files
`8` Install. Overview shows a "Detected tools" summary line per important tool with ✓/✗ and a
`S` key that starts the setup wizard. When `~/.agents/config.json` does not exist the app starts
on the wizard.

Settings screen: rows grouped by section (`Tools`, `Subagents`, `Review`, `Guardrails`, `Paths`,
`Editor`), each showing label, current value and the help text for the current row in the footer
area. `Enter`/`space` toggles a bool, cycles an enum; for int/str/path it opens an inline prompt
(`draw.prompt_line`); for pathlist/strlist it opens a list sub-screen with `a` add, `x` remove,
`d` make default (move to front) and, for `paths.obsidian_vaults`, `o` import from the Obsidian
registry (`capabilities.obsidian_vaults`). `s` saves (previous file backed up), `A` applies
(re-render and install via `./install.sh --headless --auto`, output in a pane), `R` reloads from
disk. Wizard mode walks the sections in order with `n` next / `p` previous and ends on a summary
with `s` save and `A` apply.

Files screen rows: `~/.claude/CLAUDE.md` (example-installed, yours), `~/.agents/LOCAL.md`
(yours, never overwritten), `~/.agents/config.json`, `~/.codex/AGENTS.md` (synced blocks
regenerated), `~/.claude/settings.json`, `~/.codex/config.toml`, `~/.agents/RULES.md` (rendered
- edits are overwritten on the next install; edit shared/RULES.md in the repo instead). Keys:
`Enter`/`e` open in the editor (curses suspended), `v` view in the TUI, `d` diff against the repo
source when one exists, `c` create from the example when missing.

## Tests for Part 2

`test_config.py` (defaults, merge, immutability, with_value validation, parse_value, save backs up
and writes atomically, bad JSON), `test_capabilities.py` (stubbed which/run; registry parsing from
a temp file for all three platforms; resolve_tool), `test_render.py` (every tag and filter, line
consumption, nested blocks, for-loops, unknown paths -> warnings, unbalanced -> RenderError,
non-template passthrough including `{{ }}` text, requires/requires-any/.installer-requires,
render_tree on a fixture tree with binary + text + excluded files, mode bits), `test_rewrite.py`
(each rule with headroom/codex on and off, output still parses), `test_claude_settings.py`,
`test_codex_config.py`, `test_editor.py`, plus `test_render_repo.py` which renders the REAL repo
trees (`shared`, `claude-code`, `codex`) with two contexts (everything on; codex and headroom
off) and asserts: no `{{`/`{%` remains in any rendered Markdown, the orchestrate command has no
"codex-review-runner" text when the backend is claude, `codex-review-runner.md` and the
`codex-review-pipeline` dir are absent in the off render, every rendered JSON parses, every
rendered TOML parses when tomllib is available, and `~/.agents/RULES.md` output contains section F.

---

# Part 3 - extras catalog and authored workflow skills

## Extras: external integrations the installer knows about

Some recommended tools are not skills: they ship their own installer (Impeccable), are a
plugin/MCP server (Figma), are too large to vendor (ppt-master, presentation-skill) or carry a
license that forbids redistribution (Anthropic's pptx). An optional `note` string per entry is shown in the details view. `shared/extras.json` lists them; the installer shows their status and can
run their install command **only after an explicit confirmation that says third-party code will
run**. It never runs one on its own.

```json
{
  "_comment": "External integrations the installer can detect and (on confirmation) install. Not skills.",
  "extras": {
    "impeccable": {
      "title": "Impeccable - design vocabulary, refinement commands and design checks",
      "category": "design",
      "url": "https://impeccable.style/docs/",
      "tools": ["claude", "codex"],
      "install": ["npx impeccable install"],
      "after_install": { "claude": "run /impeccable init in a project", "codex": "run $impeccable in a project" },
      "detect": { "any_paths": ["~/.claude/skills/impeccable", "~/.claude/commands/impeccable.md", "~/.codex/skills/impeccable"] }
    },
    "figma-mcp": {
      "title": "Figma MCP - live canvas and FigJam access for the agent",
      "category": "design",
      "url": "https://help.figma.com/hc/en-us/articles/39888612464151",
      "tools": ["claude", "codex"],
      "install_by_tool": {
        "claude": ["claude plugin install figma@claude-plugins-official"],
        "codex": ["codex mcp add figma --url https://mcp.figma.com/mcp"]
      },
      "detect": { "claude_mcp": "figma", "codex_mcp": "figma", "claude_plugin": "figma@claude-plugins-official" }
    },
    "ppt-master": {
      "title": "PPT Master - editable .pptx decks with native shapes, charts and brand templates",
      "category": "presentations",
      "url": "https://github.com/hugohe3/ppt-master",
      "tools": ["claude", "codex"],
      "install": ["npx skills add hugohe3/ppt-master"],
      "detect": { "any_paths": ["~/.agents/skills/ppt-master", "~/.claude/skills/ppt-master", "~/.codex/skills/ppt-master"] },
      "note": "78 MB upstream, so it is installed locally rather than vendored"
    },
    "presentation-skill": { "...": "same shape; npx skills add sirilsengolraj-source/presentation-skill" },
    "anthropic-pptx": {
      "title": "Anthropic pptx skill - read, create and edit PowerPoint files",
      "category": "presentations",
      "tools": ["claude", "codex"],
      "install_by_tool": {
        "claude": ["npx skills add anthropics/skills --skill pptx --agent claude-code"],
        "codex": ["npx skills add anthropics/skills --skill pptx --agent codex"]
      },
      "detect": { "any_paths": ["~/.claude/skills/pptx", "~/.codex/skills/pptx"] },
      "note": "its LICENSE.txt forbids redistribution, so it is never vendored"
    }
  }
}
```

```python
# core/extras.py
@dataclass(frozen=True) class Extra: key, title, category, url, tools, install (Tuple[str,...]), install_by_tool (Mapping[str, Tuple[str,...]]), after_install (Mapping[str,str]), detect (Mapping)
@dataclass(frozen=True) class ExtraStatus: extra: Extra; installed: Mapping[str, Optional[bool]]  # per tool: True/False/None(unknown)
def load(paths) -> Tuple[Extra, ...]                     # from <repo>/shared/extras.json; schema-validated; bad file -> ()
def detect(extra, paths, env=None, run=subprocess.run, which=shutil.which) -> ExtraStatus
    # any_paths: exists after ~ expansion; claude_mcp: name in `claude mcp list` output; codex_mcp: [mcp_servers.<name>]
    # in ~/.codex/config.toml (text search, no tomllib needed); claude_plugin: key in ~/.claude/settings.json enabledPlugins
def commands_for(extra, tool) -> Tuple[str, ...]        # install_by_tool[tool] or install
```

CLI: `extras list [--json]`, `extras show NAME`, `extras install NAME [--tool claude|codex] [--yes]`
(prints the exact commands and the third-party-code warning, asks `Run? [y/N]`, runs each with
`subprocess.run(shlex.split(cmd), env=<the context's env, so --home is honoured>)` - never `shell=True`,
never on a non-TTY without `--yes`).
TUI: tab `9` Extras: rows = extras with per-tool ✓/✗/?; `Enter` details (title, url, commands,
after-install note); `i` install for the tools that are on (confirm screen with the warning,
output pane); `o` prints the URL to the message line.

`shared/mcp-servers.json` gains an optional `"enabled": false` per server (sync-agents skips
those, `status` lists them as "disabled"); the Figma remote server is added disabled, so a user
who prefers the MCP route over the plugin flips one flag.

## Authored skills (shared/skills, tool-neutral)

All three follow the repo's phased, gated style (investigate → grill the user until requirements
are unambiguous → gate → produce → verify → hand back) and the skill frontmatter contract.

- `skill-forge`: a skill that builds skills. Phases: 0 intake (what task, who runs it, which tool
  or both, triggers), 1 grill (asks the questions a skill author must answer: trigger phrases,
  inputs/outputs, success criteria, failure modes, which existing skills overlap - it searches
  `~/.agents/skills`, `~/.claude/skills`, `~/.codex/skills` and the find-skills catalog), gate on an
  approved spec, 2 draft (`SKILL.md` with name/description/when-to-use/steps/output contract,
  optional `references/`, `scripts/`, `agents/openai.yaml` for Codex metadata), 3 test (dry-run the
  skill against 2-3 sample prompts the user approved, check frontmatter with the repo's
  verification snippet), 4 place (shared vs platform-specific decision per AGENTS.md rules, add the
  README table row, skill-lock provenance when adapted from upstream) and hand back a summary.
- `product-design-workflow`: the five-phase product design and UX workflow (brief → UX
  architecture: sitemap, navigation tree, user journeys, edge cases → visual direction with 2-3
  distinct directions and an anti-generic checklist → prototype: Figma/FigJam when the Figma MCP is
  connected, otherwise a clickable HTML prototype → build and verify in the browser at desktop and
  mobile sizes). Deliverables are files: `docs/product-brief.md`, `docs/sitemap.md`,
  `docs/user-flows.md` (Mermaid), a screen inventory. It names the skills it leans on when
  installed (`frontend-design`, the `ux-flow-skills` family, `information-architecture`,
  Impeccable commands) and states what it does without them. It never claims a Figma artifact,
  prototype or visual test exists unless created or run.
- `presentation-workflow`: narrative first, deck second. Phase 1 story (audience, one-sentence
  takeaway, BLUF, Minto pyramid, slide outline with one idea per slide and takeaway headlines,
  Q&A bank), gate, Phase 2 format decision (editable .pptx via `pptx` / `ppt-master` / OpenAI
  Slides, or an HTML deck via `frontend-slides`; speaker deck vs reading deck), Phase 3 build with
  the chosen skill, Phase 4 QA (render to images when the toolchain allows, check overflow,
  alignment, contrast, speaker notes), hand back with the file paths.

---

# Part 4 - TUI interface contract

`installer/tui/base.py` (frozen) defines `Screen`, `POP`, `QUIT` and `TABS`, and documents the
App's attributes and methods in its module docstring. Every screen module codes against that
docstring, never against another screen. `installer/tui/draw.py` is the only module that calls
curses drawing primitives; screens call its helpers:

```python
init_colors() -> None                                    # safe when has_colors() is False
attr(name) -> int                                        # "title"|"ok"|"warn"|"error"|"selected"|"dim"|"normal"
glyph(name) -> str                                       # "installed"|"missing"|"modified"|"foreign"|"remote"|"problem"|"selected"|"unselected"
safe_addstr(win, y, x, text, attr=0, width=None) -> None # clips, never raises
draw_frame(stdscr, app, title, footer) -> Tuple[int, int, int, int]   # chrome: top line with repo/git, tab bar, footer; returns (y0, x0, height, width) of the body
draw_list(win, y0, x0, height, width, model, row_fn, focused=True) -> None   # row_fn(item, selected: bool, width) -> Tuple[str, int]
draw_text(win, y0, x0, height, width, lines, top, left=0) -> None
prompt_line(stdscr, label, initial="") -> Optional[str]  # inline single-line editor; Esc -> None
too_small(stdscr) -> bool                                 # draws the 80x24 notice when the terminal is smaller
```

`App.run(paths, start_screen)` lives in `installer/tui/app.py`; `installer.tui.run(paths,
start_screen="overview") -> int` is the entry the CLI calls. ConfirmScreen and OutputScreen live
in `installer/tui/screens/confirm.py` and are pushed only through `App.confirm` / `App.run_command`.

---

# Part 5 - workflow maker

A **workflow** composes installed skills into a phased, gated procedure and ships as an ordinary
shared skill, so Claude Code and Codex run it like any other skill. The installer owns its
machine-readable definition and renders the SKILL.md from it.

## On disk

```
~/.agents/skills/<name>/
  workflow.json        the definition (source of truth; edited by the installer)
  SKILL.md             rendered from workflow.json; carries "<!-- ai-suite:workflow -->" on line 2
  agents/openai.yaml   rendered Codex display metadata
```
The directory is a normal shared skill: it is symlinked into both tools, shows up in Skills /
Installed, can be retired (moved to backups) and pushed into the repo's `shared/skills/`.

## core/workflows.py

```python
WORKFLOW_FILE = "workflow.json"; MARKER = "<!-- ai-suite:workflow -->"
@dataclass(frozen=True)
class Phase: name: str; goal: str; skills: Tuple[str, ...]; steps: Tuple[str, ...] = (); outputs: Tuple[str, ...] = (); gate: bool = False; gate_text: str = ""
@dataclass(frozen=True)
class WorkflowDef: name: str; description: str; triggers: Tuple[str, ...]; phases: Tuple[Phase, ...]; handback: str = ""; version: int = 1
def from_json(text: str) -> WorkflowDef          # ValueError with a clear message on bad shape
def to_json(wf: WorkflowDef) -> str              # indent=2, trailing newline, stable key order
def load_def(skill_dir: str) -> Optional[WorkflowDef]
def list_workflows(paths: Paths) -> Tuple[Tuple[str, WorkflowDef], ...]   # (skill_dir, def) for every ~/.agents/skills/*/workflow.json, sorted by name
def validate(wf: WorkflowDef, known_skills: FrozenSet[str]) -> Tuple[str, ...]
    # errors: invalid name (core.skills.is_valid_name), empty description, no phases, duplicate phase
    # names, phase without skills AND without steps; warnings (prefixed "warning: "): skill not in
    # known_skills (installed shared/claude/codex names plus the repo catalog)
def render_skill_md(wf: WorkflowDef) -> str
    # deterministic: frontmatter (name; description = wf.description + " Use when the user says: " +
    # triggers joined by ", "), MARKER line, purpose paragraph, "Skills this workflow loads" table
    # (skill -> phases), then one "## Phase N - <name>" per phase with: Goal, "Load: <skills>" line
    # ("read each skill's SKILL.md before acting"), numbered steps, Outputs list, and when gate is
    # true a bold "Gate:" line with gate_text (default "the user approves this phase's outputs
    # before the next phase starts"); then "## Handback" (wf.handback or a default template listing
    # every phase's outputs) and a closing line "Edit this workflow with ./install.sh (Workflows tab);
    # the source of truth is workflow.json next to this file."
def render_openai_yaml(wf: WorkflowDef) -> str   # same shape as shared/skills/lambda-gpu-training/agents/openai.yaml
def stage(wf: WorkflowDef, stage_dir: str) -> str     # writes the three files into <stage_dir>/<name>/ and returns that path
def plan_save(wf: WorkflowDef, paths: Paths, backup_root: str, stage_dir: str, links: Tuple[ConsumerLink, ...] = ()) -> Tuple[Operation, ...]
    # stage() first; then: "backup" the existing ~/.agents/skills/<name> when present, "copytree"
    # the staged dir into place, and "symlink" each consumer whose link state is MISSING
    # (never touches REAL_DIR/WRONG_TARGET; the Issues screen handles those)
def example() -> WorkflowDef                      # a 3-phase sample (research -> design -> build) using skills that exist in this repo
```

## CLI

```
python3 -m installer workflow list [--json]
python3 -m installer workflow show NAME                  definition + validation
python3 -m installer workflow render NAME                print the rendered SKILL.md
python3 -m installer workflow example [--json]           print a sample definition to start from
python3 -m installer workflow save FILE.json [--yes]     validate, stage, plan, confirm, apply, rescan links
python3 -m installer workflow retire NAME [--yes]        core.actions.plan_retire on the shared row
python3 -m installer workflow push NAME [--yes]          core.actions.plan_push_to_repo on the shared row
```
Exit 2 on validation errors (each printed); warnings print but do not block.

## TUI

`base.TABS` gains `(10, "Workflows")`, reached with key `0`. `installer/tui/screens/workflows.py`:
list of workflows (name, phases count, skills count, validation state), `Enter` opens the editor,
`n` new (starts from a blank definition with one empty phase), `e` edit, `r` retire, `p` push to
repo, `v` view rendered SKILL.md in the viewer's text pane. `installer/tui/screens/workflow_edit.py`:
the editor shows the header fields (name, description, triggers as a comma list, handback) and the
ordered phase list; `Enter` on a field prompts (draw.prompt_line), `a` adds a phase, `x` removes
the current phase, `J`/`K` move it, `Enter` on a phase opens the phase editor; phase editor fields:
name, goal, skills (`s` opens a skill picker: a ListModel over the union of installed and catalog
skill names with their descriptions, `/` filter, space toggles, `Enter` accepts), steps (one per
prompt line, `a` add / `x` remove / `J`/`K` move), outputs (same), gate toggle, gate text. `s` in
the editor validates (errors shown; warnings allowed) then `app.confirm(plan_save(...))`; `q`
asks `y` before discarding unsaved changes. Every list is a ListModel; every edit returns a new
WorkflowDef via dataclasses.replace.

## Tests

`test_workflows.py`: from_json/to_json round trip, validation errors and warnings, render_skill_md
determinism and required sections (frontmatter name/description, MARKER, one section per phase,
gate lines only for gated phases, handback), render_openai_yaml, stage() file set, plan_save op
kinds for new vs existing (backup first) and MISSING links, example() validates against the real
repo catalog. `test_cli_workflow.py`: list/show/render/example/save --yes/retire --yes/push --yes
on the fixture home. `test_screens_workflows.py`: editor key handling without curses (add/move/
remove phases, skill picker toggle, save builds a plan with the right kinds, q-with-changes asks).

---

# Part 6 - the Claude mod (`mods/ai-suite/`)

A Claude Code mod (hooks module) that puts the skills manager inside Claude: a pane, a status
line entry and two slash commands, all thin layers over the installer CLI's JSON output. It lives
in the repo at `mods/ai-suite/` and is shared through a marketplace file at the repo root, so
anyone installs it with one line from a terminal session:

```
/plugin install ai-suite --marketplace bhavya091213/ai-suite
```

## Files

```
.claude-plugin/marketplace.json      repo root: { "name": "ai-suite", "owner": {"name": "bhavya091213"},
                                                  "plugins": [{ "name": "ai-suite", "source": "./mods/ai-suite" }] }
mods/ai-suite/
  .claude-plugin/plugin.json         name "ai-suite", version, description, "types": "./types/index.d.ts",
                                     userConfig: repoPath (string, default ""), python (string, default "python3"),
                                     checkOnStart (boolean, default true)
  hooks/hooks.json                   { "modules": ["./register.tsx"] }
  hooks/register.tsx                 the hooks module (see below); split helpers into hooks/*.ts when over 400 lines
  hooks/*.test.ts                    `claude plugin test mods/ai-suite`
  types/index.d.ts                   the $.state contract (PluginState['ai-suite'])
  README.md                          install line, what the pane shows, the userConfig fields
```

## Behaviour

- **Repo resolution.** `repoPath` from userConfig when set; otherwise the plugin folder's
  grandparent (`<repo>/mods/ai-suite` -> `<repo>`), accepted only when it holds `install.sh` and
  `installer/`. Every command is `[python, "-m", "installer", "--repo", repo, ...]` run with
  `$.process.run(argv, { cwd: repo })`; stdout is parsed as JSON. A failure (non-zero exit, bad
  JSON) is shown in the pane's message row and as a toast, never thrown.
- **session.start.** Registers `/skills` (opens the pane) and `/skills-check` (runs `doctor --json`
  and `updates --json --fetch`, then toasts a one-line summary). When `checkOnStart` is true, runs
  `status --json` and `updates --json` without fetching (no network at start) in the background
  and sets the status line to e.g. `skills 57/90 · 3 updates · 2 issues`; returns `next(e)`
  without waiting.
- **Pane `ai-suite`** ("Skills"), drawn by `ui.render` on `{ component: 'Pane', requestId }`:
  a view switcher row of Buttons (Overview, Install, Issues, Updates, Workflows, Doctor; hotkeys
  `o i s u w d`), a message row, then the view:
  - Overview: repo path (`~`-shortened), git line (message + hint), one row per scope with
    installed/modified/missing/problems counts, buttons `[Refresh]` `[Apply config]` (runs
    `apply --yes`, confirm first).
  - Install: not-installed skills (name, scope, description truncated), `[Install]` per row
    (`install NAME --scope S --yes --json`), `[Install all missing]` with a confirm step.
  - Issues: rows from `issues --json` with `[Relink]` / `[Retire]` per row; Retire is two-step
    (the button turns into `[Confirm retire]` for one press).
  - Updates: git banner, commits behind, skills with remote changes; `[Fetch]`, `[Pull]` (ff-only,
    confirm), `[Update changed]` (update every MODIFIED skill that has a remote change, confirm).
  - Workflows: rows from `workflow list --json` (name, phases, skills, valid), a hint that the
    editor lives in `./install.sh` (tab 0).
  - Doctor: rows from `doctor --json`, each with ok/warn/blocker.
  Lists are bounded to the viewport rows; the pane states "N more" when cut. All state lives in
  atoms declared in the contract: view, snapshots per command (data + fetchedAt + error), busy
  flag, pendingConfirm key, message.
- **Never destructive without a press to confirm.** Retire, Pull, Apply config, Install all
  missing and Update changed all take a second press. Nothing runs on a timer.
- **Surfaces.** Elements come from `$.ui.resolve(e)`; the same tree is drawn on `terminal` and
  `desktop`; tests loop over both.

## CLI additions the mod needs

`updates --json` (git banner fields, commits behind, changed skills) and `doctor --json` (one
row per check: name, state ok|warn|blocker, text). Both additive; the text output is unchanged.

## Tests (`mods/ai-suite/hooks/register.test.ts`)

With `claude-code/testing`: mock `$.process.run` to return canned JSON per argv; assert
`session.start` registers both commands and sets the status line text; `command.run skills`
opens the pane; the Overview tree holds the counts; pressing Install on a row runs the expected
argv; Retire needs two presses and the first does not run anything; a failing command puts its
stderr into the message row and runs nothing else; `repoPath` unset resolves the grandparent;
loop the UI assertions over `['terminal', 'desktop']`.
