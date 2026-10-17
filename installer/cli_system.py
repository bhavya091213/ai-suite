"""Machine-level commands: tui, apply, settings-sync and doctor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Callable, List, Tuple

from installer.cli_config import TOOLS, build_context, probe_caps
from installer.cli_io import (
    EXIT_FAIL, EXIT_OK, Ctx, confirm, dump_json, emit, failure, read_text, warn,
)
from installer.core import apply_settings, capabilities, claude_settings, config, extras, git
from installer.core.paths import Paths

MIN_PYTHON = (3, 9)
Finding = Tuple[str, str]  # (level, text); level is "ok" | "warn" | "fail"
_JSON_STATES = {"ok": "ok", "warn": "warn", "fail": "blocker"}  # --json calls a failure a blocker
Plan = apply_settings.SettingsPlan
INSTALL_SCRIPT = "install.sh"


# ---------------------------------------------------------------------- tui


def cmd_tui(ctx: Ctx) -> int:
    """Start the curses installer. The import is lazy so headless commands never load curses."""
    try:
        from installer.tui import run
    except Exception as exc:  # ImportError, or curses missing on this platform
        warn(f"cannot start the interactive installer: {exc}")
        warn("use the headless commands instead, e.g. 'python3 -m installer status'")
        return EXIT_FAIL
    try:
        return int(run(ctx.paths) or 0)
    except Exception as exc:  # curses.error on a dumb terminal, etc.
        warn(f"the interactive installer stopped: {exc}")
        return EXIT_FAIL


# -------------------------------------------------------------------- apply


def _spawn(argv: List[str], script: str, cwd: str, env: dict) -> subprocess.Popen:
    options = dict(cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   universal_newlines=True, errors="replace")
    try:
        return subprocess.Popen(argv, **options)
    except PermissionError:  # the script lost its executable bit: run it through bash
        return subprocess.Popen(["bash", script] + argv[1:], **options)


def _config_was_saved(ctx: Ctx) -> bool:
    """Whether ~/.agents/config.json is on disk right now. `apply` asks this before install.sh
    runs, because install.sh creates that file from the example when it is absent."""
    return config.load(ctx.paths).exists


def _emit_sync_skipped(ctx: Ctx) -> int:
    shown = ctx.paths.display(config.load(ctx.paths).path)
    emit(f"Settings sync: skipped. {shown} did not exist before this run, so the defaults install.sh "
         "puts there were not pushed into settings.json / config.toml (they could overwrite values you set "
         "by hand).")
    emit("Review that file, then run 'settings-sync' to copy it into the existing tool files.")
    return EXIT_OK


def cmd_apply(ctx: Ctx) -> int:
    """Run ./install.sh --headless --auto from the repo root, then sync settings into existing files.

    Defaults must not replace what is in settings.json and config.toml, so the sync is cautious
    in two ways. It only runs when a config file was already saved before the run (one that
    install.sh itself just created holds nothing but defaults). And it pushes only the values
    that differ from the defaults, on every run: the example install.sh copies into place stays
    all-defaults until you edit it, and the run after the first would otherwise push it.
    Files that differ from a default-valued setting are listed, not changed. (`settings-sync` on
    its own always works from the whole current file, after showing the diff and asking.)
    """
    script = os.path.join(ctx.paths.repo_dir, INSTALL_SCRIPT)
    if not os.path.isfile(script):
        raise failure(f"{ctx.paths.display(script)} not found")
    dry_run = bool(ctx.flag("dry_run"))
    saved_before = _config_was_saved(ctx)
    argv = [script, "--headless", "--auto"] + (["--dry-run"] if dry_run else [])
    emit(f"Plan: ./{INSTALL_SCRIPT} {' '.join(argv[1:])}  (in {ctx.paths.display(ctx.paths.repo_dir)})")
    if saved_before:
        emit("      then: copy the hook and subagent settings you changed from the defaults into the "
             "existing settings.json and config.toml")
    else:
        emit("      then: nothing - no saved config yet, so settings.json and config.toml are left as they are")
    if not dry_run and not confirm(ctx.args):
        emit("Aborted.")
        return EXIT_FAIL
    try:
        proc = _spawn(argv, script, ctx.paths.repo_dir, dict(ctx.env))
    except OSError as exc:
        raise failure(f"cannot run {INSTALL_SCRIPT}: {exc}")
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    code = proc.wait()
    if code != 0:
        emit(f"{INSTALL_SCRIPT} exited with status {code}; settings were not synced")
        return EXIT_FAIL
    emit("")
    return _sync_settings(ctx, after_install=True) if saved_before else _emit_sync_skipped(ctx)


# ------------------------------------------------------------ settings-sync


def _settings_plans(ctx: Ctx, skip_defaults: bool) -> Tuple[Plan, Plan]:
    """(plan to apply, plan covering every managed key); the same object unless `skip_defaults`.

    Compares the saved config with the existing tool files. A config that cannot be trusted
    (unreadable, or never saved) syncs nothing, because defaults must not overwrite your edits.
    """
    paths = ctx.paths
    cfg = config.load(paths)
    if cfg.error:
        reason = f"{paths.display(cfg.path)} cannot be read ({cfg.error}); nothing was synced"
        blocked = Plan((), ((apply_settings.SKIP, reason),))
        return blocked, blocked
    if not cfg.exists:
        nothing = Plan((), ())
        return nothing, nothing
    context = build_context(ctx, cfg, probe_caps(ctx, only=TOOLS))
    everything = apply_settings.plan(cfg.data, context, paths)
    if not skip_defaults:
        return everything, everything
    return apply_settings.plan(cfg.data, context, paths, skip_defaults=True), everything


def _held_back(ctx: Ctx, pushed: Plan, everything: Plan) -> Tuple[str, ...]:
    """Files that `settings-sync` would change further than `pushed` does (shown paths)."""
    sent = {(change[0], change[2]) for change in pushed.changes}
    return tuple(ctx.paths.display(change[0]) for change in everything.changes if (change[0], change[2]) not in sent)


def _emit_held_back(ctx: Ctx, held: Tuple[str, ...]) -> None:
    if not held:
        return
    emit("Settings sync: kept as they are because config.json has the default value for a setting in them: "
         + ", ".join(held))
    emit("  apply pushes only values you changed from the defaults; "
         "run 'settings-sync' to see the difference and push everything.")


def _print_settings_plan(result: Plan, ctx: Ctx) -> None:
    emit(f"Settings sync ({len(result.changes)} file(s) to change):")
    for change in result.changes:
        emit(f"  change  {ctx.paths.display(change[0])}")
        for line in apply_settings.diff_lines(change, ctx.paths.display(change[0])):
            emit(f"    {line}")
    for level, text in result.problems:
        emit(f"  {level}    {text}")


def _print_outcomes(outcomes: Tuple[apply_settings.Outcome, ...], ctx: Ctx, backup_root: str) -> int:
    for outcome in outcomes:
        shown = ctx.paths.display(outcome.path)
        emit(f"  ok    updated {shown}" if outcome.ok else f"  FAIL  update {shown}: {outcome.message}")
    if any(outcome.backup for outcome in outcomes):
        emit(f"Backups went under: {ctx.paths.display(backup_root)}")
    failed = sum(1 for outcome in outcomes if not outcome.ok)
    if failed:
        emit(f"{failed} file(s) were not updated.")
        return EXIT_FAIL
    emit("Done.")
    return EXIT_OK


def _sync_settings(ctx: Ctx, after_install: bool) -> int:
    """Print the settings plan and apply it.

    `settings-sync` on its own (`after_install` False) pushes every managed key and asks first.
    After install.sh (`apply`, which already asked before it ran) only values changed from the
    defaults are pushed, and what that leaves behind is listed.
    """
    pushed, everything = _settings_plans(ctx, skip_defaults=after_install)
    held = _held_back(ctx, pushed, everything) if after_install else ()
    if not pushed.changes:
        for level, text in pushed.problems:
            emit(f"  {level}    {text}")
        emit("Settings sync: nothing to do.")
        _emit_held_back(ctx, held)
        return EXIT_OK
    _print_settings_plan(pushed, ctx)
    if ctx.flag("dry_run"):
        emit("Dry run only; nothing was changed.")
        _emit_held_back(ctx, held)
        return EXIT_OK
    if not after_install and not confirm(ctx.args, "Apply these settings changes?"):
        emit("Aborted.")
        return EXIT_FAIL
    backup_root = ctx.paths.backup_root("settings-sync")
    outcomes = apply_settings.apply(pushed.changes, backup_root, home=ctx.env.get("HOME"))
    code = _print_outcomes(outcomes, ctx, backup_root)
    _emit_held_back(ctx, held)
    return code


def cmd_settings_sync(ctx: Ctx) -> int:
    """Copy guardrails.hook_profile / disabled_hooks and subagents.codex.* into existing tool files."""
    return _sync_settings(ctx, after_install=False)


# ------------------------------------------------------------------- doctor


def _check_python() -> List[Finding]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return [("fail", f"python {version}: need {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer")]
    return [("ok", f"python {version}")]


def _check_curses() -> List[Finding]:
    try:
        import curses  # noqa: F401
    except ImportError as exc:
        return [("warn", f"curses unavailable ({exc}); the TUI will not start, headless commands still work")]
    return [("ok", "curses available (interactive installer can run)")]


def _check_git(paths: Paths) -> List[Finding]:
    info = git.detect(paths)
    level = "ok" if info.available and info.is_repo else "warn"
    found = [(level, f"git: {info.message}")]
    if info.hint and level != "ok":
        found.append(("warn", f"git hint: {info.hint}"))
    return found


def _check_paths(paths: Paths) -> List[Finding]:
    found: List[Finding] = []
    if os.path.isdir(paths.repo_dir):
        found.append(("ok", f"repo {paths.display(paths.repo_dir)}"))
    else:
        found.append(("fail", f"repo directory missing: {paths.display(paths.repo_dir)}"))
    for label, path in (("agents", paths.agents_home), ("claude", paths.claude_home),
                        ("codex", paths.codex_home)):
        if os.path.isdir(path):
            found.append(("ok", f"{label} home {paths.display(path)}"))
        else:
            found.append(("warn", f"{label} home {paths.display(path)} does not exist yet "
                                  "(created by the first install)"))
    return found


def _invalid_json(path: str) -> bool:
    try:
        json.loads(read_text(path, None))
    except ValueError:
        return True
    except OSError:
        return False
    return False


def _check_config(paths: Paths, cfg: config.Config) -> List[Finding]:
    shown = paths.display(cfg.path)
    if not cfg.exists:
        found: List[Finding] = [("ok", f"config {shown} not created yet (defaults in use)")]
    elif cfg.error and _invalid_json(cfg.path):
        found = [("fail", f"config {shown} is not valid JSON: {cfg.error}")]
    elif cfg.error:
        found = [("warn", f"config {shown}: {cfg.error}")]
    else:
        found = [("ok", f"config {shown}")]
    return found + [("warn", f"config: {text}") for text in config.validate(cfg)]


def _check_settings(paths: Paths, context) -> List[Finding]:
    path = os.path.join(paths.claude_home, "settings.json")
    if not os.path.isfile(path):
        return []
    try:
        texts = claude_settings.warnings(read_text(path, None), context)
    except OSError as exc:
        return [("warn", f"{paths.display(path)}: {exc}")]
    return [("warn", f"settings.json: {text}") for text in texts] or \
        [("ok", f"{paths.display(path)} has no known problems")]


def _check_caps(caps: capabilities.Capabilities) -> List[Finding]:
    found = sorted(c.name for c in caps.items.values() if c.present)
    missing = sorted(c.name for c in caps.items.values() if not c.present)
    return [("ok", "tools found: " + (", ".join(found) or "none")),
            ("ok", "tools not found: " + (", ".join(missing) or "none"))]


def _check_extras(paths: Paths) -> List[Finding]:
    _, problems = extras.load_checked(paths)
    return [("warn", f"extras: {text}") for text in problems]


def _collect_findings(ctx: Ctx) -> List[Tuple[str, str, str]]:
    """Every check as (name, level, text); `name` is the check that produced the finding."""
    paths = ctx.paths
    cfg = config.load(paths)
    caps = probe_caps(ctx)
    steps: List[Tuple[str, Callable[[], List[Finding]]]] = [
        ("python", _check_python), ("curses", _check_curses),
        ("git", lambda: _check_git(paths)), ("paths", lambda: _check_paths(paths)),
        ("config", lambda: _check_config(paths, cfg)),
        ("settings", lambda: _check_settings(paths, build_context(ctx, cfg, caps))),
        ("tools", lambda: _check_caps(caps)), ("extras", lambda: _check_extras(paths)),
    ]
    return [(name, level, text) for name, step in steps for level, text in step()]


def cmd_doctor(ctx: Ctx) -> int:
    """Print every check; exit 1 only when something blocks the installer.

    ``--json`` prints {"checks": [{"name", "state": "ok"|"warn"|"blocker", "text"}],
    "blockers": N} instead of the text report; the exit status is the same."""
    findings = _collect_findings(ctx)
    blockers = sum(1 for _, level, _ in findings if level == "fail")
    if ctx.flag("json"):
        dump_json({"checks": [{"name": name, "state": _JSON_STATES[level], "text": text}
                              for name, level, text in findings],
                   "blockers": blockers})
        return EXIT_FAIL if blockers else EXIT_OK
    tags = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}
    for _, level, text in findings:
        emit(f"{tags[level]} {text}")
    emit("")
    emit("doctor: " + (f"{blockers} blocker(s) found" if blockers else "no blockers"))
    return EXIT_FAIL if blockers else EXIT_OK
