"""Command line front end: ``python3 -m installer [command] [options]``.

Argument parsing and dispatch only; the commands live in ``cli_commands`` (skills, git),
``cli_config`` (config, caps, render, edit), ``cli_system`` (tui, apply, doctor),
``cli_extras`` and ``cli_workflow`` (the workflow maker). With no command the interactive
installer starts when stdin is a terminal, otherwise ``status`` is printed.

Exit codes: 0 ok, 1 failure, 2 usage error, 3 file excluded by a requirement (render).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from installer import __version__
from installer.cli_commands import (
    cmd_categories, cmd_install, cmd_issues, cmd_list, cmd_pull, cmd_push, cmd_relink,
    cmd_retire, cmd_show, cmd_status, cmd_tree, cmd_update, cmd_updates,
)
from installer.cli_config import (
    EDIT_TARGETS, cmd_caps, cmd_config, cmd_edit, cmd_render, cmd_render_tree, cmd_sections,
)
from installer.cli_extras import cmd_extras
from installer.cli_io import EXIT_FAIL, EXIT_OK, EXIT_USAGE, CliError, Ctx
from installer.cli_system import cmd_apply, cmd_doctor, cmd_settings_sync, cmd_tui
from installer.cli_workflow import cmd_workflow
from installer.core.paths import Paths
from installer.core.types import SCOPES

Handler = Callable[[Ctx], int]
DEBUG_ENV = "INSTALLER_DEBUG"
# Variables that relocate a tool home on their own; --home must not be overridden by them.
HOME_OVERRIDE_VARS = ("AGENTS_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME")


# ------------------------------------------------------------------ parser


def _globals(parser: argparse.ArgumentParser, top: bool) -> None:
    """--repo / --home. Sub-parsers use SUPPRESS so they never overwrite the top-level value."""
    default = None if top else argparse.SUPPRESS
    parser.add_argument("--repo", metavar="PATH", default=default,
                        help="repo checkout to read skills from (default: this checkout)")
    parser.add_argument("--home", metavar="PATH", default=default,
                        help="treat PATH as $HOME (uses PATH/.agents, .claude, .codex)")


def _command(sub, name: str, func: Handler, help_text: str) -> argparse.ArgumentParser:
    parser = sub.add_parser(name, help=help_text, description=help_text)
    _globals(parser, top=False)
    parser.set_defaults(func=func)
    return parser


def _action(actions, name: str, help_text: str) -> argparse.ArgumentParser:
    """A nested action parser (``config get``, ``extras list`` ...) that also takes --repo / --home."""
    parser = actions.add_parser(name, help=help_text, description=help_text)
    _globals(parser, top=False)
    return parser


def _scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--scope", choices=SCOPES, help="disambiguate a name that exists in several scopes")


def _category(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", metavar="NAME",
                        help="only skills in this category (case-insensitive; see the categories command)")


def _mutating(parser: argparse.ArgumentParser, dry_run: bool = True) -> None:
    parser.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    if dry_run:
        parser.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")


def _json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def _skill_commands(sub) -> None:
    for name, func, text in (
        ("status", cmd_status, "table of every skill: state, links, upstream changes"),
        ("list", cmd_list, "skills available in the repo, with an installed marker"),
    ):
        parser = _command(sub, name, func, text)
        _scope(parser)
        _category(parser)
        _json(parser)
    _json(_command(sub, "categories", cmd_categories, "skill categories with offered and installed counts"))
    _json(_command(sub, "issues", cmd_issues, "duplicates, broken links, foreign entries, bad frontmatter"))
    for name, func, text in (
        ("install", cmd_install, "install skills from the repo (never overwrites)"),
        ("update", cmd_update, "replace a modified installed skill with the repo copy (backs it up)"),
        ("retire", cmd_retire, "move installed skills (and their tool links) into a backup"),
        ("push", cmd_push, "copy an installed skill back into the repo"),
    ):
        parser = _command(sub, name, func, text)
        parser.add_argument("names", nargs="+", metavar="NAME")
        _scope(parser)
        _mutating(parser)
        if name == "retire":
            parser.add_argument("--consumers-only", action="store_true",
                                help="only unlink from claude/codex; keep the shared copy")
    relink = _command(sub, "relink", cmd_relink, "repair claude/codex links to shared skills")
    relink.add_argument("names", nargs="*", metavar="NAME")
    _mutating(relink)


def _view_commands(sub) -> None:
    tree = _command(sub, "tree", cmd_tree, "file tree of one skill")
    tree.add_argument("name", metavar="NAME")
    _scope(tree)
    show = _command(sub, "show", cmd_show, "print a file of one skill (default SKILL.md)")
    show.add_argument("name", metavar="NAME")
    show.add_argument("file", nargs="?", metavar="FILE")
    _scope(show)
    updates = _command(sub, "updates", cmd_updates,
                       "git status: commits behind and skills with upstream changes")
    updates.add_argument("--fetch", action="store_true", help="run git fetch first")
    updates.add_argument("--json", action="store_true",
                         help='machine-readable: {"git": {message, hint, branch, upstream, ahead, behind, '
                              'last_fetch}, "commits": ["<sha> <subject>"], "changed": [{scope, name, files}]}')
    _mutating(_command(sub, "pull", cmd_pull, "git pull --ff-only in the repo"))


def _config_commands(sub) -> None:
    _json(_command(sub, "caps", cmd_caps, "which tools were detected on this machine"))
    _command(sub, "sections", cmd_sections, "which of shared/claude/codex to install")
    config = _command(sub, "config", cmd_config, "read or change ~/.agents/config.json")
    actions = config.add_subparsers(dest="config_action", required=True, metavar="ACTION")
    _json(_action(actions, "list", "every setting and its value"))
    _action(actions, "get", "print one value").add_argument("key")
    set_parser = _action(actions, "set", "change one value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    _mutating(set_parser, dry_run=False)
    reset = _action(actions, "reset", "restore one value to its default")
    reset.add_argument("key")
    _mutating(reset, dry_run=False)
    _action(actions, "path", "print the config file path")
    _action(actions, "edit", "open the config file in your editor")
    edit = _command(sub, "edit", cmd_edit, "open a config file in your editor")
    edit.add_argument("target", choices=sorted(EDIT_TARGETS))


def _render_commands(sub) -> None:
    render = _command(sub, "render", cmd_render, "print one repo file as it would be installed")
    render.add_argument("file", metavar="FILE")
    tree = _command(sub, "render-tree", cmd_render_tree, "mirror a repo directory, rendered, into OUT")
    tree.add_argument("src", metavar="SRC")
    tree.add_argument("out", metavar="OUT")
    tree.add_argument("--rel", required=True, help="repo-relative name of SRC, e.g. shared")
    _json(tree)


def _system_commands(sub) -> None:
    _command(sub, "tui", cmd_tui, "interactive installer (curses)")
    _mutating(_command(sub, "apply", cmd_apply,
                       "run ./install.sh --headless --auto, then sync settings into existing files"), dry_run=True)
    _mutating(_command(sub, "settings-sync", cmd_settings_sync,
                       "copy hook profile and Codex subagent settings into existing settings.json / config.toml"),
              dry_run=True)
    doctor = _command(sub, "doctor", cmd_doctor, "check python, curses, git, paths, config and tools")
    doctor.add_argument("--json", action="store_true",
                        help='machine-readable: {"checks": [{name, state: ok|warn|blocker, text}], '
                             '"blockers": N}; the exit status is unchanged')
    extras = _command(sub, "extras", cmd_extras, "external integrations (Impeccable, Figma, ...)")
    actions = extras.add_subparsers(dest="extras_action", required=True, metavar="ACTION")
    _json(_action(actions, "list", "known extras and whether they are set up"))
    _action(actions, "show", "details and install commands").add_argument("name")
    install = _action(actions, "install", "run an extra's install commands (third-party code)")
    install.add_argument("name")
    install.add_argument("--tool", choices=("claude", "codex"), help="install for one tool only")
    _mutating(install)


def _workflow_commands(sub) -> None:
    workflow = _command(sub, "workflow", cmd_workflow,
                        "compose installed skills into a phased workflow skill")
    actions = workflow.add_subparsers(dest="workflow_action", required=True, metavar="ACTION")
    _json(_action(actions, "list", "installed workflows: phases, skills, valid or not"))
    _action(actions, "show", "definition fields and validation messages").add_argument("name")
    _action(actions, "render", "print the SKILL.md rendered from the definition").add_argument("name")
    _json(_action(actions, "example", "print a sample definition to start from"))
    save = _action(actions, "save", "validate a definition file, then install it as a shared skill")
    save.add_argument("file", metavar="FILE.json")
    _mutating(save)
    for name, text in (("retire", "move an installed workflow (and its tool links) into a backup"),
                       ("push", "copy an installed workflow into the repo's shared/skills")):
        parser = _action(actions, name, text)
        parser.add_argument("name")
        _mutating(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m installer",
        description="Install and manage the skills and configuration in this repo.")
    parser.add_argument("--version", action="version", version=f"installer {__version__}")
    _globals(parser, top=True)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    _skill_commands(sub)
    _view_commands(sub)
    _config_commands(sub)
    _render_commands(sub)
    _system_commands(sub)
    _workflow_commands(sub)
    return parser


# -------------------------------------------------------------------- main


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(list(argv))
    if args.command is None:
        default = "tui" if sys.stdin.isatty() else "status"
        args = parser.parse_args(list(argv) + [default])
    return args


def _resolve(args: argparse.Namespace, env: Optional[Mapping[str, str]]) -> Tuple[Paths, Mapping[str, str]]:
    base = dict(os.environ if env is None else env)
    home = getattr(args, "home", None)
    if home:
        home = os.path.abspath(os.path.expanduser(home))
        base["HOME"] = home
        for name in HOME_OVERRIDE_VARS:  # --home is a sandbox: exported tool homes must not win
            base.pop(name, None)
    paths = Paths.detect(repo_dir=getattr(args, "repo", None), env=base, home=home)
    return paths, base


def _exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return EXIT_OK
    return exc.code if isinstance(exc.code, int) else EXIT_USAGE


def _run(args: argparse.Namespace, env: Optional[Mapping[str, str]]) -> int:
    paths, base = _resolve(args, env)
    return int(args.func(Ctx(args=args, paths=paths, env=base)) or 0)


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None) -> int:
    """Run one command and return its exit status. Never raises (except for INSTALLER_DEBUG=1)."""
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:  # argparse: --help (0) or a usage error (2)
        return _exit_code(exc)
    try:
        return _run(args, env)
    except CliError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_FAIL
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # last resort: report, do not dump a traceback on the user
        if os.environ.get(DEBUG_ENV) == "1":
            raise
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAIL
