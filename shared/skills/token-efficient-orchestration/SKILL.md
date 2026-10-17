---
name: token-efficient-orchestration
description: Use when coordinating Codex subagents, Trello tickets, Obsidian project memory, CI verification, or long-running project work where context and token cost must be minimized. Enforces bounded retrieval, small prompts, no watcher loops by default, concise vault updates, and explicit completion gates.
---

# Token-Efficient Orchestration

When the user does not name a vault, use the default vault listed under 'Environment & defaults' in ~/.agents/RULES.md (set it with ./install.sh → Settings).

Use this skill before spawning agents or updating orchestration memory.

## Defaults

- Prefer one local action over a subagent when the task is blocking, small, or tightly coupled.
- Spawn subagents only for bounded, non-overlapping work with clear file ownership.
- Do not start long-running watcher agents unless the user explicitly asks.
- Cap each agent prompt to the minimum needed context: task, repo/vault paths, allowed scope, required evidence, and stop conditions.
- Tell agents to re-query local knowledge for their exact task instead of inheriting broad parent context.
- Tell agents to update one concise agent note, not many dashboard/index files, unless status materially changed.
- Close completed agents promptly.

## Retrieval Budget

- First use `rg`, `rg --files`, or `python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py search` (the local-knowledge-retrieval helper; plain `rg` is the fallback when it is unavailable).
- Default search budget: `--limit 5 --max-chars 8000`.
- For small tasks: `--limit 3 --max-chars 4000`.
- Read file slices with `sed -n`, not whole large files.
- Stop reading when you can name the target files, test command, and risk.

## Subagent Prompt Contract

Include only:

- Task and ticket ID.
- Repo and vault paths.
- Allowed write scope and protected files.
- 3-6 required reads, not whole folder lists.
- Focused retrieval command.
- Exact verification command expectations.
- Vault note to update.
- Stop conditions: too broad, schema needed, remote state unavailable, or conflicting dirty files.

Avoid:

- Large copied handoffs.
- Full ticket indexes.
- Multiple redundant skills.
- Background monitoring instructions.
- Asking agents to keep watching unless explicitly needed.

## Vault Memory

- The vault should make future sessions cheaper: write concise state, links, evidence, and next actions.
- Prefer index notes over dense cross-linking.
- Use `Related` sections with 3-8 high-signal links.
- Record local verification separately from remote CI.
- Do not duplicate long command logs; summarize result and point to the command.

## Completion

Before reporting done:

- Verify every running agent is either still needed or closed.
- Report active agents by objective, not by transcript.
- Report exact local checks and remote-state limits.
