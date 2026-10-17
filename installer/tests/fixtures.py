"""Deterministic fake repo + fake home used by every test module.

Layout produced by make_repo(root)  (root/repo):
  shared/skills/alpha            valid, 2 files (SKILL.md, references/notes.md)
  shared/skills/beta             valid, 1 file
  shared/skills/dup              valid                 <- ALSO in claude-code (repo-level duplicate)
  claude-code/skills/gamma       valid (claude variant)
  claude-code/skills/dup         valid (duplicate of shared/dup)
  claude-code/skills/learned/.gitkeep                  <- not a skill
  claude-code/skills/nometa      SKILL.md without frontmatter
  codex/skills/gamma             valid (codex variant, different body)
  codex/skills/badname           frontmatter name "other-name" (name mismatch)

Layout produced by make_home(root, repo)  (root/home):
  ~/.agents/skills/alpha         identical copy of repo alpha           -> INSTALLED
  ~/.agents/skills/beta          repo beta with SKILL.md edited         -> MODIFIED
  ~/.agents/skills/foreign1      valid skill not in repo                -> FOREIGN
  ~/.claude/skills/alpha         symlink ../../.agents/skills/alpha     -> link OK
  ~/.claude/skills/beta          REAL DIR, identical to repo beta       -> REAL_DIR duplicate copy
  ~/.claude/skills/gamma         identical copy of claude-code gamma    -> INSTALLED
  ~/.claude/skills/ghost         symlink to missing target              -> broken symlink (FOREIGN w/ issue)
  ~/.claude/skills/synced/...    tool-managed                           -> IGNORED
  ~/.claude/skills/learned/      empty                                  -> IGNORED
  ~/.codex/skills/alpha          symlink to ABSOLUTE agents path        -> link OK (resolves correctly)
  ~/.codex/skills/beta           symlink to /nonexistent                -> link BROKEN
  ~/.codex/skills/gamma          codex gamma with extra file            -> MODIFIED
  ~/.codex/skills/.system/...    tool-managed                           -> hidden/IGNORED
  ~/.codex/skills/stray.txt      plain file                             -> kind "file", issue
"""

from __future__ import annotations

import os
import shutil
from typing import Mapping, Optional

from installer.core.paths import Paths

FRONTMATTER = "---\nname: {name}\ndescription: {description}\n---\n"


def write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def make_skill(parent: str, name: str, description: Optional[str] = None,
               body: str = "# Body\n", extra: Optional[Mapping[str, str]] = None,
               frontmatter: Optional[str] = None) -> str:
    """Create <parent>/<name>/SKILL.md (+ extra relative files). Returns the dir."""
    skill_dir = os.path.join(parent, name)
    fm = FRONTMATTER.format(name=name, description=description or f"{name} does things") \
        if frontmatter is None else frontmatter
    write(os.path.join(skill_dir, "SKILL.md"), fm + body)
    for rel, text in (extra or {}).items():
        write(os.path.join(skill_dir, rel), text)
    return skill_dir


def make_repo(root: str) -> str:
    repo = os.path.join(root, "repo")
    shared = os.path.join(repo, "shared", "skills")
    claude = os.path.join(repo, "claude-code", "skills")
    codex = os.path.join(repo, "codex", "skills")

    make_skill(shared, "alpha", "Alpha skill for testing", extra={"references/notes.md": "alpha notes\n"})
    make_skill(shared, "beta", "Beta skill for testing")
    make_skill(shared, "dup", "Duplicated in shared and claude")

    make_skill(claude, "gamma", "Gamma (Claude variant)", body="# Claude body\n")
    make_skill(claude, "dup", "Duplicated in shared and claude")
    write(os.path.join(claude, "learned", ".gitkeep"), "")
    make_skill(claude, "nometa", frontmatter="", body="# No frontmatter here\n")

    make_skill(codex, "gamma", "Gamma (Codex variant)", body="# Codex body\n")
    make_skill(codex, "badname", frontmatter=FRONTMATTER.format(name="other-name", description="Mismatch"))

    # a stray file that must be ignored by the catalog
    write(os.path.join(shared, ".DS_Store"), "junk")
    return repo


def make_home(root: str, repo: str) -> str:
    home = os.path.join(root, "home")
    agents = os.path.join(home, ".agents", "skills")
    claude = os.path.join(home, ".claude", "skills")
    codex = os.path.join(home, ".codex", "skills")
    for d in (agents, claude, codex):
        os.makedirs(d, exist_ok=True)

    # ~/.agents/skills
    shutil.copytree(os.path.join(repo, "shared", "skills", "alpha"), os.path.join(agents, "alpha"))
    shutil.copytree(os.path.join(repo, "shared", "skills", "beta"), os.path.join(agents, "beta"))
    write(os.path.join(agents, "beta", "SKILL.md"),
          FRONTMATTER.format(name="beta", description="Beta skill for testing") + "# Body\n\nlocal edit\n")
    make_skill(agents, "foreign1", "Not in the repo")

    # ~/.claude/skills
    os.symlink(os.path.join("..", "..", ".agents", "skills", "alpha"), os.path.join(claude, "alpha"))
    shutil.copytree(os.path.join(repo, "shared", "skills", "beta"), os.path.join(claude, "beta"))
    shutil.copytree(os.path.join(repo, "claude-code", "skills", "gamma"), os.path.join(claude, "gamma"))
    os.symlink(os.path.join("..", "..", ".agents", "skills", "does-not-exist"), os.path.join(claude, "ghost"))
    write(os.path.join(claude, "synced", "bucket-1", "pdf", "SKILL.md"),
          FRONTMATTER.format(name="pdf", description="synced") + "x\n")
    os.makedirs(os.path.join(claude, "learned"), exist_ok=True)

    # ~/.codex/skills
    os.symlink(os.path.join(agents, "alpha"), os.path.join(codex, "alpha"))  # absolute, still correct
    os.symlink("/nonexistent/target/beta", os.path.join(codex, "beta"))
    shutil.copytree(os.path.join(repo, "codex", "skills", "gamma"), os.path.join(codex, "gamma"))
    write(os.path.join(codex, "gamma", "extra.md"), "extra\n")
    write(os.path.join(codex, ".system", "imagegen", "SKILL.md"),
          FRONTMATTER.format(name="imagegen", description="system") + "x\n")
    write(os.path.join(codex, "stray.txt"), "not a skill\n")
    return home


def paths_for(root: str, repo: Optional[str] = None, home: Optional[str] = None) -> Paths:
    repo = repo or os.path.join(root, "repo")
    home = home or os.path.join(root, "home")
    return Paths(
        repo_dir=repo,
        agents_home=os.path.join(home, ".agents"),
        claude_home=os.path.join(home, ".claude"),
        codex_home=os.path.join(home, ".codex"),
    )


def build(root: str) -> Paths:
    """make_repo + make_home in one call."""
    repo = make_repo(root)
    make_home(root, repo)
    return paths_for(root)
