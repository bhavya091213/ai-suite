"""Dialogs pushed only through App.confirm() and App.run_command().

ConfirmScreen lists planned filesystem operations, applies them on ``y`` and
shows one result line per operation. OutputScreen streams a subprocess (argument
list, never a shell) into a scrollable pane. Both own the keyboard while open
(``editing()`` is True), so the App's global keys cannot close them by accident.

The command runs in its own session, so stopping it signals the whole process group
(SIGTERM, then SIGKILL after a grace period): the children an install script starts
stop with it, and the pane only closes once nothing is left running.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import signal
import subprocess
import threading
import time
from typing import Any, Callable, List, Optional, Sequence, Tuple

from installer.core import actions
from installer.core.paths import Paths
from installer.core.types import Operation, OpResult
from installer.tui import draw
from installer.tui.base import POP, Screen

BACKUP_KINDS = ("backup", "unlink-to-backup")
ESC = 27
KILL_GRACE_SECONDS = 2.0  # SIGTERM -> SIGKILL delay, and again how long to wait for the pipe to close
_HAS_GROUPS = hasattr(os, "killpg")
_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def call_flexible(callback: Callable[..., Any], *args: Any) -> Any:
    """Call `callback` with as many of `args` as its signature accepts (0..len(args))."""
    try:
        params = list(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):
        return callback(*args)
    if any(p.kind == p.VAR_POSITIONAL for p in params):
        return callback(*args)
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return callback(*args[:len(positional)])


def derive_backup_root(ops: Sequence[Operation], paths: Paths) -> Optional[str]:
    """The ``<agents_home>/backups/<label>-<stamp>`` directory the backup ops land in, if any."""
    base = os.path.join(paths.agents_home, "backups")
    for op in ops:
        if op.kind not in BACKUP_KINDS:
            continue
        rel = os.path.relpath(op.dst, base)
        if not rel.startswith(os.pardir):
            return os.path.join(base, rel.split(os.sep)[0])
        return os.path.dirname(os.path.dirname(op.dst))
    return None


# ------------------------------------------------------------- ConfirmScreen


class ConfirmScreen(Screen):
    """Numbered operation list -> ``y`` apply / ``n`` cancel -> results log -> any key returns."""

    tab = None

    def __init__(self, ops: Sequence[Operation], title: str, paths: Paths,
                 on_done: Optional[Callable[..., Any]] = None,
                 backup_root: Optional[str] = None) -> None:
        self.ops: Tuple[Operation, ...] = tuple(ops)
        self.title = title
        self.paths = paths
        self.on_done = on_done
        self.backup_root = backup_root or derive_backup_root(self.ops, paths)
        self.results: Optional[Tuple[OpResult, ...]] = None
        self._top = 0
        self._height = 1

    def editing(self) -> bool:
        return True

    # ----------------------------------------------------------- content

    def ask_lines(self) -> Tuple[draw.Line, ...]:
        count = len(self.ops)
        head = f"{count} operation{'s' if count != 1 else ''} will run. Nothing is deleted: replaced items move to a backup."
        lines: List[draw.Line] = [(head, draw.attr("title")), ""]
        for number, op in enumerate(self.ops, 1):
            lines.append(f"{number:>3}. {actions.describe(op, self.paths)}")
        lines.append("")
        if self.backup_root:
            lines.append(f"Backups go to: {self.paths.display(self.backup_root)}")
        return tuple(lines)

    def result_lines(self) -> Tuple[draw.Line, ...]:
        results = self.results or ()
        failed = sum(1 for r in results if not r.ok)
        summary = f"{len(results) - failed} ok, {failed} failed"
        lines: List[draw.Line] = [(summary, draw.attr("error" if failed else "ok")), ""]
        for number, result in enumerate(results, 1):
            lines.append(self._result_line(number, result))
        skipped = len(self.ops) - len(results)
        if skipped > 0:
            lines.append((f"      {skipped} later operation(s) were not run after the failure", draw.attr("warn")))
        lines.append("")
        if self.backup_root:
            lines.append(f"Backup root: {self.paths.display(self.backup_root)}")
        lines.append("Press any key to return.")
        return tuple(lines)

    def _result_line(self, number: int, result: OpResult) -> draw.Line:
        described = actions.describe(result.op, self.paths)
        if result.ok:
            return (f"{number:>3}. ok      {described}", draw.attr("ok"))
        return (f"{number:>3}. FAILED  {described}  -- {result.message}", draw.attr("error"))

    # ------------------------------------------------------------- draw

    def draw(self, stdscr, app) -> None:
        hints = ("y apply   n/q cancel   j/k scroll" if self.results is None
                 else "any key returns (arrows scroll long logs)")
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, hints)
        lines = self.ask_lines() if self.results is None else self.result_lines()
        self._height = height
        self._top = draw.clamp_top(self._top, len(lines), height)
        draw.draw_text(stdscr, y0, x0, height, width, lines, self._top)

    # -------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            if self.results is None:
                return self._ask_key(key, app)
            return self._done_key(key, app)
        except Exception as exc:  # noqa: BLE001 - a dialog must never crash the app
            app.set_message(f"error: {type(exc).__name__}: {exc}")
            return None

    def _ask_key(self, key: int, app) -> Optional[str]:
        if key in (ord("y"), ord("Y")):
            self.results = actions.apply(self.ops)
            self._top = 0
            failed = sum(1 for r in self.results if not r.ok)
            if failed:
                app.set_message(f"{failed} operation(s) failed - see the log")
            return None
        if key in (ord("n"), ord("N"), ord("q"), ESC):
            return POP
        total = len(self.ask_lines())
        moved = draw.scroll_key(key, self._top, total, self._height)
        if moved is not None:
            self._top = moved
        return None

    def _done_key(self, key: int, app) -> Optional[str]:
        total = len(self.result_lines())
        if total > self._height and key != ord(" "):
            moved = draw.scroll_key(key, self._top, total, self._height)
            if moved is not None:
                self._top = moved
                return None
        return self._finish(app)

    def _finish(self, app) -> Optional[str]:
        app.pop()
        results = self.results or ()
        if self.on_done is not None:
            try:
                call_flexible(self.on_done, results)
            except Exception as exc:  # noqa: BLE001
                app.set_message(f"after-action error: {type(exc).__name__}: {exc}")
        app.rescan()
        return None


# -------------------------------------------------------------- OutputScreen


class OutputScreen(Screen):
    """Streams a command's merged stdout+stderr. ``q`` closes once it has finished (or was stopped)."""

    tab = None

    def __init__(self, argv: Sequence[str], title: str, cwd: Optional[str] = None,
                 on_done: Optional[Callable[..., Any]] = None,
                 popen: Callable[..., Any] = subprocess.Popen) -> None:
        self.argv: Tuple[str, ...] = tuple(argv)
        self.title = title
        self.cwd = cwd
        self.on_done = on_done
        self._popen = popen
        self._lock = threading.Lock()
        self._lines: List[str] = []
        self._exit_code: Optional[int] = None
        self._finished = False
        self._started = False
        self._proc: Any = None
        self._grouped = False  # True when the command leads its own process group
        self._follow = True
        self._top = 0
        self._height = 1
        self._kill_prompt = False
        self._kill_requested = False

    def editing(self) -> bool:
        return True

    def on_enter(self, app) -> None:
        self.start()

    # --------------------------------------------------------- process

    def start(self) -> None:
        """Launch the command and its reader thread (idempotent)."""
        if self._started:
            return
        self._started = True
        options = dict(cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, text=True, bufsize=1, errors="replace")
        if _HAS_GROUPS:
            options["start_new_session"] = True  # own process group: the whole tree can be stopped
        try:
            proc = self._popen(list(self.argv), **options)
        except (OSError, ValueError) as exc:
            self._append(f"failed to start: {exc}")
            self._finish(127)
            return
        self._grouped = _HAS_GROUPS
        self._proc = proc
        threading.Thread(target=self._read, args=(proc,), daemon=True).start()

    def _read(self, proc: Any) -> None:
        code = -1
        try:
            for line in proc.stdout:
                self._append(line.rstrip("\r\n"))
        except Exception as exc:  # noqa: BLE001 - reader thread must not die silently
            self._append(f"[read error: {exc}]")
        finally:
            with contextlib.suppress(Exception):
                code = proc.wait()
            with contextlib.suppress(Exception):
                proc.stdout.close()
            self._finish(code)

    def _append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)

    def _finish(self, code: int) -> bool:
        """Record the exit code once; False when the command was already marked finished."""
        with self._lock:
            if self._finished:
                return False
            self._exit_code = code
            self._finished = True
            return True

    def snapshot(self) -> Tuple[Tuple[str, ...], bool, Optional[int]]:
        """(lines so far, finished, exit code) taken under the lock."""
        with self._lock:
            return tuple(self._lines), self._finished, self._exit_code

    @property
    def running(self) -> bool:
        return self._started and not self.snapshot()[1]

    def streaming(self) -> bool:
        """True while output may still arrive; the App polls with a short timeout then."""
        return self.running

    # ------------------------------------------------------------ stopping

    def _signal(self, sig: int) -> None:
        """Send `sig` to the command's whole process group (children included), else to the command."""
        proc = self._proc
        pid = getattr(proc, "pid", None)
        try:
            if self._grouped and isinstance(pid, int) and pid > 1 and pid != os.getpgrp():
                os.killpg(pid, sig)
            elif sig == _SIGKILL:
                proc.kill()
            else:
                proc.terminate()
        except ProcessLookupError:
            pass  # it is already gone
        except Exception as exc:  # noqa: BLE001 - report it; the escalation in _stop() still follows
            self._append(f"[could not signal the command: {exc}]")

    def _wait_finished(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while not self.snapshot()[1]:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)
        return True

    def _stop(self, grace: float) -> None:
        """SIGTERM the process group, SIGKILL it after `grace` seconds, and leave the pane closable.

        Blocks for at most about ``2 * grace``. When something outside the group (a detached
        daemon) still holds the output pipe open once the command itself is dead, the pane is
        marked finished anyway so the user is never stuck in it.
        """
        if self._proc is None or not self.running:
            return
        self._signal(signal.SIGTERM)
        if self._wait_finished(grace):
            return
        self._signal(_SIGKILL)
        if self._wait_finished(grace):
            return
        code = self._proc.poll()
        if self._finish(-int(_SIGKILL) if code is None else code):
            self._append("[stopped; a detached process still holds the output open]")

    def close(self, grace: Optional[float] = None) -> None:
        """Stop a still-running command and everything it started (called when the app exits)."""
        self._stop(KILL_GRACE_SECONDS if grace is None else grace)

    def _kill(self) -> None:
        """Stop the command at the user's request; the SIGKILL escalation runs off the UI thread."""
        if not self.running:
            return
        self._kill_requested = True
        self._append("[terminated by user]")
        threading.Thread(target=self._stop, args=(KILL_GRACE_SECONDS,), daemon=True).start()

    # -------------------------------------------------------------- draw

    def draw(self, stdscr, app) -> None:
        lines, finished, code = self.snapshot()
        hints = ("arrows/PgUp/PgDn scroll   q close" if finished
                 else "arrows/PgUp/PgDn scroll   k kill the command")
        y0, x0, height, width = draw.draw_frame(stdscr, app, self.title, hints)
        body = max(1, height - 1)
        self._height = body
        bottom = max(0, len(lines) - body)
        self._top = bottom if self._follow else draw.clamp_top(self._top, len(lines), body)
        draw.draw_text(stdscr, y0, x0, body, width, lines, self._top)
        text, name = self._status(finished, code)
        draw.safe_addstr(stdscr, y0 + height - 1, x0, text, draw.attr(name), width)

    def _status(self, finished: bool, code: Optional[int]) -> Tuple[str, str]:
        if self._kill_prompt:
            return "kill the running command? y/n", "warn"
        if not finished:
            return ("stopping...", "warn") if self._kill_requested else ("running...", "warn")
        return f"exit code {code}", "ok" if code == 0 else "error"

    # -------------------------------------------------------------- keys

    def handle_key(self, key: int, app) -> Optional[str]:
        try:
            return self._key(key, app)
        except Exception as exc:  # noqa: BLE001
            app.set_message(f"error: {type(exc).__name__}: {exc}")
            return None

    def _key(self, key: int, app) -> Optional[str]:
        if self._kill_prompt:
            self._kill_prompt = False
            if key in (ord("y"), ord("Y")):
                self._kill()
                app.set_message("stopping the command - press q to close once it has stopped")
            return None
        if key == ord("k") and self.running:
            self._kill_prompt = True
            return None
        if key in (ord("q"), ESC):
            return self._try_close(app)
        self._scroll(key)
        return None

    def _try_close(self, app) -> Optional[str]:
        """Close only when the command has finished: a running one keeps its pane (and is never orphaned)."""
        _, finished, code = self.snapshot()
        if not finished:
            app.set_message("still stopping - press q again in a moment" if self._kill_requested
                            else "still running - press k to kill it, then q")
            return None
        app.pop_then(lambda: self._report(app, code))
        return None

    def _report(self, app, code: Optional[int]) -> None:
        """Rescan and call on_done; runs after this screen left the stack, so on_done may push or switch tabs."""
        try:
            app.rescan()
        except Exception as exc:  # noqa: BLE001
            app.set_message(f"rescan error: {type(exc).__name__}: {exc}")
        if self.on_done is None:
            return
        try:
            call_flexible(self.on_done, code)
        except Exception as exc:  # noqa: BLE001
            app.set_message(f"after-command error: {type(exc).__name__}: {exc}")

    def _scroll(self, key: int) -> None:
        lines, _, _ = self.snapshot()
        total = len(lines)
        if key == ord("G"):
            self._follow = True
            return
        if key == ord("g"):
            self._follow, self._top = False, 0
            return
        current = max(0, total - self._height) if self._follow else self._top
        moved = draw.scroll_key(key, current, total, self._height, letters=False)
        if moved is None:
            return
        self._top = moved
        self._follow = moved >= max(0, total - self._height)
