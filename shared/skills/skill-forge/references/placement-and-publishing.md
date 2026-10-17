# Placement and publishing for Phase 4

Paths below are repo paths. The repo mirrors the live setup: `shared/` installs to `~/.agents/`,
`claude-code/` to `~/.claude/`, `codex/` to `~/.codex/`. Shared skills are symlinked into both
tools by `install.sh`; nothing else needs to change in the installer for a new skill directory.

## 1. Decide the tree

| Put it in | When | Also |
| --- | --- | --- |
| `shared/skills/<name>/` | The body reads the same in both tools. This is the default. | Include `agents/openai.yaml`. Never copy it into a tool tree. |
| `claude-code/skills/<name>/` **and** `codex/skills/<name>/` | The body genuinely differs per tool: hooks, session-file layout, memory snapshots, slash-command syntax, a tool-specific installer. | Create **both** variants with the identical `name`. README scope is `claude + codex`. |

There is no single-tool row. `AGENTS.md` requires both variants "so neither CLI is left without
it". When the mechanism exists in one tool only (a Claude Code hook or plugin, Codex roles,
`~/.codex/memory/`, `~/.codex/scripts/codex-prompt`), still build the pair: the full variant for
the tool that has it, and for the other tool a variant that does the closest honest equivalent or
says plainly what it cannot do and what to use instead. Record which in the handback's open
follow-ups and in the commit body.

Rules of thumb:

- [ ] If two variants would be identical apart from the word "Claude" or "Codex", it is one
      shared skill that names both mechanisms in one body.
- [ ] If a variant pair later converges, collapse it into `shared/skills/` and `mv` the old
      copies to `~/.agents/backups/retired-<name>/`.
- [ ] `claude-code/skills/learned/` is reserved for `/learn` output. Nothing goes there by hand.
- [ ] Installed location after `./install.sh`: `~/.agents/skills/<name>` (shared, symlinked into
      `~/.claude/skills` and `~/.codex/skills`) or a real directory under `~/.claude/skills` /
      `~/.codex/skills` for a variant.

## 2. Move it into place

- [ ] The draft sits in the Phase 2 draft area (`<scratch>/skill-forge/<name>/`; a pair:
      `.../claude-code/<name>/` and `.../codex/<name>/`), not in the repo.
- [ ] Target free? `[ ! -e <tree>/skills/<name> ] || echo "TARGET EXISTS: back it up first"`.
      `mv <draft> <existing dir>` puts the draft *inside* the existing directory
      (`<tree>/skills/<name>/<name>/SKILL.md`), and the installer would then ship that nested copy.
- [ ] Target exists (the Phase 0 "extend" case): back the original up first, never delete it:
      `mkdir -p ~/.agents/backups/retired-<name> && mv <tree>/skills/<name> ~/.agents/backups/retired-<name>/<name>-$(date +%Y%m%d-%H%M%S)`
      then name that path in the handback's "Moved or retired".
- [ ] `mv <draft dir> <tree>/skills/<name>` (never `cp` for a shared skill, never `rm` the draft).
- [ ] Afterwards: `[ -f <tree>/skills/<name>/SKILL.md ] && [ ! -e <tree>/skills/<name>/<name> ]`.
- [ ] Directory name equals the frontmatter `name`.
- [ ] Nothing machine-specific inside: no expanded home-directory paths, no tokens, no absolute
      paths to this clone.

## 3. README table row

`README.md` lists every skill in a category table under `## Skills`. Add one row to the
matching category and keep rows alphabetical only where the table already is.

| Category heading | For |
| --- | --- |
| Orchestration, context & harness | workflow, subagent, context, skill-management skills |
| Engineering practice: quality, testing, security | TDD, review, verification, security |
| Languages & frameworks | one language or framework |
| Web, API & data platform | APIs, databases, cloud, GPU and runtime platforms |
| Research & knowledge | search, docs, notes, knowledge bases |
| Content & media | writing, slides, video, social |
| Business & career | fundraising, market, resume |

Row format (scope is `shared` or `claude + codex`; the description is one line, no trailing
full stop, written for someone who has not read the skill):

```
| <name> | shared | <What it does, in the README's voice> |
```

Then update every count the README states and that this change moved: the "N skills total",
"N shared" and "N platform-specific" numbers under `## Skills`, and the same numbers in
`docs/layout-and-sync.md` and `shared/README.md` / `codex/README.md` where they repeat. A stale
number is a bug. Check with:

