"""Terminal-free tests for the TUI foundation: App key handling, the confirm dialog, the output pane and the overview.

Curses is never initialised: drawing goes to FakeWindow and the App runs with ``stdscr=None``.
"""

from __future__ import annotations

import curses
import os
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock

from installer.core.types import Operation, State
from installer.tests import fixtures
from installer.tests.tui_support import make_caps, make_git
from installer.tui.app import App
from installer.tui.base import QUIT, Screen
from installer.tui.screens import confirm as confirm_module
from installer.tui.screens import capabilities as caps_screen
from installer.tui.screens import help as help_screen
from installer.tui.screens import overview
from installer.tui.screens.confirm import OutputScreen


class AppTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.paths = fixtures.build(self.root)
        self.app = App(self.paths, stdscr=None, caps=make_caps())


class AppTests(AppTestCase):
    def test_global_keys_exceptions_and_editing_screens(self):
        class Editor(Screen):
            tab = 1
            seen = []

            def editing(self):
                return True

            def handle_key(self, key, app):
                self.seen.append(key)
                if key == ord("x"):
                    raise RuntimeError("kaboom")

        self.app.goto_tab(1)
        self.assertIsNone(self.app.handle_key(curses.KEY_RESIZE))
        self.app.handle_key(ord("?"))
        self.assertIsInstance(self.app.top(), help_screen.HelpScreen)
        self.assertIsNone(self.app.handle_key(ord("q")))
        self.assertIsInstance(self.app.top(), overview.OverviewScreen)
        self.assertEqual((self.app.handle_key(ord("q")), self.app.handle_key(ord("Q"))), (QUIT, QUIT))
        editor = Editor()
        self.app.push(editor)
        self.app.handle_key(ord("q"))
        self.app.handle_key(ord("2"))
        self.assertEqual(editor.seen, [ord("q"), ord("2")])  # global keys stay away from an editing screen
        self.assertIsNone(self.app.handle_key(ord("x")))
        self.assertIn("kaboom", self.app.message)  # a handler error is shown, not raised


class ConfirmTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.target = os.path.join(self.root, "made", "deeper")
        self.ops = (Operation("mkdir", dst=self.target),)
        self.app.goto_tab(1)

    def test_n_applies_nothing_and_y_applies_then_any_key_returns_calls_on_done_and_rescans(self):
        calls = []
        self.app.confirm((), "Nothing")
        self.assertEqual(self.app.message, "nothing to do")
        self.app.confirm(self.ops, "Make dir")
        self.assertTrue(any("mkdir" in str(line) for line in self.app.top().ask_lines()))
        self.assertIsNone(self.app.handle_key(ord("n")))  # declined: the dialog pops and nothing is applied
        self.assertIsInstance(self.app.top(), overview.OverviewScreen)
        self.assertFalse(os.path.exists(self.target))
        self.app.confirm(self.ops, "Make dir", on_done=lambda results: calls.append(results))
        screen = self.app.top()
        screen.handle_key(ord("y"), self.app)
        self.assertTrue(os.path.isdir(self.target))
        self.assertTrue(screen.results[0].ok)
        with mock.patch.object(self.app, "rescan") as rescan:
            screen.handle_key(ord(" "), self.app)
        self.assertEqual(len(calls), 1)
        rescan.assert_called_once()
        self.assertIsInstance(self.app.top(), overview.OverviewScreen)
        blocker = fixtures.write(os.path.join(self.root, "file.txt"), "x")  # a failing operation is shown, not hidden
        self.app.confirm((Operation("copytree", dst=blocker, src=self.root),), "Fails")
        self.app.top().handle_key(ord("y"), self.app)
        self.assertFalse(self.app.top().results[0].ok)
        self.assertTrue(any("FAILED" in str(line) for line in self.app.top().result_lines()))


def wait_until(condition, seconds: float = 10.0) -> bool:
    end = time.time() + seconds
    while not condition() and time.time() < end:
        time.sleep(0.02)
    return bool(condition())


def wait_finished(screen: OutputScreen, seconds: float = 10.0) -> None:
    wait_until(lambda: not screen.running, seconds)


def python_command(code: str):
    return (sys.executable, "-c", code)


def pid_alive(pid: int) -> bool:
    try:
        return os.kill(pid, 0) is None
    except ProcessLookupError:
        return False


