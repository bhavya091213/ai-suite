---
name: storage-cull
description: Reclaim disk space eaten by agent orchestration runs — Claude Code subagent workflow transcripts, session scratchpads, node_modules/.next inside retired backups, merged git worktrees and branches, Codex session logs. Use when the user says storage is bloated, disk is full, asks to cull/clean up caches or old worktrees, or when df shows the home volume above 90%. Never deletes — everything moves to a dated folder in ~/.Trash.
---

# Storage Cull

Agent orchestration leaves large residue behind: per-subagent transcripts, scratchpads full of venvs and model exports, backups that still contain `node_modules`, worktrees whose branch merged days ago. This skill finds it, proves it is idle, and parks it in Trash so the user can empty it.

## Hard rules

- **Never `rm`.** Every move goes to `~/.Trash/storage-cull-<date>/<category>/<original path>`, structure preserved. The user empties Trash; you do not.
- **Never touch a live session's working files** unless the user names that project. Live means: a `claude`/`codex` process has it as cwd, or files were written within the idle window.
- **Dry-run first, always.** Show the plan with sizes, then apply only on an explicit go-ahead or when the user already said "cull/clean it up".
- **Report space as "parked in Trash"**, not freed. `df` will not move until Trash is emptied; say so.

## Workflow

1. **Survey** — `scripts/cull.sh survey`. Prints sizes of every known cache location plus `df`. Lead the report with the three biggest items.
2. **Plan** — `scripts/cull.sh cull` (dry-run). Lists every path that would move, grouped by category, with the idle check it passed.
3. **Apply** — `scripts/cull.sh cull --apply [--category ...]`. Moves to Trash and prints totals.
4. **Report** — a short table: category, size, where it went. Then the one action the user must take: empty Trash.

## Where the bloat lives

| Category | Path pattern | Idle rule |
|---|---|---|
| `workflows` | `~/.claude/projects/*/<session>/subagents/workflows/wf_*` | no file written in 60 min |
| `scratchpads` | `/private/tmp/claude-501/<project>/<session>/scratchpad` | no file written in 24 h and session transcript idle |
| `backup-builds` | `node_modules`, `.next`, `dist`, `build`, `.venv`, `venv`, `__pycache__`, `target` under `~/.agents/backups/` | always safe; regenerable |
| `worktrees` | `git worktree list` in each repo under `~/Documents`, `~/Desktop`, `~/Downloads` | branch merged into default, working tree clean, no commits ahead |
| `codex-sessions` | `~/.codex/sessions/<year>/<month>` | month is older than 3 months |

Report-only (judgement call, never automated): `~/.codex/logs_*.sqlite`, plugin marketplace caches, `.orchestrate/*/qa*` screenshot folders in project repos, merged local branches without a worktree.

## Judgement notes

- A scratchpad can hold the only copy of an expensive artifact (a quantized model, a dataset). Name what is in it before moving it, so the user can rescue it from Trash.
- Removing a worktree is `mv` + `git worktree prune`. Only `git branch -d` (lowercase, merged-only) afterwards; never `-D`.
- `~/.agents/backups` exists *because* of the no-rm rule. Cull only the regenerable build output inside it, not the source it was created to preserve.
- Leave the live session you are running in alone, including its own scratchpad.

## Test

`tests/test_cull.sh` builds a fixture home, runs dry-run and apply, and asserts fresh files are skipped and idle ones land in Trash. Run it after editing the script.
