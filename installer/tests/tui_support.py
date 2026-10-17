"""Shared helpers for the terminal-free TUI tests: recording curses windows, sample GitInfo/Capabilities and
AppCase, a test case with an App over the fixture repo and home (HOME pointed at the fixture home)."""

from __future__ import annotations

import curses
import json
import os
import tempfile
import unittest
from typing import Any, Callable, Dict
from unittest import mock

from installer.core import capabilities
from installer.core.capabilities import PROBES, Capabilities, Capability
from installer.core.types import GitInfo
from installer.tests import fixtures
from installer.tui.app import App

ENTER, ESC = 10, 27
PROMPT = "installer.tui.draw.prompt_line"


class FakeWindow:
    """Records writes into a character grid, raising curses.error like a real window."""

    def __init__(self, rows: int = 24, cols: int = 80, keys=()):
        self.rows, self.cols = rows, cols
        self.cells = [[" "] * cols for _ in range(rows)]
        self.attrs = [[0] * cols for _ in range(rows)]
        self.keys = list(keys)

    def getmaxyx(self):
        return self.rows, self.cols

    def addstr(self, y, x, text, attr=0):
        if not (0 <= y < self.rows and 0 <= x < self.cols):
            raise curses.error("out of range")
        for offset, char in enumerate(text):
            if x + offset >= self.cols:
                raise curses.error("past the edge")
            self.cells[y][x + offset] = char
            self.attrs[y][x + offset] = attr

    def erase(self):
        self.__init__(self.rows, self.cols, self.keys)

    def row(self, y):
        return "".join(self.cells[y]).rstrip()

    def get_wch(self):
        return self.keys.pop(0)

    move = refresh = timeout = lambda *args: None


def make_git(**changes) -> GitInfo:
    base = dict(available=True, version="2.40", is_repo=True, branch="main", head="abc1234",
                upstream="origin/main", ahead=0, behind=0, dirty=False, last_fetch=None,
                remote_url=None, message="up to date with origin/main", hint="")
    return GitInfo(**{**base, **changes})


def make_caps(missing=()) -> Capabilities:
    items = {name: Capability(name, name not in missing, None if name in missing else "1.0",
                              None, "found" if name not in missing else "not found")
             for name in PROBES}
    return Capabilities(items=items)


class FakeWin:
    """Just enough of a curses window for draw.safe_addstr / draw_frame."""

    def __init__(self, rows: int = 30, cols: int = 100) -> None:
        self.rows, self.cols, self.grid = rows, cols, [[" "] * cols for _ in range(rows)]

    def getmaxyx(self):
        return self.rows, self.cols

    def addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        self.grid[y][x:x + len(text)] = list(text[:self.cols - x])

    def text(self) -> str:
        return "\n".join("".join(row).rstrip() for row in self.grid)


class Recorder(list):
    """Stands in for App.run_command: one dict per call."""

    def __call__(self, argv, title, cwd=None, on_done=None) -> None:
        self.append({"argv": list(argv), "title": title, "cwd": cwd, "on_done": on_done})


class AppCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.paths = fixtures.build(self.root)
        self.home = os.path.join(self.root, "home")
        self.set_home(self.home)
        self.use_caps("claude")

    def set_home(self, home: str) -> None:
        """Run the process under `home`; the fixture home is the ordinary, non-relocated case."""
        patcher = mock.patch.dict(os.environ, {"HOME": home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def relocate(self) -> str:
        """Make the session's home differ from the process $HOME, as `--home DIR` does."""
        elsewhere = os.path.join(self.root, "real-home")
        os.makedirs(elsewhere, exist_ok=True)
        self.set_home(elsewhere)
        return elsewhere

    def use_caps(self, *present: str, record: bool = True) -> None:
        caps = capabilities.Capabilities(items={n: capabilities.Capability(n, n in present, None, None, "")
                                                for n in capabilities.PROBES})
        self.app, self.run = App(self.paths, None, caps=caps), Recorder()
        if record:
            self.app.run_command = self.run

    def press(self, screen, *keys) -> None:
        for key in keys:
            screen.handle_key(key if isinstance(key, int) else ord(key), self.app)

    def goto(self, screen, match: Callable[[Any], bool]) -> Any:
        self.press(screen, "g")
        for _ in range(60):
            row = screen.model.current()
            if row is not None and match(row):
                return row
            self.press(screen, "j")
        self.fail("row not found")

    def write_config(self, data: Dict[str, Any]) -> None:
        fixtures.write(os.path.join(self.paths.agents_home, "config.json"), json.dumps(data))
        self.app.reload_config()

    def write_repo(self, rel: str, text: str) -> None:
        fixtures.write(os.path.join(self.paths.repo_dir, *rel.split("/")), text)

    def render(self, screen) -> str:
        win = FakeWin()
        screen.draw(win, self.app)
        return win.text()
