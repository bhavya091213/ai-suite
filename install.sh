#!/usr/bin/env bash
#
# install.sh - install this repo's agent configuration into $HOME.
#
#   shared/      -> ~/.agents    (RULES.md, config.json, LOCAL.md, mcp-servers.json, bin/sync-agents, skills/)
#   claude-code/ -> ~/.claude    (CLAUDE.md, agents/, commands/, rules/, hooks/, scripts/, skills/)
#   codex/       -> ~/.codex     (AGENTS.md, agents/, scripts/, prompts/, workflows/, hooks.json, skills/)
#
# ~/.agents/skills is the single source of truth for shared skills; each one is
# symlinked into ~/.claude/skills/<name> and ~/.codex/skills/<name>.
#
# Repo files that contain an installer template marker (and codex/AGENTS.md) are
# rendered from ~/.agents/config.json at install time: all three trees are first
# rendered into a staging directory (python3 -m installer render-tree) and the
# rendered copies are what gets installed. If rendering is impossible the repo
# files are installed verbatim, with a warning. The staging directory is never
# deleted; its path is printed at the end of the summary.
#
# Files that are yours once installed (~/.claude/CLAUDE.md, ~/.claude/settings.json,
# ~/.codex/config.toml, ~/.agents/config.json, ~/.agents/LOCAL.md) are installed
# from their bundled examples only when absent, or replaced (backed up) with --force.
#
# This script NEVER deletes anything. Anything it would overwrite is moved into
# ~/.agents/backups/ai-suite-install-<timestamp>/ first.
#
# Entry points:
#   ./install.sh                 no arguments on a terminal: launch the interactive installer
#                                (python3 -m installer tui). If it cannot start, print why plus
#                                the usage text and exit 1 without installing anything.
#                                No arguments and no terminal: the headless install of everything
#   ./install.sh --tui           force the interactive installer
#   ./install.sh --all | --shared | --claude | --codex | --headless [--dry-run] [--force]
#                                headless install of the repo into $HOME
#   ./install.sh --auto [--dry-run] [--force]
#                                headless install of the sections chosen by
#                                `python3 -m installer sections` (a subset of shared, claude, codex)
#   ./install.sh skills <args>   forward <args> to the skill manager (python3 -m installer <args>)
#
# Requires: bash, coreutils, python3 (3.9+, with curses for the interactive
# installer; any python3 is enough for the headless install).

set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DO_SHARED=0
DO_CLAUDE=0
DO_CODEX=0
DRY_RUN=0
FORCE=0
WANT_TUI=0
WANT_HEADLESS=0
AUTO=0
NO_ARGS=0
PY=""
SRC_ROOT="$REPO_DIR"
STAGE=""

AGENTS_HOME="$HOME/.agents"
CLAUDE_HOME="$HOME/.claude"
CODEX_HOME="$HOME/.codex"
BACKUP_ROOT="$AGENTS_HOME/backups/ai-suite-install-$(date +%Y%m%d-%H%M%S)"

n_shared=0
n_claude=0
n_codex=0
n_links=0
n_backups=0
n_skipped=0
n_warnings=0
TREE_INSTALLED=0
EXAMPLE_INSTALLED=0

# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------

