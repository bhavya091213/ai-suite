"""The App: screen stack, global keys, rescan/fetch/pull and the main loop.

Screens are looked up lazily per tab through a registry of (module, class)
names, so a tab whose module is not written yet shows "screen not available
yet" on the message line instead of crashing the app. Instances are cached per
tab, which keeps filters, cursors and unsaved edits when the user jumps away
and back.

Global keys (skipped while the top screen reports ``editing()``):
``q`` back (quit on the root)  ``Q`` quit  ``?`` help  ``R`` recheck
``F`` fetch  ``1``..``9`` jump to a tab, ``0`` to tab 10  ``Tab``/``Shift-Tab`` next/previous tab.
Tab and Shift-Tab are left to a pushed sub-screen (``screen.tab is None``), e.g. the viewer's pane focus.
"""

from __future__ import annotations

import contextlib
import curses
import importlib
import locale
import os
import sys
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Tuple

from installer.core import capabilities
from installer.core import config as cfg
from installer.core import extras as extras_mod
from installer.core import git as git_mod
from installer.core import render, skills
from installer.core import status as status_mod
from installer.core.paths import Paths
from installer.core.types import GitInfo
from installer.tui import draw
from installer.tui.base import POP, QUIT, TABS, Screen
from installer.tui.screens.confirm import ConfirmScreen, OutputScreen

SCREENS_PACKAGE = "installer.tui.screens"

# tab number -> (module name under SCREENS_PACKAGE, conventional class name)
DEFAULT_REGISTRY: Mapping[int, Tuple[str, str]] = MappingProxyType({
    1: ("overview", "OverviewScreen"),
    2: ("browse", "BrowseScreen"),
    3: ("installed", "InstalledScreen"),
    4: ("issues", "IssuesScreen"),
    5: ("updates", "UpdatesScreen"),
    6: ("settings", "SettingsScreen"),
    7: ("files", "FilesScreen"),
    8: ("fullinstall", "FullInstallScreen"),
    9: ("extras", "ExtrasScreen"),
    10: ("workflows", "WorkflowsScreen"),
})

START_ALIASES: Mapping[str, int] = MappingProxyType({
    "browse": 2, "skills": 2, "fullinstall": 8, "install": 8,
})

STREAM_POLL_MS = 100
KEY_TAB = 9


class ScreenUnavailable(Exception):
    """The screen module or class for a tab does not exist (yet)."""


def resolve_start_screen(name: str, tabs: Sequence[Tuple[int, str]] = TABS) -> Optional[int]:
    """Tab number for "overview", "settings", "3", ...; None when unknown."""
    key = str(name).strip().lower()
    if key.isdigit():
        number = int(key)
        return number if number in dict(tabs) else None
    for number, label in tabs:
        if label.lower() == key:
            return number
    return START_ALIASES.get(key)


def blank_git() -> GitInfo:
    """Placeholder shown until the first git.detect() has run."""
    return GitInfo(available=False, version=None, is_repo=False, branch=None, head=None,
                   upstream=None, ahead=0, behind=0, dirty=False, last_fetch=None,
                   remote_url=None, message="git status not checked yet")


def _find_class(module: Any, class_name: str, number: int) -> type:
    found = getattr(module, class_name, None)
    if isinstance(found, type):
        return found
    candidates = [obj for obj in vars(module).values()
                  if isinstance(obj, type) and issubclass(obj, Screen) and obj is not Screen
                  and obj.__module__ == module.__name__]
    for obj in candidates:
        if getattr(obj, "tab", None) == number:
            return obj
    if candidates:
        return candidates[0]
    raise ScreenUnavailable(class_name)


