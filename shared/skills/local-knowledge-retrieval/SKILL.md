---
name: local-knowledge-retrieval
description: Discover, index, and retrieve bounded context from repository-local knowledge sources before acting. Use when a repo may contain an Obsidian vault, docs, wiki, notes, handbook, playbooks, markdown collections, or project documentation; when spawning subagents that need project context; when creating or updating skills from repo knowledge; and when the user asks agents to search local notes or use the repo knowledge base without loading everything into context.
---

# Local Knowledge Retrieval

When the user does not name a vault, use the default vault listed under 'Environment & defaults' in ~/.agents/RULES.md (set it with ./install.sh → Settings).

Use this skill as a context acquisition layer. The goal is to search first, retrieve second, and reason third without stuffing a whole vault or documentation tree into the prompt.

## Protocol

1. Discover local knowledge sources from the repository root:
   - `.obsidian/`
   - `vault/`
   - `knowledge/`
   - `docs/`
   - `wiki/`
   - `notes/`
   - `handbook/`
   - `playbooks/`
   - markdown collections such as `*.md`, `*.mdx`, and `*.markdown`
2. Build or update the index before retrieval. Do not re-index unchanged files.
3. Generate 1-3 focused search queries from the task, using project terms from the user prompt and parent handoff.
4. Retrieve only the top relevant chunks, preferring headings, sections, note summaries, tags, aliases, and graph neighbors.
5. Merge retrieved chunks with the user prompt, parent-agent context, and task files.
6. Stop when the context budget is reached. Prefer relevance density over token volume.

Failure to check an obvious local knowledge source before working is a protocol miss unless the task is completely self-contained.

## Tool

Run the bundled search helper from the repository root (it ships with this skill, so it works under Claude Code and Codex alike):

```bash
python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py search "task or question"
```

Codex installs also expose the same helper as `~/.codex/scripts/codex-knowledge`.

Useful commands:

```bash
python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py discover --format markdown
python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py index
python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py search "authentication runbook" --limit 5 --max-chars 8000
python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py search "Obsidian Bases formulas" --format json
```

The helper stores SQLite FTS indexes under `~/.codex/cache/knowledge/`, keyed by repository path, so repositories are not dirtied by generated index files. That cache location is used whichever CLI runs the helper; no Codex install is required.

## Ranking Signals

Prefer chunks with:

- direct keyword overlap with the task
- heading/title matches
- matching frontmatter tags or aliases
- backlinks or wikilinks from relevant Obsidian notes
- relevant directory placement such as `docs/`, `knowledge/`, `playbooks/`, or a vault root
- recent modification time when recency matters

For Obsidian vaults, parse and use:

- `[[wikilinks]]`
- `#tags`
- YAML frontmatter
- aliases
- backlinks
- folder hierarchy

Use graph-neighbor retrieval sparingly: first retrieve matching chunks, then add directly linked or backlinking notes only when they improve the answer.

## Token-Efficient Defaults

- Small task: `--limit 3 --max-chars 4000`
- Normal task: `--limit 5 --max-chars 8000`
- Complex cross-cutting task: `--limit 8 --max-chars 12000`
- Prefer `rg -n "term"` and `sed -n 'start,endp'` for known files.
- Do not load whole dashboards, ticket indexes, or vault folders just to find one fact.
- Stop retrieval when you can identify target files, risks, and verification commands.
- If a parent prompt already includes a long handoff, search for deltas instead of rereading the same notes.

## Context Budgets

Keep retrieved knowledge bounded. Defaults:

- `--limit 5`
- `--max-chars 8000`
- about 60% retrieved knowledge, 30% task files, 10% instructions/handoff metadata

If the task is small, retrieve less. Do not use the whole budget just because it exists.

## Agent Handoff

When spawning a subagent, include a compact retrieval block:

```markdown
## Knowledge Retrieval
- root: <repo root>
- command: python3 ~/.agents/skills/local-knowledge-retrieval/scripts/knowledge_index.py search "<query>" --limit <n> --max-chars <budget>
- sources: <vault/docs/wiki/notes paths used>
- selected: <path#heading entries>
- gaps: <missing context to re-query, or "none">
```

Child agents should re-query with their specific task, not blindly inherit irrelevant chunks. Give them the retrieval command and selected source names, not full retrieved text unless it is essential.

For subagents whose primary output is Markdown, Obsidian notes, docs, prompt recipes, or `SKILL.md` files, route to the `markdown_writer` agent role when available (a Codex role; under Claude Code spawn a light-tier subagent instead). That role is intentionally lower model/effort for Markdown production.

## Fallbacks

If the helper is unavailable, use:

```bash
rg --files -g '*.md' -g '*.mdx' -g '*.markdown' -g '*.base' -g '*.canvas'
rg -n "keyword|another keyword" docs wiki knowledge notes handbook playbooks .
```

Still load sections and chunks, not entire vaults, unless a specific full file is clearly required.