```bash
ls shared/skills | wc -l
ls -d claude-code/skills/*/ | grep -v learned | wc -l
ls -d codex/skills/*/ | wc -l
grep -n "skills" README.md docs/layout-and-sync.md shared/README.md codex/README.md | grep -E '[0-9]+ '
```

## 4. skill-lock.json entry (adapted from upstream only)

When the skill was adapted from an external repo, record its provenance under the `"skills"`
object of `shared/skill-lock.json` so `npx skills check` can see it and a reader knows where it
came from.
Skip this for a skill written from scratch; set `origin: local` in its frontmatter instead.

```json
"<name>": {
  "source": "<owner>/<repo>",
  "sourceType": "github",
  "sourceUrl": "https://github.com/<owner>/<repo>.git",
  "skillPath": "<path to SKILL.md inside that repo>",
  "skillFolderHash": "<git tree hash of the upstream skill folder at the commit you adapted>",
  "installedAt": "<ISO 8601 UTC>",
  "updatedAt": "<ISO 8601 UTC>"
}
```

- [ ] Frontmatter `origin:` names the upstream (`ECC`, `community`, or `<owner>/<repo>`).
- [ ] The upstream licence allows the adaptation; say which licence in the commit body.
- [ ] `python3 -c "import json,sys;json.load(open(sys.argv[1]))" shared/skill-lock.json` passes.

## 5. Repo checks before the commit

```bash
# Frontmatter present everywhere (the repo's own snippet)
for f in shared/skills/*/SKILL.md claude-code/skills/*/SKILL.md codex/skills/*/SKILL.md; do
  grep -q '^name:' "$f" && grep -q '^description:' "$f" || echo "MISSING FRONTMATTER: $f"
done
# Every skill directory has a SKILL.md
for d in shared/skills/*/ codex/skills/*/; do [ -f "$d/SKILL.md" ] || echo "NO SKILL.md: $d"; done
# No personal home paths (expected: no output)
grep -rnE '/(Users|home)/[^/ "]+' . --exclude-dir=.git
# No credentials (expected: no output)
grep -rniE '(api[_-]?key|secret|token|password|bearer)[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9_\-]{16,}' . --exclude-dir=.git
# Installer still valid and its plan sane
bash -n install.sh && ./install.sh --dry-run --all
# YAML metadata parses (ruby ships with macOS; python3 needs PyYAML). Expect: four interface keys, one policy key
ruby -ryaml -e 'p YAML.load_file(ARGV[0])' <tree>/skills/<name>/agents/openai.yaml
```

## 6. Commit

Format: `<type>: <description>`, imperative, under ~72 characters, `type` one of `feat`, `fix`,
`refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

- [ ] Gate first: show `git status --short` for this skill's paths plus the section 5 output and
      wait for an explicit yes. Stage those paths by name; never `git add -A` or `git commit -a`,
      because the working tree may hold unrelated uncommitted work.
- [ ] New skill and its README row in **one** commit: `feat: add <name> skill`.
- [ ] A variant pair in one commit, both trees together.
- [ ] A `skill-lock.json` entry in the same commit as the skill it describes.
- [ ] Body (optional): what it does in two lines, upstream source and licence when adapted,
      anything moved to `~/.agents/backups/`.
- [ ] Never push, open a PR or tag without the user asking.

## 7. Install the result (separate gate, optional)

Installing is not part of the commit gate. Offer it after the commit and run it only on its own
explicit yes.

- [ ] `./install.sh --all` re-installs the whole working tree (`shared/`, `claude-code/`, `codex/`)
      onto the live `~/.agents`, `~/.claude` and `~/.codex`. It backs up what it replaces, but it
      also installs unrelated uncommitted changes, so show `./install.sh --dry-run --all` first
      and say that.
- [ ] Scoped alternative: `./install.sh skills install <name> --dry-run`, then the same without
      `--dry-run` (documented in `installer/ARCHITECTURE.md`, cli.py). For a shared skill it copies
      into `~/.agents/skills` and symlinks it into `~/.claude/skills` and `~/.codex/skills`. A
      variant pair needs one run per variant, with `--scope`.
- [ ] Confirm with `ls -l ~/.claude/skills/<name> ~/.codex/skills/<name>`.
- [ ] No yes: report `Installed: no` and leave the command for the user.