say()  { printf '%s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf 'warn: %s\n' "$*" >&2; n_warnings=$((n_warnings + 1)); }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]
       ./install.sh skills <args...>

With no arguments on an interactive terminal, launches the interactive
installer (python3 -m installer tui). If it cannot start (no Python 3.9+ with
curses), the reason and this help are printed to stderr and the script exits 1
without installing anything. With no arguments and no terminal (stdin or stdout
is not a TTY), or with any option below, runs the headless install.

Repo files that contain an installer template marker are rendered from
~/.agents/config.json at install time (python3 -m installer render-tree) before
they are installed; without a usable python3 they are installed verbatim.

Modes:
  --tui         Force the interactive installer; cannot be combined with any
                other option
  --headless    Install without the interactive installer (the old no-argument
                default: everything, unless sections are given)
  skills <args...>
                Forward <args...> to the skill manager, i.e. run
                python3 -m installer <args...>. Must be the first argument.
                  ./install.sh skills status
                  ./install.sh skills install lambda-gpu-training

Sections (default: --all):
  --shared      Install shared/  -> ~/.agents
  --claude      Install claude-code/ -> ~/.claude (+ symlink shared skills)
  --codex       Install codex/   -> ~/.codex (+ symlink shared skills)
  --all         All three, in order: shared, claude, codex
  --auto        Install the sections printed by `python3 -m installer sections`
                (a subset of shared, claude, codex). Cannot be combined with
                --shared, --claude, --codex, --all or --tui

Options:
  --dry-run     Print what would happen; change nothing
  --force       Also overwrite the files that are yours once installed -
                ~/.claude/CLAUDE.md, ~/.claude/settings.json,
                ~/.codex/config.toml, ~/.agents/config.json and
                ~/.agents/LOCAL.md - from the bundled examples (backed up first)
  -h, --help    Show this help

Environment:
  INSTALLER_PYTHON  Python 3.9+ interpreter to prefer for the interactive
                    installer, `skills`, template rendering and --auto
                    (default: search PATH)

Nothing is ever deleted. Files that would be overwritten are moved to
~/.agents/backups/ai-suite-install-<timestamp>/ first.
EOF
}

# ---------------------------------------------------------------------------
# python discovery and the interactive installer
# ---------------------------------------------------------------------------

# find_python [curses]
# Sets PY to the first interpreter that is Python >= 3.9 (and, when the
# argument is "curses", can import curses). Returns 1 with PY empty if none is.
# Each probe has stderr silenced and stdin closed; any non-zero exit (including
# a broken /usr/bin/python3 stub) just means "not this one".
find_python() {
  local need="${1:-}" cand
  PY=""
  for cand in "${INSTALLER_PYTHON:-}" python3 python3.13 python3.12 python3.11 \
              python3.10 python3.9 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
              /usr/bin/python3; do
    [ -n "$cand" ] || continue
    command -v "$cand" >/dev/null 2>&1 || continue
    "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
      >/dev/null 2>&1 </dev/null || continue
    if [ "$need" = "curses" ]; then
      "$cand" -c 'import curses' >/dev/null 2>&1 </dev/null || continue
    fi
    PY="$cand"
    return 0
  done
  return 1
}

# run_skills <args...>
# Hands everything to the Python package: ./install.sh skills X -> python3 -m installer X
run_skills() {
  find_python || die "Python 3.9+ is required for 'skills' (set INSTALLER_PYTHON to point at one)"
  [ -d "$REPO_DIR/installer" ] || die "installer/ package not found in $REPO_DIR"
  PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m installer "$@"
}

# launch_tui <forced>
# Execs the interactive installer. When it cannot start: with forced=1 (--tui)
# this is an error; with forced=0 (bare ./install.sh on a terminal) it prints
# why, then the usage text to stderr, and exits 1. The user only wanted to look,
# so it never falls through to an install.
launch_tui() {
  local forced="$1" why="" python_hint=0
  if [ ! -d "$REPO_DIR/installer" ]; then
    why="installer/ package not found in $REPO_DIR"
  elif find_python curses; then
    say "launching the interactive installer; run ./install.sh --all for the headless install"
    PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m installer tui
  elif find_python; then
    why="$PY is Python 3.9+ but has no curses module"
    python_hint=1
  else
    why="no Python 3.9+ interpreter found"
    python_hint=1
  fi
  if [ "$forced" -eq 1 ]; then
    [ "$python_hint" -eq 1 ] && printf 'hint: install Python 3.9+ (with curses) to use the interactive installer\n' >&2
    die "cannot start the interactive installer: $why"
  fi
  printf 'note: cannot start the interactive installer: %s\n' "$why" >&2
  if [ "$python_hint" -eq 1 ]; then
    printf 'hint: install Python 3.9+ (with curses) to use the interactive installer\n' >&2
  fi
  usage >&2
  exit 1
}

# ---------------------------------------------------------------------------
# filesystem helpers (never use rm)
# ---------------------------------------------------------------------------

