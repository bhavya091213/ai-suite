#!/usr/bin/env bash
# Fixture test for cull.sh: idle items move, fresh items stay, nothing is ever rm'd.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); CULL="$HERE/../scripts/cull.sh"
FX=$(mktemp -d); export HOME="$FX/home" CULL_SCRATCH_ROOT="$FX/scratch" CULL_TRASH="$FX/trash" CULL_REPO_ROOTS="$FX/home/Documents"
fail() { echo "FAIL: $*"; exit 1; }
old() { touch -t 202601010000 "$@"; }

# workflows: one idle, one fresh
WF="$HOME/.claude/projects/-p/sess1/subagents/workflows"; mkdir -p "$WF/wf_old" "$WF/wf_new"
echo x > "$WF/wf_old/a.jsonl"; old "$WF/wf_old/a.jsonl"; echo x > "$WF/wf_new/a.jsonl"
# scratchpads: idle with idle transcript, idle with live transcript
mkdir -p "$CULL_SCRATCH_ROOT/-p/sess1/scratchpad" "$CULL_SCRATCH_ROOT/-p/sess2/scratchpad"
echo x > "$CULL_SCRATCH_ROOT/-p/sess1/scratchpad/big.bin"; old "$CULL_SCRATCH_ROOT/-p/sess1/scratchpad/big.bin"
echo x > "$CULL_SCRATCH_ROOT/-p/sess2/scratchpad/big.bin"; old "$CULL_SCRATCH_ROOT/-p/sess2/scratchpad/big.bin"
mkdir -p "$HOME/.claude/projects/-p"; echo x > "$HOME/.claude/projects/-p/sess1.jsonl"; old "$HOME/.claude/projects/-p/sess1.jsonl"; echo x > "$HOME/.claude/projects/-p/sess2.jsonl"
# backup builds
mkdir -p "$HOME/.agents/backups/retired-x/node_modules/pkg" "$HOME/.agents/backups/retired-x/src"; echo x > "$HOME/.agents/backups/retired-x/src/keep.ts"; echo x > "$HOME/.agents/backups/retired-x/node_modules/pkg/index.js"
# worktrees: merged+clean vs unmerged
R="$HOME/Documents/repo"; mkdir -p "$R"; git -C "$R" init -q -b main; git -C "$R" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$R" worktree add -q "$R/.claude/worktrees/merged" -b merged >/dev/null
git -C "$R" worktree add -q "$R/.claude/worktrees/unmerged" -b unmerged >/dev/null; git -C "$R/.claude/worktrees/unmerged" -c user.email=t@t -c user.name=t commit -q --allow-empty -m work
# codex sessions
mkdir -p "$HOME/.codex/sessions/2025/01" "$HOME/.codex/sessions/$(date +%Y)/$(date +%m)"; echo x > "$HOME/.codex/sessions/2025/01/s.jsonl"

out=$("$CULL" cull); echo "$out" | grep -q 'DRY RUN' || fail "dry-run banner"
[ -d "$WF/wf_old" ] || fail "dry-run moved something"
out=$("$CULL" cull --apply); echo "$out"
[ ! -d "$WF/wf_old" ] || fail "idle workflow not moved"; [ -d "$WF/wf_new" ] || fail "fresh workflow moved"
[ ! -d "$CULL_SCRATCH_ROOT/-p/sess1/scratchpad" ] || fail "idle scratchpad not moved"
[ -d "$CULL_SCRATCH_ROOT/-p/sess2/scratchpad" ] || fail "live-session scratchpad moved"
[ ! -d "$HOME/.agents/backups/retired-x/node_modules" ] || fail "node_modules not moved"; [ -f "$HOME/.agents/backups/retired-x/src/keep.ts" ] || fail "source removed"
[ ! -d "$R/.claude/worktrees/merged" ] || fail "merged worktree not moved"; [ -d "$R/.claude/worktrees/unmerged" ] || fail "unmerged worktree moved"
git -C "$R" branch | grep -q unmerged || fail "unmerged branch deleted"; ! git -C "$R" branch | grep -q ' merged' || fail "merged branch kept"
[ ! -d "$HOME/.codex/sessions/2025/01" ] || fail "old codex month not moved"; [ -d "$HOME/.codex/sessions/$(date +%Y)/$(date +%m)" ] || fail "current codex month moved"
T=$(ls -d "$CULL_TRASH"/storage-cull-*); [ -f "$T/workflows/.claude/projects/-p/sess1/subagents/workflows/wf_old/a.jsonl" ] || fail "trash structure not preserved"
[ -f "$T/scratchpads/$(echo "$CULL_SCRATCH_ROOT" | sed "s#^$HOME/##")/-p/sess1/scratchpad/big.bin" ] || [ -n "$(find "$T/scratchpads" -name big.bin)" ] || fail "scratchpad not in trash"
echo "PASS"; mv "$FX" "${TMPDIR:-/tmp}/storage-cull-test-$(date +%s)"
