"""End-to-end smoke test: run the real curses UI in a pseudo terminal and press keys.

``python3 -m installer tui --repo <fixture repo> --home <fixture home>`` is spawned on a
100x30 pseudo terminal (``pty.openpty`` + ``subprocess``, ``TERM=xterm-256color``). Using
``subprocess`` instead of ``pty.fork`` keeps Python code out of the forked child, which is
unsafe once other tests have left threads running. The test types through the main
screens and asserts that the process exits 0 and that the screens it visited were drawn.

Skipped where ``pty`` / ``fork`` / ``curses`` are unavailable (Windows).
"""

from __future__ import annotations

import errno
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Optional, Sequence, Tuple

from installer.core import config as cfg
from installer.core import workflows
from installer.tests import fixtures

try:  # pragma: no cover - platform dependent
    import fcntl
    import pty
    import struct
    import termios
    import curses  # noqa: F401 - only checked for availability
    HAVE_PTY = hasattr(pty, "openpty")
except ImportError:  # pragma: no cover
    HAVE_PTY = False

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROWS, COLS = 30, 100
KEY_GAP = 0.1
START_TIMEOUT = 20.0  # the first frame waits for the tool probes
EXIT_TIMEOUT = 15.0

# WALK is the tour from ARCHITECTURE.md (Skills, move, select, open the viewer, back, then each
# remaining tab and the help screen) with "1" (Overview) between tabs, because a tab jump
# replaces the whole stack and a "q" on a root screen would quit. Each step names a word only
# that screen draws. "0" opens the tenth tab (Workflows), the only screen whose list header
# says "Phases".
WORKFLOWS_MARKER = "Phases"
WALK: Tuple[Tuple[str, str], ...] = (
    ("2", "not-installed"), ("j", ""), (" ", ""), ("\r", "SKILL.md"), ("q", ""),
    ("6", "Guardrails"), ("1", ""), ("7", "rendered"), ("1", ""), ("9", "Category"),
    ("1", ""), ("0", WORKFLOWS_MARKER), ("1", ""), ("?", "Everywhere"), ("q", ""), ("Q", ""),
)

ANSI = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"      # CSI ... final byte
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[()][0-9A-Za-z]"            # charset selection
    r"|\x1b[=>78cDEHMNO]"              # single-character escapes
    r"|[\x0e\x0f]"                     # shift in / out
)


def strip_ansi(data: bytes) -> str:
    return ANSI.sub("", data.decode("utf-8", errors="replace"))