# Path inside the backup tree for a destination under $HOME.
backup_dest_for() {
  local dest="$1" rel
  case "$dest" in
    "$HOME"/*) rel="${dest#"$HOME"/}" ;;
    *)         rel="$(printf '%s' "$dest" | sed 's#^/##')" ;;
  esac
  printf '%s/%s' "$BACKUP_ROOT" "$rel"
}

# Move an existing file/dir/symlink out of the way into the backup tree.
stash() {
  local dest="$1" bdest
  bdest="$(backup_dest_for "$dest")"
  n_backups=$((n_backups + 1))
  if [ "$DRY_RUN" -eq 1 ]; then
    info "backup  $dest -> $bdest"
    return 0
  fi
  mkdir -p "$(dirname "$bdest")"
  mv "$dest" "$bdest"
  info "backup  $dest -> $bdest"
}

# install_file <src> <dest>; returns 0 if installed, 1 if skipped as identical.
install_file() {
  local src="$1" dest="$2"
  if [ -e "$dest" ] && [ ! -L "$dest" ] && cmp -s "$src" "$dest"; then
    n_skipped=$((n_skipped + 1))
    return 1
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    stash "$dest"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    info "install $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  cp -p "$src" "$dest"
  info "install $dest"
}

# install_tree <src_dir> <dest_dir>
# Copies every regular file under src_dir, preserving mode bits and layout.
# Sets TREE_INSTALLED to the number of files written (bash 3.2 has no namerefs).
install_tree() {
  local src="$1" dest="$2" rel target file dir
  TREE_INSTALLED=0
  if [ ! -d "$src" ]; then
    # In the staged tree a directory can be absent because every file in it was
    # excluded by a requires marker; that is expected, not a warning.
    if [ "$SRC_ROOT" != "$REPO_DIR" ] && [ -d "$REPO_DIR/${src#"$SRC_ROOT"/}" ]; then
      return 0
    fi
    warn "missing source directory: $src"
    return 0
  fi
  while IFS= read -r -d '' file; do
    rel="${file#"$src"/}"
    target="$dest/$rel"
    if install_file "$file" "$target"; then
      TREE_INSTALLED=$((TREE_INSTALLED + 1))
    fi
  done < <(find "$src" -type f ! -name '.DS_Store' ! -name '.installer-requires' -print0)
  # Recreate any empty directories the file walk missed.
  while IFS= read -r -d '' dir; do
    rel="${dir#"$src"/}"
    [ "$rel" = "$dir" ] && continue
    target="$dest/$rel"
    if [ ! -d "$target" ]; then
      if [ "$DRY_RUN" -eq 1 ]; then
        info "mkdir   $target"
      else
        mkdir -p "$target"
      fi
    fi
  done < <(find "$src" -type d -empty -print0)
}

# install_example <src> <dest> <label>
# Installs only when dest is absent, unless --force. Sets EXAMPLE_INSTALLED to 1
# when a file was (or, in a dry run, would be) written, else 0.
install_example() {
  local src="$1" dest="$2" label="$3"
  EXAMPLE_INSTALLED=0
  if [ -e "$dest" ] && [ "$FORCE" -eq 0 ]; then
    info "keep    $dest (already exists)"
    info "        compare with: diff \"$dest\" \"$src\""
    n_skipped=$((n_skipped + 1))
    return 0
  fi
  if install_file "$src" "$dest"; then
    EXAMPLE_INSTALLED=1
    info "        installed $label from example - review it before first use"
  fi
}

resolve() {
  "${PY:-python3}" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

relpath() {
  "${PY:-python3}" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$1" "$2"
}

# link_shared_skills <target_skills_dir>
# Links each ~/.agents/skills/<name> into <target_skills_dir>/<name> using a
# relative target, matching the layout sync-agents already expects.
link_shared_skills() {
  local skills_dir="$1" src name dest current rel_prefix skills_real
  if [ ! -d "$AGENTS_HOME/skills" ]; then
    warn "no $AGENTS_HOME/skills - run with --shared first; skipping symlinks"
    return 0
  fi
  if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$skills_dir"
  fi
  rel_prefix="$(relpath "$AGENTS_HOME/skills" "$skills_dir")"
  skills_real="$(resolve "$AGENTS_HOME/skills")"
  while IFS= read -r -d '' src; do
    name="$(basename "$src")"
    dest="$skills_dir/$name"
    if [ -L "$dest" ]; then
      current="$(readlink "$dest")"
      # Already correct, whether stored relative or absolute.
      if [ "$current" = "$rel_prefix/$name" ] || [ "$current" = "$src" ] ||
         [ "$(resolve "$dest")" = "$skills_real/$name" ]; then
        n_skipped=$((n_skipped + 1))
        continue
      fi
      stash "$dest"
    elif [ -e "$dest" ]; then
      warn "$dest is a real directory (platform-specific skill) - not linking shared '$name'"
      continue
    fi
    if [ "$DRY_RUN" -eq 0 ]; then
      ln -s "$rel_prefix/$name" "$dest"
    fi
    info "link    $dest -> $rel_prefix/$name"
    n_links=$((n_links + 1))
  done < <(find "$AGENTS_HOME/skills" -mindepth 1 -maxdepth 1 -type d -print0)
}

# ---------------------------------------------------------------------------
# rendering stage and section selection
# ---------------------------------------------------------------------------

# render_stage
# Renders shared/, claude-code/ and codex/ into a fresh staging directory so that
# files carrying installer template markers are installed with their placeholders
# filled in from ~/.agents/config.json. On success SRC_ROOT is the staging root;
# when rendering is impossible it stays the repo and a warning says so. Writes
# only inside the staging directory (so it is safe in a dry run) and never
# deletes it.
render_stage() {
  local why="" dir tmp_base
  SRC_ROOT="$REPO_DIR"
  STAGE=""
  if [ -z "$PY" ]; then
    why="no Python 3.9+ interpreter found"
  elif [ ! -d "$REPO_DIR/installer" ]; then
    why="installer/ package not found in $REPO_DIR"
  else
    tmp_base="${TMPDIR:-/tmp}"
    tmp_base="${tmp_base%/}"
    if ! STAGE="$(mktemp -d "$tmp_base/ai-suite-stage.XXXXXX")"; then
      STAGE=""
      why="cannot create a staging directory"
    else
      for dir in shared claude-code codex; do
        if ! PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m installer render-tree \
               "$REPO_DIR/$dir" "$STAGE/$dir" --rel "$dir" >/dev/null; then
          why="render-tree failed for $dir"
          break
        fi
      done
    fi
  fi
  if [ -n "$why" ]; then
    STAGE=""
    warn "templates not rendered ($why); installing repo files verbatim"
    return 0
  fi
  SRC_ROOT="$STAGE"
}

# select_auto_sections
# --auto: sets DO_SHARED/DO_CLAUDE/DO_CODEX from the space-separated subset of
# "shared claude codex" that `python3 -m installer sections` prints.
select_auto_sections() {
  local out="" sec
  if [ -n "$PY" ] && [ -d "$REPO_DIR/installer" ]; then
    out="$(PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m installer sections)" || out=""
  fi
  set -f
  for sec in $out; do
    case "$sec" in
      shared) DO_SHARED=1 ;;
      claude) DO_CLAUDE=1 ;;
      codex)  DO_CODEX=1 ;;
      *)      set +f; die "unknown section '$sec' from 'python3 -m installer sections'" ;;
    esac
  done
  set +f
  if [ "$DO_SHARED" -eq 0 ] && [ "$DO_CLAUDE" -eq 0 ] && [ "$DO_CODEX" -eq 0 ]; then
    die "could not determine sections (python3 -m installer sections failed)"
  fi
}

# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------

install_shared() {
  say ""
  say "==> shared -> $AGENTS_HOME"
  install_file "$SRC_ROOT/shared/RULES.md"         "$AGENTS_HOME/RULES.md"         && n_shared=$((n_shared + 1))
  install_file "$SRC_ROOT/shared/mcp-servers.json" "$AGENTS_HOME/mcp-servers.json" && n_shared=$((n_shared + 1))
  install_file "$SRC_ROOT/shared/skill-lock.json"  "$AGENTS_HOME/.skill-lock.json" && n_shared=$((n_shared + 1))
  if install_file "$SRC_ROOT/shared/bin/sync-agents" "$AGENTS_HOME/bin/sync-agents"; then
    n_shared=$((n_shared + 1))
  fi
  if [ "$DRY_RUN" -eq 0 ] && [ -f "$AGENTS_HOME/bin/sync-agents" ]; then
    chmod +x "$AGENTS_HOME/bin/sync-agents"
  fi
  install_tree "$SRC_ROOT/shared/skills" "$AGENTS_HOME/skills"
  n_shared=$((n_shared + TREE_INSTALLED))
  install_example "$SRC_ROOT/shared/config.example.json" \
                  "$AGENTS_HOME/config.json" "config.json"
  if [ "$EXAMPLE_INSTALLED" -eq 1 ]; then n_shared=$((n_shared + 1)); fi
  install_example "$SRC_ROOT/shared/LOCAL.example.md" \
                  "$AGENTS_HOME/LOCAL.md" "LOCAL.md"
  if [ "$EXAMPLE_INSTALLED" -eq 1 ]; then n_shared=$((n_shared + 1)); fi
}

install_claude() {
  say ""
  say "==> claude-code -> $CLAUDE_HOME"
  install_example "$SRC_ROOT/claude-code/CLAUDE.md" "$CLAUDE_HOME/CLAUDE.md" "CLAUDE.md"
  if [ "$EXAMPLE_INSTALLED" -eq 1 ]; then n_claude=$((n_claude + 1)); fi
  local sub
  for sub in agents commands rules hooks scripts skills; do
    install_tree "$SRC_ROOT/claude-code/$sub" "$CLAUDE_HOME/$sub"
    n_claude=$((n_claude + TREE_INSTALLED))
  done
  install_example "$SRC_ROOT/claude-code/settings.example.json" \
                  "$CLAUDE_HOME/settings.json" "settings.json"
  say "    linking shared skills into $CLAUDE_HOME/skills"
  link_shared_skills "$CLAUDE_HOME/skills"
}

install_codex() {
  say ""
  say "==> codex -> $CODEX_HOME"
  install_file "$SRC_ROOT/codex/AGENTS.md"  "$CODEX_HOME/AGENTS.md"  && n_codex=$((n_codex + 1))
  install_file "$SRC_ROOT/codex/hooks.json" "$CODEX_HOME/hooks.json" && n_codex=$((n_codex + 1))
  local sub
  for sub in agents scripts prompts workflows skills; do
    install_tree "$SRC_ROOT/codex/$sub" "$CODEX_HOME/$sub"
    n_codex=$((n_codex + TREE_INSTALLED))
  done
  install_example "$SRC_ROOT/codex/config.example.toml" \
                  "$CODEX_HOME/config.toml" "config.toml"
  say "    linking shared skills into $CODEX_HOME/skills"
  link_shared_skills "$CODEX_HOME/skills"

  if [ -x "$AGENTS_HOME/bin/sync-agents" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      info "would run $AGENTS_HOME/bin/sync-agents rules"
    else
      say "    syncing shared rules into $CODEX_HOME/AGENTS.md"
      "$AGENTS_HOME/bin/sync-agents" rules || echo "warn: sync-agents rules failed"
    fi
  else
    warn "$AGENTS_HOME/bin/sync-agents not found or not executable - skipping rules sync"
  fi
}

summary() {
  local total=$((n_shared + n_claude + n_codex))
  say ""
  say "-------------------------------------------"
  printf '%-22s %s\n' "Section" "Files installed"
  say "-------------------------------------------"
  [ "$DO_SHARED" -eq 1 ] && printf '%-22s %d\n' "shared  (~/.agents)" "$n_shared"
  [ "$DO_CLAUDE" -eq 1 ] && printf '%-22s %d\n' "claude  (~/.claude)" "$n_claude"
  [ "$DO_CODEX"  -eq 1 ] && printf '%-22s %d\n' "codex   (~/.codex)"  "$n_codex"
  say "-------------------------------------------"
  printf '%-22s %d\n' "total files"      "$total"
  printf '%-22s %d\n' "skill symlinks"   "$n_links"
  printf '%-22s %d\n' "unchanged/kept"   "$n_skipped"
  printf '%-22s %d\n' "backed up"        "$n_backups"
  printf '%-22s %d\n' "warnings"         "$n_warnings"
  say "-------------------------------------------"
  if [ "$n_backups" -gt 0 ]; then
    say "Replaced items were moved to: $BACKUP_ROOT"
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY RUN - nothing was changed."
  fi
  if [ -n "$STAGE" ] && [ "$SRC_ROOT" = "$STAGE" ]; then
    say "rendered files staged in: $STAGE"
  fi
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

# `skills` is only recognised as the first argument; it never returns.
if [ "${1:-}" = "skills" ]; then
  shift
  run_skills "$@"
fi

if [ $# -eq 0 ]; then
  NO_ARGS=1
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --tui)      WANT_TUI=1 ;;
    --headless) WANT_HEADLESS=1 ;;
    --shared)   DO_SHARED=1 ;;
    --claude)   DO_CLAUDE=1 ;;
    --codex)    DO_CODEX=1 ;;
    --all)      DO_SHARED=1; DO_CLAUDE=1; DO_CODEX=1 ;;
    --auto)     AUTO=1 ;;
    --dry-run)  DRY_RUN=1 ;;
    --force)    FORCE=1 ;;
    -h|--help)  usage; exit 0 ;;
    skills)     usage >&2; die "'skills' must be the first argument" ;;
    *)          usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

# --auto picks its own sections, so it excludes the explicit section flags.
if [ "$AUTO" -eq 1 ]; then
  if [ "$DO_SHARED" -eq 1 ] || [ "$DO_CLAUDE" -eq 1 ] || [ "$DO_CODEX" -eq 1 ]; then
    printf 'error: --auto cannot be combined with --shared, --claude, --codex or --all\n' >&2
    exit 2
  fi
fi

# Interactive installer: forced by --tui, or chosen by a bare ./install.sh on a
# terminal. Everything else (any other option, or no terminal) stays headless.
if [ "$WANT_TUI" -eq 1 ]; then
  if [ "$WANT_HEADLESS" -eq 1 ] || [ "$DRY_RUN" -eq 1 ] || [ "$FORCE" -eq 1 ] || [ "$AUTO" -eq 1 ] ||
     [ "$DO_SHARED" -eq 1 ] || [ "$DO_CLAUDE" -eq 1 ] || [ "$DO_CODEX" -eq 1 ]; then
    printf 'error: --tui cannot be combined with --headless, --shared, --claude, --codex, --all, --auto, --dry-run or --force\n' >&2
    exit 2
  fi
  launch_tui 1
elif [ "$NO_ARGS" -eq 1 ] && [ -t 0 ] && [ -t 1 ]; then
  launch_tui 0
fi

if [ "$AUTO" -eq 0 ] && [ "$DO_SHARED" -eq 0 ] && [ "$DO_CLAUDE" -eq 0 ] && [ "$DO_CODEX" -eq 0 ]; then
  DO_SHARED=1; DO_CLAUDE=1; DO_CODEX=1
fi

find_python || true
[ -n "$PY" ] || command -v python3 >/dev/null 2>&1 || die "python3 is required"
[ -d "$REPO_DIR/shared" ] || die "run this script from inside the ai-suite repo"

if [ "$AUTO" -eq 1 ]; then
  select_auto_sections
fi

say "ai-suite installer"
say "  repo:   $REPO_DIR"
say "  home:   $HOME"
[ "$DRY_RUN" -eq 1 ] && say "  mode:   DRY RUN (no changes)"
[ "$FORCE"   -eq 1 ] && say "  mode:   FORCE (CLAUDE.md / settings.json / config.toml / config.json / LOCAL.md will be replaced)"
if [ "$AUTO" -eq 1 ]; then
  chosen=""
  if [ "$DO_SHARED" -eq 1 ]; then chosen="$chosen shared"; fi
  if [ "$DO_CLAUDE" -eq 1 ]; then chosen="$chosen claude"; fi
  if [ "$DO_CODEX"  -eq 1 ]; then chosen="$chosen codex"; fi
  say "  auto:   sections chosen by the installer:$chosen"
fi

render_stage

[ "$DO_SHARED" -eq 1 ] && install_shared
[ "$DO_CLAUDE" -eq 1 ] && install_claude
[ "$DO_CODEX"  -eq 1 ] && install_codex

summary
