"""Git awareness: detection, fetch, ahead/behind, changed paths, fast-forward pull.

Terminal-free - everything here returns data. Every subprocess call is an
argument list (never a shell), runs in ``paths.repo_dir`` with
``capture_output=True``, ``text=True``, ``check=False``, a timeout, and
``GIT_TERMINAL_PROMPT=0`` so a fetch can never hang on a credential prompt.
Any failure - missing binary, missing repo directory, timeout, non-zero exit -
is reported as data (``GitInfo.error`` or a ``(False, message)`` tuple); no
exception escapes. A ``paths.repo_dir`` that is not a directory is its own
error (never "git not found", even though ``subprocess`` raises the same
``FileNotFoundError`` for a bad ``cwd`` as for a bad binary), and path lists
are read from ``-z`` output so names with non-ASCII, quote or backslash
characters arrive literally instead of C-quoted (``core.quotePath``).

Every function accepts ``run`` (a ``subprocess.run``-compatible callable) and
``env`` (a *replacement* environment, like ``Paths.detect``; ``None`` means
``os.environ``) so tests can control both.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from installer.core.paths import REPO_SOURCE, Paths
from installer.core.types import GitInfo, RemoteChange

QUICK_TIMEOUT = 15.0  # rev-parse / status / log / diff
FETCH_TIMEOUT = 60.0
PULL_TIMEOUT = 120.0
DEFAULT_LOG_LIMIT = 50

MISSING_MESSAGE = "git not found on PATH"
NOT_REPO_MESSAGE = "not a git checkout"
MISSING_DIR_MESSAGE = "repo directory does not exist"
RECHECK_SENTENCE = (
    "then make sure `git` is on your PATH (or symlink it into ~/.local/bin) "
    "and press R to re-check"
)
FALLBACK_CLONE_URL = "https://github.com/bhavya091213/ai-suite.git"
_CLONE_RE = re.compile(r"git clone\s+((?:https?://|git@|ssh://)\S+)")

Runner = Callable[..., Any]


@dataclass(frozen=True)
class _Result:
    """Outcome of one git invocation."""

    ok: bool
    out: str = ""
    err: str = ""
    missing: bool = False  # the binary could not be executed at all
    no_repo_dir: bool = False  # paths.repo_dir is not a directory; nothing was run


# ------------------------------------------------------------------ plumbing


def _merge_env(env: Optional[Mapping[str, str]]) -> Dict[str, str]:
    merged = dict(os.environ if env is None else env)
    merged["GIT_TERMINAL_PROMPT"] = "0"
    return merged


def _no_repo_dir(paths: Paths) -> _Result:
    return _Result(False, err=f"{MISSING_DIR_MESSAGE}: {paths.repo_dir}", no_repo_dir=True)


def _git(paths: Paths, args: Sequence[str], run: Runner, env: Optional[Mapping[str, str]],
         timeout: float, strip: bool = True) -> _Result:
    """Run ``git <args>`` in the repo. Never raises.

    ``strip=False`` keeps stdout exactly as git wrote it (for ``-z`` output,
    where even a leading space belongs to the first path).
    """
    label = f"git {args[0]}" if args else "git"
    if not os.path.isdir(paths.repo_dir):
        return _no_repo_dir(paths)
    try:
        proc = run(["git", *args], cwd=paths.repo_dir, capture_output=True, text=True,
                   check=False, timeout=timeout, env=_merge_env(env))
    except FileNotFoundError as exc:
        if exc.filename == paths.repo_dir:  # chdir(cwd) failed, not the exec of git
            return _no_repo_dir(paths)
        return _Result(False, err=MISSING_MESSAGE, missing=True)
    except subprocess.TimeoutExpired:
        return _Result(False, err=f"{label} timed out after {timeout:g}s")
    except Exception as exc:  # noqa: BLE001 - contract: nothing escapes this module
        return _Result(False, err=f"{label} failed: {exc}")
    out = str(proc.stdout or "")
    if strip:
        out = out.strip()
    err = str(proc.stderr or "").strip()
    if proc.returncode != 0:
        return _Result(False, out=out, err=err or f"{label} exited with status {proc.returncode}")
    return _Result(True, out=out, err=err)


def _value(result: _Result) -> Optional[str]:
    """Stdout of a successful command, None when it failed or printed nothing."""
    return result.out if result.ok and result.out else None


def _lines(result: _Result) -> Tuple[str, ...]:
    if not result.ok:
        return ()
    return tuple(line for line in result.out.splitlines() if line.strip())


def _nul_fields(result: _Result) -> Tuple[str, ...]:
    """Fields of NUL-terminated (``-z``) output: literal paths, never C-quoted."""
    if not result.ok:
        return ()
    return tuple(field for field in result.out.split("\0") if field)


def _join(errors: Sequence[Optional[str]]) -> Optional[str]:
    text = "; ".join(e for e in errors if e)
    return text or None


def _strip_prefix(text: str, prefix: str) -> str:
    return text[len(prefix):] if text.startswith(prefix) else text


def _upstream(paths: Paths, run: Runner, env: Optional[Mapping[str, str]]) -> Optional[str]:
    return _value(_git(paths, ["rev-parse", "--abbrev-ref", "@{u}"], run, env, QUICK_TIMEOUT))


# -------------------------------------------------------------------- hints


def install_hint(platform: str = sys.platform) -> str:
    """How to get git on this platform. Always ends with the PATH / re-check sentence."""
    if platform == "darwin":
        command = "`xcode-select --install` (or `brew install git`)"
    elif platform.startswith("linux"):
        command = "`sudo apt install git` (Debian/Ubuntu) or `sudo dnf install git` (Fedora)"
    elif platform in ("win32", "cygwin", "msys"):
        command = "`winget install Git.Git`"
    else:
        command = "your package manager (see https://git-scm.com/downloads)"
    return f"install git with {command}, {RECHECK_SENTENCE}"


def clone_url(paths: Optional[Paths] = None) -> str:
    """The clone URL named in the repo README, falling back to the published one."""
    if paths is None:
        return FALLBACK_CLONE_URL
    readme = os.path.join(paths.repo_dir, "README.md")
    try:
        with open(readme, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                found = _CLONE_RE.search(line)
                if found:
                    return found.group(1)
    except OSError:
        pass
    return FALLBACK_CLONE_URL


def clone_hint(paths: Optional[Paths] = None) -> str:
    return ("this folder is not a git checkout; clone it to get update checks: "
            f"`git clone {clone_url(paths)}`")


def missing_dir_hint(paths: Optional[Paths] = None) -> str:
    return ("pass an existing checkout with `--repo PATH` (or run the installer from inside "
            f"one); to get a checkout: `git clone {clone_url(paths)}`")


def _repo_hint(upstream: Optional[str], branch: Optional[str], behind: int,
               last_fetch: Optional[float]) -> str:
    if upstream is None:
        target = f"origin/{branch}" if branch and branch != "HEAD" else "origin/<branch>"
        return f"no upstream to compare against; set one with `git branch --set-upstream-to={target}`"
    if behind > 0:
        return "run `git pull --ff-only` (P on the Updates tab) to fast-forward"
    if last_fetch is None:
        return "press F to fetch and check for updates"
    return ""


# ------------------------------------------------------------------- detect


def _blank(available: bool, message: str, hint: str, version: Optional[str] = None,
           error: Optional[str] = None) -> GitInfo:
    return GitInfo(available=available, version=version, is_repo=False, branch=None, head=None,
                   upstream=None, ahead=0, behind=0, dirty=False, last_fetch=None,
                   remote_url=None, message=message, hint=hint, error=error)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _summary(upstream: Optional[str], ahead: int, behind: int, last_fetch: Optional[float]) -> str:
    if upstream is None:
        base = "no upstream configured"
    elif behind > 0:
        base = f"{_plural(behind, 'commit')} behind {upstream} - updates available"
        if ahead > 0:
            base += f" ({_plural(ahead, 'commit')} ahead)"
    elif ahead > 0:
        base = f"{_plural(ahead, 'commit')} ahead of {upstream}"
    else:
        base = f"up to date with {upstream}"
    return base if last_fetch is not None else f"{base} - never fetched"


def _parse_counts(text: str) -> Tuple[int, int]:
    """'A<tab>B' from rev-list --left-right --count -> (ahead, behind)."""
    parts = text.split()
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 0, 0


def _fetch_head_mtime(paths: Paths, git_dir: Optional[str]) -> Optional[float]:
    if not git_dir:
        return None
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(paths.repo_dir, git_dir)
    try:
        return os.path.getmtime(os.path.join(git_dir, "FETCH_HEAD"))
    except OSError:
        return None


def _describe_repo(paths: Paths, version: Optional[str], errors: Tuple[str, ...], run: Runner,
                   env: Optional[Mapping[str, str]]) -> GitInfo:
    def quick(*args: str) -> _Result:
        return _git(paths, args, run, env, QUICK_TIMEOUT)

    branch = _value(quick("rev-parse", "--abbrev-ref", "HEAD")) \
        or _value(quick("symbolic-ref", "--short", "-q", "HEAD"))
    head = _value(quick("rev-parse", "--short", "HEAD"))
    upstream = _value(quick("rev-parse", "--abbrev-ref", "@{u}"))
    ahead, behind = 0, 0
    if upstream is not None:
        count = quick("rev-list", "--left-right", "--count", "HEAD...@{u}")
        if count.ok:
            ahead, behind = _parse_counts(count.out)
        else:
            errors += (count.err,)
    status = quick("status", "--porcelain")
    if not status.ok:
        errors += (status.err,)
    dirty = status.ok and bool(status.out)
    last_fetch = _fetch_head_mtime(paths, _value(quick("rev-parse", "--git-dir")))
    remote_url = _value(quick("remote", "get-url", "origin"))
    return GitInfo(available=True, version=version, is_repo=True, branch=branch, head=head,
                   upstream=upstream, ahead=ahead, behind=behind, dirty=dirty,
                   last_fetch=last_fetch, remote_url=remote_url,
                   message=_summary(upstream, ahead, behind, last_fetch),
                   hint=_repo_hint(upstream, branch, behind, last_fetch), error=_join(errors))


def detect(paths: Paths, env: Optional[Mapping[str, str]] = None,
           run: Runner = subprocess.run) -> GitInfo:
    """Describe the checkout at ``paths.repo_dir``. Never raises."""
    search_path = _merge_env(env).get("PATH")
    if shutil.which("git", path=search_path if search_path is not None else os.defpath) is None:
        return _blank(False, MISSING_MESSAGE, install_hint())
    version = _git(paths, ["--version"], run, env, QUICK_TIMEOUT)
    if version.missing:
        return _blank(False, MISSING_MESSAGE, install_hint())
    if version.no_repo_dir:
        return _blank(True, f"{MISSING_DIR_MESSAGE}: {paths.display(paths.repo_dir)}",
                      missing_dir_hint(paths), error=version.err)
    errors: Tuple[str, ...] = () if version.ok else (version.err,)
    version_text = _strip_prefix(version.out, "git version ") if version.ok else None
    inside = _git(paths, ["rev-parse", "--is-inside-work-tree"], run, env, QUICK_TIMEOUT)
    if not inside.ok or inside.out != "true":
        if not inside.ok and "not a git repository" not in inside.err.lower():
            errors += (inside.err,)
        return _blank(True, NOT_REPO_MESSAGE, clone_hint(paths), version_text, _join(errors))
    return _describe_repo(paths, version_text, errors, run, env)


# ------------------------------------------------------------ fetch / pull


def fetch(paths: Paths, run: Runner = subprocess.run, timeout: float = FETCH_TIMEOUT,
          env: Optional[Mapping[str, str]] = None) -> GitInfo:
    """``git fetch --prune`` then ``detect``. A failed fetch lands in ``GitInfo.error``."""
    result = _git(paths, ["fetch", "--prune"], run, env, timeout)
    info = detect(paths, env=env, run=run)
    if result.ok:
        return info
    return replace(info, error=_join((info.error, f"fetch failed: {result.err}")))


def pull_ff(paths: Paths, run: Runner = subprocess.run, timeout: float = PULL_TIMEOUT,
            env: Optional[Mapping[str, str]] = None) -> Tuple[bool, str]:
    """``git pull --ff-only``. Returns (ok, message); never raises."""
    result = _git(paths, ["pull", "--ff-only"], run, env, timeout)
    if not result.ok:
        return False, result.err or result.out or "git pull --ff-only failed"
    return True, result.out or result.err or "pull --ff-only completed"


# ------------------------------------------------------- what changed upstream


def _diff_names(paths: Paths, upstream: str, run: Runner,
                env: Optional[Mapping[str, str]]) -> Tuple[str, ...]:
    # -z: NUL-terminated, unquoted names. Without it git C-quotes any path holding
    # a byte > 0x7F, a double quote, a backslash or a control character (default
    # core.quotePath), and "shared/skills/caf\303\251/" never matches a prefix.
    args = ["diff", "--name-only", "-z", f"HEAD...{upstream}"]
    return _nul_fields(_git(paths, args, run, env, QUICK_TIMEOUT, strip=False))


def _log_behind(paths: Paths, upstream: str, run: Runner, env: Optional[Mapping[str, str]],
                limit: int, path: Optional[str] = None) -> Tuple[str, ...]:
    args = ["log", "--oneline", "--no-decorate", "--no-color", f"--max-count={int(limit)}",
            f"HEAD..{upstream}"]
    if path:
        args += ["--", path]
    return _lines(_git(paths, args, run, env, QUICK_TIMEOUT))


def changed_paths(paths: Paths, run: Runner = subprocess.run,
                  env: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """Repo-relative paths changed in ``HEAD...<upstream>`` (empty without an upstream)."""
    upstream = _upstream(paths, run, env)
    if upstream is None:
        return ()
    return _diff_names(paths, upstream, run, env)


def commits_behind(paths: Paths, run: Runner = subprocess.run, limit: int = DEFAULT_LOG_LIMIT,
                   env: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """``git log --oneline HEAD..<upstream>`` lines, newest first (empty without an upstream)."""
    upstream = _upstream(paths, run, env)
    if upstream is None:
        return ()
    return _log_behind(paths, upstream, run, env, limit)


def skill_prefix(scope: str, name: str) -> Optional[str]:
    """Repo-relative, slash-terminated prefix of a catalog entry, e.g. ``shared/skills/alpha/``."""
    source = REPO_SOURCE.get(scope)
    if source is None or not name:
        return None
    return f"{source.replace(os.sep, '/')}/{name}/"


def remote_changes(paths: Paths, catalog: Mapping[Tuple[str, str], Any],
                   run: Runner = subprocess.run, env: Optional[Mapping[str, str]] = None,
                   limit: int = DEFAULT_LOG_LIMIT) -> Dict[Tuple[str, str], RemoteChange]:
    """Map upstream-changed paths onto catalog keys by ``<REPO_SOURCE[scope]>/<name>/``."""
    upstream = _upstream(paths, run, env)
    if upstream is None:
        return {}
    files = _diff_names(paths, upstream, run, env)
    if not files:
        return {}
    changes: Dict[Tuple[str, str], RemoteChange] = {}
    for key in catalog:
        prefix = skill_prefix(*key) if isinstance(key, tuple) and len(key) == 2 else None
        if prefix is None:
            continue
        touched = tuple(f for f in files if f.startswith(prefix))
        if not touched:
            continue
        commits = _log_behind(paths, upstream, run, env, limit, path=prefix.rstrip("/"))
        changes[key] = RemoteChange(upstream=upstream, files=touched, commits=commits)
    return changes
