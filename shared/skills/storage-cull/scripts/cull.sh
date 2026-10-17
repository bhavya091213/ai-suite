#!/usr/bin/env bash
# storage-cull: find and park orchestration-run residue in Trash. Never rm.
#
#   cull.sh survey
#   cull.sh cull [--apply] [--category a,b,...] [--wf-idle-min 60] [--scratch-idle-min 1440] [--codex-keep-months 3]
#
# Overridable for tests: HOME, CULL_SCRATCH_ROOT, CULL_TRASH, CULL_REPO_ROOTS (colon-separated)
set -euo pipefail

SCRATCH_ROOT="${CULL_SCRATCH_ROOT:-/private/tmp/claude-$(id -u)}"
TRASH="${CULL_TRASH:-$HOME/.Trash}/storage-cull-$(date +%Y-%m-%d)"
IFS=':' read -r -a REPO_ROOTS <<< "${CULL_REPO_ROOTS:-$HOME/Documents:$HOME/Desktop:$HOME/Downloads}"
BUILD_DIRS=(node_modules .next dist build .venv venv __pycache__ target .turbo)
ALL_CATEGORIES="workflows,scratchpads,backup-builds,worktrees,codex-sessions"

APPLY=0; CATEGORIES="$ALL_CATEGORIES"; WF_IDLE=60; SCRATCH_IDLE=1440; CODEX_KEEP=3
TOTAL_BYTES=0; MOVED=0; EMPTY=0

size_of() { du -sk "$1" 2>/dev/null | cut -f1; }           # KiB
human() { awk -v k="$1" 'BEGIN{ if(k>1048576) printf "%.1fG", k/1048576; else if(k>1024) printf "%.0fM", k/1024; else printf "%dK", k }'; }
is_busy() { [ -n "$(find "$1" -type f -mmin "-$2" -print -quit 2>/dev/null)" ]; }
rel_home() { printf '%s' "${1#"$HOME"/}"; }

park() { # park <category> <path>
  local cat="$1" src="$2" k; k=$(size_of "$src")
  if [ "${k:-0}" -eq 0 ]; then EMPTY=$((EMPTY+1)); return; fi            # empty leftovers are noise, not storage
  TOTAL_BYTES=$((TOTAL_BYTES + k))
  local dest="$TRASH/$cat/$(rel_home "$(dirname "$src")")"
  if [ "$APPLY" = 1 ]; then mkdir -p "$dest"; mv "$src" "$dest/"; MOVED=$((MOVED+1)); echo "  moved  $(human "$k")  $src"
  else echo "  would  $(human "$k")  $src"; fi
}

want() { case ",$CATEGORIES," in *",$1,"*) return 0;; *) return 1;; esac; }

# ---------- categories ----------
cull_workflows() {
  echo "== workflows (idle > ${WF_IDLE}m) =="
  for wf in "$HOME"/.claude/projects/*/*/subagents/workflows/wf_*; do
    [ -d "$wf" ] || continue
    if is_busy "$wf" "$WF_IDLE"; then echo "  skip   active  $wf"; else park workflows "$wf"; fi
  done
}

session_live() { # session_live <project-dirname> <session-id>
  local t="$HOME/.claude/projects/$1/$2.jsonl"
  [ -f "$t" ] && [ -n "$(find "$t" -mmin "-$SCRATCH_IDLE" -print -quit 2>/dev/null)" ]
}

cull_scratchpads() {
  echo "== scratchpads (idle > ${SCRATCH_IDLE}m, session transcript idle) =="
  [ -d "$SCRATCH_ROOT" ] || { echo "  (none: $SCRATCH_ROOT missing)"; return; }
  for sp in "$SCRATCH_ROOT"/*/*/scratchpad; do
    [ -d "$sp" ] || continue
    local sess proj; sess=$(basename "$(dirname "$sp")"); proj=$(basename "$(dirname "$(dirname "$sp")")")
    if is_busy "$sp" "$SCRATCH_IDLE" || session_live "$proj" "$sess"; then echo "  skip   active  $sp"; else park scratchpads "$sp"; fi
  done
}

cull_backup_builds() {
  echo "== backup-builds (regenerable dirs under ~/.agents/backups) =="
  [ -d "$HOME/.agents/backups" ] || return 0
  local names=(); for n in "${BUILD_DIRS[@]}"; do names+=(-o -name "$n"); done
  while read -r d; do park backup-builds "$d"; done < <(find "$HOME/.agents/backups" -type d \( -false "${names[@]}" \) -prune -print 2>/dev/null)
}