class OutputScreenTests(AppTestCase):
    def open_screen(self, argv) -> OutputScreen:
        """Push an OutputScreen on top of the Overview, like App.run_command."""
        self.app.goto_tab(1)
        screen = OutputScreen(tuple(argv), "Run")
        self.addCleanup(screen.close, 0.2)
        self.app.push(screen)
        return screen

    def test_streams_output_reports_the_exit_code_and_a_missing_binary_fails_cleanly(self):
        self.app.goto_tab(1)
        self.app.run_command(list(python_command("print('hello'); print('world')")), "Echo")
        screen = self.app.top()
        self.assertIsInstance(screen, OutputScreen)
        self.assertTrue(screen.editing())
        wait_finished(screen)
        lines, finished, code = screen.snapshot()
        self.assertEqual((lines, finished, code), (("hello", "world"), True, 0))
        self.assertEqual(screen._status(finished, code), ("exit code 0", "ok"))
        self.assertIsNone(self.app.handle_key(ord("q")))
        self.assertIsInstance(self.app.top(), overview.OverviewScreen)
        missing = OutputScreen((os.path.join(self.root, "no-such-binary"),), "Run")
        missing.start()
        lines, finished, code = missing.snapshot()
        self.assertEqual((finished, code), (True, 127))
        self.assertIn("failed to start", lines[0])

    @unittest.skipUnless(hasattr(os, "killpg"), "needs POSIX process groups")
    def test_the_user_is_never_trapped_and_kill_stops_the_whole_process_group(self):
        # q is refused while running; k then y stops the command (SIGKILL if it ignores SIGTERM) and its children.
        stubborn = ("import signal, subprocess, sys, time\n"
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    "print('ready', child.pid, flush=True)\ntime.sleep(60)")
        with mock.patch.object(confirm_module, "KILL_GRACE_SECONDS", 0.3):
            screen = self.open_screen(python_command(stubborn))
            self.assertTrue(wait_until(lambda: any(l.startswith("ready") for l in screen.snapshot()[0])))
            child_pid = int(screen.snapshot()[0][0].split()[1])
            self.assertEqual(screen._status(False, None), ("running...", "warn"))
            self.app.handle_key(ord("q"))
            self.assertIs(self.app.top(), screen)
            self.assertIn("still running", self.app.message)
            self.app.handle_key(ord("k"))
            self.assertEqual(screen._status(False, None)[0], "kill the running command? y/n")
            self.app.handle_key(ord("y"))
            self.assertEqual(screen._status(False, None), ("stopping...", "warn"))
            self.app.handle_key(ord("q"))
            self.assertIs(self.app.top(), screen)
            self.assertIn("still stopping", self.app.message)
            wait_finished(screen, 5.0)
            self.assertEqual(screen.snapshot()[2], -int(signal.SIGKILL))
            self.assertTrue(wait_until(lambda: not pid_alive(child_pid), 3.0), "a child outlived the kill")
            self.app.handle_key(ord("q"))
            self.assertIsInstance(self.app.top(), overview.OverviewScreen)


class ScreenContentTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.app.rescan()
        self.app.git = make_git(last_fetch=1000.0, hint="")

    def test_rescan_and_the_overview_show_banner_tools_counts_and_menu_and_its_keys_report_errors(self):
        by_key = {s.key: s for s in self.app.statuses}
        self.assertEqual((by_key[("shared", "alpha")].state, by_key[("shared", "beta")].state),
                         (State.INSTALLED, State.MODIFIED))
        self.assertIn(("claude", "gamma"), self.app.catalog)
        self.assertIn(("shared", "foreign1"), self.app.installed)
        self.assertTrue(self.app.repo_issues)
        with mock.patch.dict(os.environ, {"INSTALLER_ASCII": "1"}):
            lines = overview.build_lines(self.app, 80, now=1000.0 + 300)
        text = "\n".join("".join(t for t, _ in row) for row in lines)
        for expected in ("Git: up to date with origin/main", "fetched 5 min ago", "main @ abc1234",
                         "Detected tools:", "+ claude", "Installed", "shared"):
            self.assertIn(expected, text)
        for number, label, _ in overview.MENU:
            self.assertIn(f"{number}  {label}", text)
        self.assertEqual(overview.fetch_age_text(None), "never fetched")
        self.assertEqual([overview.fetch_age_text(0.0, now=n) for n in (7 * 60, 5, 5 * 3600)],
                         ["fetched 7 min ago", "fetched just now", "fetched 5 h ago"])
        screen = overview.OverviewScreen()
        self.assertIsNone(screen.handle_key(ord("c"), self.app))
        self.assertIsInstance(self.app.top(), caps_screen.CapabilitiesScreen)
        with mock.patch.object(self.app, "start_wizard", side_effect=RuntimeError("no wizard")):
            screen.handle_key(ord("S"), self.app)
        self.assertIn("no wizard", self.app.message)


if __name__ == "__main__":
    unittest.main()