class App:
    """Everything screens need, as plain attributes plus the methods in tui/base.py."""

    def __init__(self, paths: Paths, stdscr: Any = None, caps: Optional[capabilities.Capabilities] = None,
                 registry: Optional[Mapping[int, Tuple[str, str]]] = None) -> None:
        self.paths = paths
        self.stdscr = stdscr
        self.registry = DEFAULT_REGISTRY if registry is None else registry
        self.tabs = TABS
        self.active_tab = 1
        self.message = ""
        self.config = cfg.load(paths)
        self.caps = capabilities.probe() if caps is None else caps
        self.context = self._build_context()
        self.catalog: Dict[Tuple[str, str], Any] = {}
        self.repo_issues: Tuple[Any, ...] = ()
        self.installed: Dict[Tuple[str, str], Any] = {}
        self.statuses: Tuple[Any, ...] = ()
        self.git: GitInfo = blank_git()
        self.remote: Dict[Tuple[str, str], Any] = {}
        self.extras: Tuple[Any, ...] = ()
        self._stack: Tuple[Screen, ...] = ()
        self._screens: Mapping[int, Screen] = MappingProxyType({})
        self._commands: Tuple[OutputScreen, ...] = ()  # for shutdown(), even after they left the stack

    # ------------------------------------------------------------ stack

    @property
    def stack(self) -> Tuple[Screen, ...]:
        return self._stack

    def top(self) -> Optional[Screen]:
        return self._stack[-1] if self._stack else None

    def push(self, screen: Screen) -> None:
        self._stack = self._stack + (screen,)
        self._sync_tab()
        self._enter(screen)

    def pop(self) -> None:
        if not self._stack:
            return
        self._stack = self._stack[:-1]
        self._sync_tab()
        if self._stack:
            self._enter(self._stack[-1])

    def replace(self, screen: Screen) -> None:
        self._stack = self._stack[:-1] + (screen,)
        self._sync_tab()
        self._enter(screen)

    def pop_then(self, after: Callable[[], None]) -> None:
        """Pop the top screen, run ``after()``, then enter the screen that was uncovered.

        For dialogs that report back: ``after`` may push or switch tabs and sees the stack without
        the dialog, and a flag it sets on the uncovered screen is there when its ``on_enter`` runs.
        """
        if self._stack:
            self._stack = self._stack[:-1]
            self._sync_tab()
        uncovered = self.top()
        try:
            after()
        finally:
            if uncovered is not None and self.top() is uncovered:
                self._enter(uncovered)

    def _enter(self, screen: Screen) -> None:
        try:
            screen.on_enter(self)
        except Exception as exc:  # noqa: BLE001 - never let a screen crash the stack
            self.set_message(f"error: {type(exc).__name__}: {exc}")

    def _sync_tab(self) -> None:
        for screen in reversed(self._stack):
            if screen.tab is not None:
                self.active_tab = screen.tab
                return

    def _tab_label(self, number: int) -> str:
        return dict(self.tabs).get(number, str(number))

    def _screen_for_tab(self, number: int) -> Screen:
        cached = self._screens.get(number)
        if cached is not None:
            return cached
        if number not in self.registry:
            raise ScreenUnavailable(str(number))
        module_name, class_name = self.registry[number]
        full = module_name if "." in module_name else f"{SCREENS_PACKAGE}.{module_name}"
        try:
            module = importlib.import_module(full)
        except ModuleNotFoundError as exc:
            if exc.name == full:
                raise ScreenUnavailable(full) from exc
            raise
        screen = _find_class(module, class_name, number)()
        self._screens = MappingProxyType({**self._screens, number: screen})
        return screen

    def goto_tab(self, number: int) -> bool:
        """Replace the stack with the screen of tab `number`; False (with a message) if it cannot open."""
        label = self._tab_label(number)
        try:
            screen = self._screen_for_tab(number)
        except ScreenUnavailable:
            self.set_message(f"screen not available yet: {label}")
            return False
        except Exception as exc:  # noqa: BLE001
            self.set_message(f"cannot open {label}: {type(exc).__name__}: {exc}")
            return False
        self._stack = (screen,)
        self.active_tab = number
        self._enter(screen)
        return True

    def _cycle_tab(self, delta: int) -> None:
        numbers = [number for number, _ in self.tabs]
        start = numbers.index(self.active_tab) if self.active_tab in numbers else 0
        for step in range(1, len(numbers) + 1):
            if self.goto_tab(numbers[(start + delta * step) % len(numbers)]):
                return

    def set_message(self, text: str) -> None:
        self.message = " ".join(str(text).split())

    # --------------------------------------------------------- data

    def _build_context(self) -> Mapping[str, Any]:
        # The Capabilities object keeps the detail docker_state needs and the full nvm_versions.
        return render.build_context(self.config.data, self.caps, self.paths)

    def reload_config(self) -> None:
        """Re-read ~/.agents/config.json and rebuild the template context."""
        self.config = cfg.load(self.paths)
        self.context = self._build_context()

    def probe_caps(self) -> None:
        """Re-run the capability probes (after the user installs a tool) and rebuild the context."""
        self.caps = capabilities.probe()
        self.context = self._build_context()

    def rescan(self) -> None:
        """Recompute catalog, installed, statuses and extras (no git fetch)."""
        catalog, issues = skills.scan_catalog(self.paths)
        installed = skills.scan_installed(self.paths)
        statuses = status_mod.compute(catalog, installed, self.paths, self.remote, issues)
        found = extras_mod.load(self.paths)
        detected = tuple(extras_mod.detect(extra, self.paths) for extra in found)
        self.catalog, self.repo_issues, self.installed = catalog, issues, installed
        self.statuses, self.extras = statuses, detected
        self._notify_rescan()

    def _notify_rescan(self) -> None:
        for screen in self._stack:
            hook = getattr(screen, "on_rescan", None)
            if callable(hook):
                try:
                    hook(self)
                except Exception as exc:  # noqa: BLE001
                    self.set_message(f"error: {type(exc).__name__}: {exc}")

    def _refresh_remote(self) -> None:
        self.remote = git_mod.remote_changes(self.paths, self.catalog)
        self.statuses = status_mod.compute(self.catalog, self.installed, self.paths, self.remote,
                                           self.repo_issues)
        self._notify_rescan()

    def refresh_git(self) -> None:
        self.git = git_mod.detect(self.paths)

    def fetch(self) -> None:
        self._busy("fetching from the remote...")
        info = git_mod.fetch(self.paths)
        self.git = info
        self.rescan()
        self._refresh_remote()
        self.set_message(f"fetch problem: {info.error}" if info.error else info.message)

    def pull(self) -> Tuple[bool, str]:
        self._busy("pulling (fast-forward only)...")
        ok, text = git_mod.pull_ff(self.paths)
        self.refresh_git()
        self.rescan()
        self._refresh_remote()
        self.set_message(text if ok else f"pull failed: {text}")
        return ok, text

    def recheck(self) -> None:
        """Global R: re-probe tools, re-read config, re-detect git and rescan the disk."""
        self._busy("re-checking tools, git and files...")
        self.probe_caps()
        self.reload_config()
        self.refresh_git()
        self.rescan()
        self._refresh_remote()
        self.set_message("rescanned")

    def _busy(self, text: str) -> None:
        """Show `text` right now, before a slow blocking call."""
        self.set_message(text)
        self._draw()

    # -------------------------------------------------------- actions

    def confirm(self, ops: Sequence[Any], title: str, on_done: Any = None,
                backup_root: Optional[str] = None) -> None:
        """Push a ConfirmScreen; on 'y' it applies, shows results, calls on_done, then rescans."""
        plan = tuple(ops)
        if not plan:
            self.set_message("nothing to do")
            return
        self.push(ConfirmScreen(plan, title, self.paths, on_done, backup_root))

    def run_command(self, argv: Sequence[str], title: str, cwd: Optional[str] = None,
                    on_done: Any = None) -> None:
        """Push an OutputScreen streaming `argv` (an argument list; never run through a shell)."""
        if isinstance(argv, str):
            raise TypeError("run_command needs an argument list, not a shell string")
        screen = OutputScreen(tuple(argv), title, cwd, on_done)
        self._commands = tuple(c for c in self._commands if c.running) + (screen,)
        self.push(screen)

    @contextlib.contextmanager
    def suspend(self) -> Iterator[None]:
        """Leave curses (to run $EDITOR or a pager) and restore the screen afterwards."""
        if self.stdscr is None:
            yield
            return
        try:
            curses.def_prog_mode()
            curses.endwin()
        except curses.error:
            pass
        try:
            yield
        finally:
            try:
                curses.reset_prog_mode()
                self.stdscr.refresh()
            except curses.error:
                pass

    def start_wizard(self) -> None:
        """Push the Settings screen in first-run wizard mode."""
        try:
            from installer.tui.screens.settings import SettingsScreen
            screen = SettingsScreen(wizard=True)
        except Exception as exc:  # noqa: BLE001 - the screen may not exist yet
            self.set_message(f"setup wizard not available ({type(exc).__name__}: {exc})")
            return
        self.push(screen)

    def open_help(self) -> None:
        from installer.tui.screens.help import HelpScreen
        self.push(HelpScreen())

    # ------------------------------------------------------------ keys

    def handle_key(self, key: int) -> Optional[str]:
        """Dispatch one key; returns QUIT when the app should exit."""
        if key == curses.KEY_RESIZE:
            return None
        top = self.top()
        if top is None:
            return QUIT
        self.message = ""
        try:
            if not top.editing():
                handled, outcome = self._global_key(key, top)
                if handled:
                    return outcome
            return self._apply_result(top.handle_key(key, self))
        except Exception as exc:  # noqa: BLE001 - a bad key must never kill the app
            self.set_message(f"error: {type(exc).__name__}: {exc}")
            return None

    def _global_key(self, key: int, top: Screen) -> Tuple[bool, Optional[str]]:
        if key == ord("Q"):
            return True, QUIT
        if key == ord("q"):
            if len(self._stack) > 1:
                self.pop()
                return True, None
            return True, QUIT
        actions_by_key = {ord("?"): self.open_help, ord("R"): self.recheck, ord("F"): self.fetch}
        if key in actions_by_key:
            actions_by_key[key]()
            return True, None
        if ord("0") <= key <= ord("9"):
            self.goto_tab(key - ord("0") or 10)  # "0" is the tenth tab
            return True, None
        if key in (KEY_TAB, curses.KEY_BTAB) and top.tab is not None:
            self._cycle_tab(1 if key == KEY_TAB else -1)
            return True, None
        return False, None

    def _apply_result(self, result: Optional[str]) -> Optional[str]:
        if result == QUIT:
            return QUIT
        if result == POP:
            self.pop()
            return None if self._stack else QUIT
        return None

    # ------------------------------------------------------------ loop

    def _draw(self) -> None:
        stdscr = self.stdscr
        top = self.top()
        if stdscr is None or top is None:
            return
        stdscr.erase()
        if draw.too_small(stdscr):
            stdscr.refresh()
            return
        try:
            top.draw(stdscr, self)
        except Exception as exc:  # noqa: BLE001 - show the error instead of a half-drawn screen
            self.set_message(f"draw error: {type(exc).__name__}: {exc}")
            stdscr.erase()
            with contextlib.suppress(Exception):
                draw.draw_frame(stdscr, self, getattr(top, "title", ""), "")
        stdscr.refresh()

    def _streaming(self) -> bool:
        check = getattr(self.top(), "streaming", None)
        return bool(callable(check) and check())

    def loop(self) -> int:
        empty = 0
        while self._stack:
            self._draw()
            key, empty, gone = draw.read_key(self.stdscr, STREAM_POLL_MS if self._streaming() else -1, empty)
            if gone:  # stdin at EOF or the terminal is gone: leave instead of spinning
                return 0
            if key != -1 and self.handle_key(key) == QUIT:
                return 0
        return 0

    def start(self, start_screen: str = "overview") -> None:
        """Initial scan, first screen, and the first-run wizard when no config file exists."""
        try:
            self.refresh_git()
            self.rescan()
            if self.git.is_repo and self.git.behind:
                self._refresh_remote()
        except Exception as exc:  # noqa: BLE001
            self.set_message(f"initial scan failed: {type(exc).__name__}: {exc}")
        number = resolve_start_screen(start_screen)
        if number is None or not self.goto_tab(number):
            if not self.goto_tab(1):
                self._fallback_overview()
        if self.config.error:
            self.set_message(f"config problem: {self.config.error}")
        if not self.config.exists:
            self.start_wizard()

    def _fallback_overview(self) -> None:
        from installer.tui.screens.overview import OverviewScreen
        self._stack = (OverviewScreen(),)
        self.active_tab = 1
        self._enter(self._stack[0])

    def shutdown(self) -> None:
        """Terminate every command still running, whether or not its screen is still on the stack."""
        for screen in self._stack + self._commands:
            closer = getattr(screen, "close", None)
            if callable(closer):
                with contextlib.suppress(Exception):
                    closer()

    def main(self, start_screen: str = "overview") -> int:
        self.start(start_screen)
        try:
            return self.loop()
        except KeyboardInterrupt:
            return 130
        finally:
            self.shutdown()


def run(paths: Paths, start_screen: str = "overview") -> int:
    """Run the interactive UI under curses.wrapper; returns the process exit code."""
    os.environ.setdefault("ESCDELAY", "25")
    with contextlib.suppress(locale.Error):
        locale.setlocale(locale.LC_ALL, "")
    caps = capabilities.probe()

    def _main(stdscr: Any) -> int:
        draw.init_colors()
        with contextlib.suppress(curses.error):
            curses.curs_set(0)
        return App(paths, stdscr, caps=caps).main(start_screen)

    try:
        return curses.wrapper(_main)
    except curses.error as exc:
        print(f"cannot start the terminal UI: {exc}", file=sys.stderr)
        return 1