default_branch() { git -C "$1" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#origin/##' || true; }

cull_worktrees() {
  echo "== worktrees (merged, clean, 0 ahead) =="
  for root in "${REPO_ROOTS[@]}"; do
    [ -d "$root" ] || continue
    while read -r g; do
      local repo main; repo=$(dirname "$g"); main=$(default_branch "$repo"); [ -n "$main" ] || main=$(git -C "$repo" symbolic-ref --short HEAD 2>/dev/null || echo main)
      while read -r wt; do
        [ -d "$wt" ] || continue
        local br; br=$(git -C "$wt" branch --show-current 2>/dev/null || true)
        local dirty ahead; dirty=$(git -C "$wt" status --porcelain 2>/dev/null | wc -l | tr -d ' '); ahead=$(git -C "$repo" rev-list --count "$main..${br:-HEAD}" 2>/dev/null || echo 1)
        if [ -n "$br" ] && [ "$dirty" = 0 ] && [ "$ahead" = 0 ]; then
          park worktrees "$wt"
          if [ "$APPLY" = 1 ]; then git -C "$repo" worktree prune; git -C "$repo" branch -d "$br" >/dev/null 2>&1 && echo "  branch -d $br ($repo)"; fi
        else echo "  keep   $wt  branch=${br:-detached} dirty=$dirty ahead=$ahead"; fi
      done < <(git -C "$repo" worktree list --porcelain | awk '/^worktree /{print substr($0,10)}' | tail -n +2)
    done < <(find "$root" -maxdepth 4 -name .git -type d -not -path '*/node_modules/*' 2>/dev/null)
  done
}

cull_codex_sessions() {
  echo "== codex-sessions (months older than ${CODEX_KEEP}) =="
  [ -d "$HOME/.codex/sessions" ] || return 0
  local cutoff; cutoff=$(date -v-"${CODEX_KEEP}"m +%Y%m 2>/dev/null || date -d "-${CODEX_KEEP} months" +%Y%m)
  for m in "$HOME"/.codex/sessions/*/*; do
    [ -d "$m" ] || continue
    local ym; ym="$(basename "$(dirname "$m")")$(basename "$m")"
    if [ "$ym" -lt "$cutoff" ]; then park codex-sessions "$m"; fi
  done
}

# ---------- survey ----------
survey() {
  echo "== disk =="; df -h "$HOME" | tail -1
  echo "== top-level =="; du -sh "$HOME/.claude" "$HOME/.codex" "$HOME/.agents" "$SCRATCH_ROOT" 2>/dev/null
  echo "== claude project transcripts =="; du -sh "$HOME"/.claude/projects/* 2>/dev/null | sort -rh | head -8
  echo "== subagent workflow dirs =="; du -sh "$HOME"/.claude/projects/*/*/subagents/workflows 2>/dev/null | sort -rh | head -5
  echo "== scratchpads =="; du -sh "$SCRATCH_ROOT"/* 2>/dev/null | sort -rh | head -6
  echo "== agents backups =="; du -sh "$HOME"/.agents/backups/* 2>/dev/null | sort -rh | head -6
  echo "== codex =="; du -sh "$HOME"/.codex/sessions "$HOME"/.codex/logs_*.sqlite "$HOME"/.codex/cache 2>/dev/null | sort -rh
  echo "== plugin caches (reinstallable) =="; du -sh "$HOME"/.claude/plugins/marketplaces/* "$HOME"/.codex/plugins/cache/* 2>/dev/null | sort -rh | head -4
  echo "== worktrees =="; CATEGORIES=worktrees APPLY=0 cull_worktrees | grep -v '^==' || true
}

# ---------- main ----------
cmd="${1:-survey}"; shift || true
while [ $# -gt 0 ]; do case "$1" in
  --apply) APPLY=1;; --category) CATEGORIES="$2"; shift;; --wf-idle-min) WF_IDLE="$2"; shift;;
  --scratch-idle-min) SCRATCH_IDLE="$2"; shift;; --codex-keep-months) CODEX_KEEP="$2"; shift;;
  *) echo "unknown arg: $1" >&2; exit 2;; esac; shift; done

case "$cmd" in
  survey) survey;;
  cull)
    [ "$APPLY" = 1 ] && echo "APPLY: moving to $TRASH" || echo "DRY RUN (add --apply to move). Target: $TRASH"
    want workflows && cull_workflows
    want scratchpads && cull_scratchpads
    want backup-builds && cull_backup_builds
    want worktrees && cull_worktrees
    want codex-sessions && cull_codex_sessions
    [ "$EMPTY" -gt 0 ] && echo "($EMPTY empty directories ignored)"
    echo "== total: $(human "$TOTAL_BYTES") $([ "$APPLY" = 1 ] && echo "parked in $TRASH ($MOVED items). Empty Trash to reclaim." || echo "would be parked")";;
  *) sed -n 2,7p "$0"; exit 2;;
esac
