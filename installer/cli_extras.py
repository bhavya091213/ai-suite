"""`extras` commands: list, show and install external integrations (not skills).

Installing runs third-party commands, so it only ever happens after the warning below
is printed and the user answers yes (``--yes`` is the explicit non-interactive form).
Commands run as an argument list from ``shlex.split`` - never through a shell.

Everything here goes through the command context (``ctx.paths`` / ``ctx.env``), never the
process environment, so ``--home <dir>`` sandboxes detection *and* the commands that run:
they get the context's env (``HOME`` relocated, exported tool homes dropped) and look
programs up on the context's ``PATH``.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from typing import Callable, List, Optional, Tuple

from installer.cli_config import TOOLS, probe_caps
from installer.cli_io import (
    EXIT_FAIL, EXIT_OK, Ctx, confirm, dump_json, emit, failure, glyph, print_table,
    usage_error, warn,
)
from installer.core import capabilities, config, extras

THIRD_PARTY_WARNING = (
    "WARNING: this runs third-party code from {url} on this machine, exactly as listed below "
    "(no shell). Read the commands first; only continue if you trust the source."
)


def _which(ctx: Ctx) -> Callable[[str], Optional[str]]:
    """``shutil.which`` on the context's PATH (the process PATH when the context has none)."""
    path = ctx.env.get("PATH")
    return lambda name: shutil.which(name, path=path)


def _detect(ctx: Ctx, extra: extras.Extra) -> extras.ExtraStatus:
    return extras.detect(extra, ctx.paths, env=dict(ctx.env), which=_which(ctx))


def _statuses(ctx: Ctx) -> Tuple[extras.ExtraStatus, ...]:
    return tuple(_detect(ctx, e) for e in extras.load(ctx.paths))


def _cell(status: extras.ExtraStatus, tool: str) -> str:
    if tool not in status.extra.tools:
        return glyph("na")
    value = status.installed.get(tool)
    return glyph("unknown" if value is None else ("ok" if value else "bad"))


def _find(ctx: Ctx, name: str) -> extras.ExtraStatus:
    for extra in extras.load(ctx.paths):
        if extra.key == name:
            return _detect(ctx, extra)
    raise usage_error(f"unknown extra: {name}")


def _extras_list(ctx: Ctx) -> int:
    statuses = _statuses(ctx)
    if ctx.flag("json"):
        dump_json([{"key": s.extra.key, "title": s.extra.title, "category": s.extra.category,
                    "url": s.extra.url, "tools": s.extra.tools, "installed": dict(s.installed)}
                   for s in statuses])
        return EXIT_OK
    if not statuses:
        emit("No extras defined (shared/extras.json is missing or empty).")
        return EXIT_OK
    rows = [(s.extra.key, s.extra.category) + tuple(_cell(s, t) for t in TOOLS) + (s.extra.title,)
            for s in statuses]
    print_table(("KEY", "CATEGORY") + TOOLS + ("TITLE",), rows)
    return EXIT_OK


def _extras_show(ctx: Ctx) -> int:
    status = _find(ctx, ctx.args.name)
    extra = status.extra
    emit(f"{extra.key}: {extra.title}")
    emit(f"category {extra.category}   url {extra.url}")
    for tool in extra.tools:
        state = {True: "installed", False: "not installed", None: "unknown"}[status.installed.get(tool)]
        emit(f"[{tool}] {state}")
        for command in extras.commands_for(extra, tool):
            emit(f"    install: {command}")
        if extra.after_install.get(tool):
            emit(f"    after:   {extra.after_install[tool]}")
    return EXIT_OK


def _enabled_tools(ctx: Ctx, status: extras.ExtraStatus) -> Tuple[str, ...]:
    """Tools of the extra that are switched on and not yet set up."""
    cfg = config.load(ctx.paths)
    caps = probe_caps(ctx, only=TOOLS)
    return tuple(t for t in status.extra.tools
                 if status.installed.get(t) is not True
                 and capabilities.resolve_tool(config.get(cfg, f"tools.{t}"), caps.get(t)))


def _choose_tools(ctx: Ctx, status: extras.ExtraStatus) -> Tuple[str, ...]:
    wanted: Optional[str] = ctx.flag("tool", None)
    if wanted is None:
        return _enabled_tools(ctx, status)
    if wanted not in status.extra.tools:
        raise usage_error(f"{status.extra.key} does not support --tool {wanted} "
                          f"(supports: {', '.join(status.extra.tools)})")
    return (wanted,)


def _commands(extra: extras.Extra, tools: Tuple[str, ...]) -> Tuple[str, ...]:
    seen: List[str] = []
    for tool in tools:
        for command in extras.commands_for(extra, tool):
            if command not in seen:
                seen.append(command)
    return tuple(seen)


def _run_commands(ctx: Ctx, commands: Tuple[str, ...]) -> int:
    env = dict(ctx.env)
    for command in commands:
        emit(f"$ {command}")
        try:
            code = subprocess.run(shlex.split(command), env=env).returncode
        except (OSError, ValueError) as exc:
            raise failure(f"cannot run {command!r}: {exc}")
        if code != 0:
            warn(f"command failed with status {code}; stopping.")
            return EXIT_FAIL
    return EXIT_OK


def _extras_install(ctx: Ctx) -> int:
    status = _find(ctx, ctx.args.name)
    extra = status.extra
    tools = _choose_tools(ctx, status)
    commands = _commands(extra, tools)
    if not commands:
        emit(f"{extra.key}: nothing to install (already set up, or no tool is enabled for it).")
        return EXIT_OK
    emit(f"{extra.title}")
    emit(THIRD_PARTY_WARNING.format(url=extra.url))
    for number, command in enumerate(commands, 1):
        emit(f"  {number}. {command}")
    if ctx.flag("dry_run"):
        emit("Dry run only; nothing was run.")
        return EXIT_OK
    if not confirm(ctx.args, "Run?"):
        emit("Aborted.")
        return EXIT_FAIL
    code = _run_commands(ctx, commands)
    if code == EXIT_OK:
        for tool in tools:
            if extra.after_install.get(tool):
                emit(f"next ({tool}): {extra.after_install[tool]}")
    return code


def cmd_extras(ctx: Ctx) -> int:
    handlers = {"list": _extras_list, "show": _extras_show, "install": _extras_install}
    return handlers[ctx.args.extras_action](ctx)