class PtyRun:
    """One child process on a pseudo terminal; reads its output as it goes."""

    def __init__(self, argv: Sequence[str], env: dict, cwd: str, rows: int = ROWS, cols: int = COLS) -> None:
        self.output = b""
        self.eof = False
        self.status: Optional[int] = None
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            self.proc = subprocess.Popen(list(argv), stdin=slave, stdout=slave, stderr=slave,
                                         env=env, cwd=cwd, close_fds=True, start_new_session=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)  # the child holds its own copy; EOF on `master` then means "child gone"
        self.fd = master

    def pump(self, seconds: float) -> None:
        """Collect output for up to `seconds` (returns early at end of file)."""
        deadline = time.monotonic() + seconds
        while not self.eof:
            left = deadline - time.monotonic()
            if left <= 0:
                return
            ready, _, _ = select.select([self.fd], [], [], min(left, 0.1))
            if ready:
                self._read_some()

    def _read_some(self) -> None:
        try:
            data = os.read(self.fd, 65536)
        except OSError as exc:  # EIO: the child closed its side (Linux)
            if exc.errno not in (errno.EIO, errno.EBADF):
                raise
            data = b""
        if data:
            self.output += data
        else:
            self.eof = True

    def text(self) -> str:
        return strip_ansi(self.output)

    def wait_for(self, needle: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.eof:
            if needle in self.text():
                return True
            self.pump(0.1)
        return needle in self.text()

    def send(self, key: str) -> bool:
        """Write one key; False when the child is already gone."""
        try:
            os.write(self.fd, key.encode("utf-8"))
            return True
        except OSError:
            return False

    def reap(self, timeout: float) -> Optional[int]:
        """Wait for the child to exit and return its status (None on timeout)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.1)
            code = self.proc.poll()
            if code is not None:
                self.status = code
                self.pump(0.2)  # drain what was written just before exit
                return code
        return None

    def exit_code(self) -> Optional[int]:
        """The exit status, or None when it is unknown or the child died from a signal."""
        return self.status if self.status is not None and self.status >= 0 else None

    def close(self) -> None:
        """Make sure no child outlives the test (stops only the process this test started)."""
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def _bin_dir_with_git(parent: str) -> str:
    """A PATH directory that exposes only ``git``.

    The UI probes ~17 tools at start (each with a timeout), which takes seconds and depends on
    what the machine has installed; an almost empty PATH keeps the run fast and repeatable.
    """
    bin_dir = os.path.join(parent, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    git = shutil.which("git")
    if git:
        os.symlink(git, os.path.join(bin_dir, "git"))
    return bin_dir


def _child_env(home: str, bin_dir: Optional[str] = None) -> dict:
    env = {key: value for key, value in os.environ.items()
           if key not in ("AGENTS_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "INSTALLER_ASCII")}
    env.update({"TERM": "xterm-256color", "HOME": home, "PYTHONDONTWRITEBYTECODE": "1",
                "LC_ALL": env.get("LC_ALL") or "en_US.UTF-8", "PYTHONUTF8": "1"})
    if bin_dir is not None:
        env["PATH"] = bin_dir
    return env


@unittest.skipUnless(HAVE_PTY and sys.platform != "win32", "needs a pseudo terminal (pty) and curses")
class TuiSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = fixtures.build(self._tmp.name)
        self.home = os.path.dirname(self.paths.agents_home)
        self.bin_dir = _bin_dir_with_git(self._tmp.name)
        self.run_: Optional[PtyRun] = None
        self.addCleanup(self._close)

    def _close(self) -> None:
        if self.run_ is not None:
            self.run_.close()

    def _write_default_config(self) -> None:
        config = cfg.load(self.paths)
        cfg.save(config, self.paths)
        self.assertTrue(cfg.load(self.paths).exists)

    def _spawn(self) -> PtyRun:
        argv = [sys.executable, "-m", "installer", "tui", "--repo", self.paths.repo_dir, "--home", self.home]
        self.run_ = PtyRun(argv, _child_env(self.home, self.bin_dir), PACKAGE_ROOT)
        return self.run_

    def _type(self, run: PtyRun, keys: Sequence[str]) -> int:
        """Send each key after a gap; stops when the child has exited. Returns keys delivered."""
        sent = 0
        for key in keys:
            run.pump(KEY_GAP)
            if run.eof or not run.send(key):
                break
            sent += 1
        return sent

    def _assert_clean_exit(self, run: PtyRun) -> None:
        status = run.reap(EXIT_TIMEOUT)
        self.assertIsNotNone(status, "installer did not exit within %.0fs\n%s" % (EXIT_TIMEOUT, run.text()[-1500:]))
        self.assertEqual(run.exit_code(), 0, "exit status %r\n%s" % (status, run.text()[-1500:]))

    # ------------------------------------------------------------------ tests

    def test_full_walk_through_draws_every_screen(self) -> None:
        self._write_default_config()
        run = self._spawn()
        self.assertTrue(run.wait_for("Overview", START_TIMEOUT), "no first frame:\n" + run.text()[-800:])
        for key, marker in WALK:
            run.pump(KEY_GAP)
            if marker == WORKFLOWS_MARKER:  # the output is cumulative: it must not be there already
                self.assertNotIn(marker, run.text(), "the Workflows header was drawn before key '0'")
            self.assertTrue(run.send(key), "child exited before %r\n%s" % (key, run.text()[-800:]))
            if marker:
                self.assertTrue(run.wait_for(marker, 3.0),
                                "after %r expected %r\n%s" % (key, marker, run.text()[-800:]))
        self._assert_clean_exit(run)
        shown = run.text()
        for label in ("Skills", "Settings", "Files", "Extras", "Overview", "Workflows", WORKFLOWS_MARKER):
            self.assertIn(label, shown)
        for bad in ("Traceback", "screen not available", "draw error", "error:"):
            self.assertNotIn(bad, shown)

    def test_workflow_from_the_example_is_saved_and_linked(self) -> None:
        """Workflows tab: N starts from the example, s plans the save, y applies it for real."""
        self._write_default_config()
        skill_dir = os.path.join(self.paths.agents_home, "skills", "research-design-build")
        self.assertFalse(os.path.exists(skill_dir))
        run = self._spawn()
        self.assertTrue(run.wait_for("Overview", START_TIMEOUT), "no first frame:\n" + run.text()[-800:])
        for key, marker in (("0", WORKFLOWS_MARKER), ("N", "New workflow"), ("s", "operations will run"),
                            ("y", "ok, 0 failed")):
            run.pump(KEY_GAP)
            self.assertTrue(run.send(key), "child exited before %r\n%s" % (key, run.text()[-800:]))
            self.assertTrue(run.wait_for(marker, 5.0), "after %r expected %r\n%s" % (key, marker, run.text()[-800:]))
        self._type(run, ("q", "Q"))  # any key leaves the results page; Q quits (nothing unsaved)
        self._assert_clean_exit(run)
        for name in ("workflow.json", "SKILL.md", os.path.join("agents", "openai.yaml")):
            self.assertTrue(os.path.isfile(os.path.join(skill_dir, name)), name)
        with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as handle:
            self.assertIn(workflows.MARKER, handle.read().splitlines())
        for consumer in ("claude", "codex"):
            link = os.path.join(self.paths.consumer_dir(consumer), "research-design-build")
            self.assertTrue(os.path.islink(link), link)
        self.assertNotIn("Traceback", run.text())

    def test_first_run_starts_in_the_wizard(self) -> None:
        self.assertFalse(os.path.exists(cfg.config_path(self.paths)))
        run = self._spawn()
        self.assertTrue(run.wait_for("Detected:", START_TIMEOUT), "no wizard text:\n" + run.text()[-800:])
        self.assertIn("wizard", run.text())
        run.pump(KEY_GAP)
        self.assertTrue(run.send("Q"))
        self._assert_clean_exit(run)
        self.assertFalse(os.path.exists(cfg.config_path(self.paths)), "the wizard must not write before 's'")


if __name__ == "__main__":
    unittest.main()
