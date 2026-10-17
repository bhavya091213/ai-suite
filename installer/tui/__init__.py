"""curses user interface. Everything that needs a terminal lives here."""

from __future__ import annotations

import contextlib
import signal
from typing import Dict, Iterator


@contextlib.contextmanager
def exit_on_hangup() -> Iterator[None]:
    """Turn SIGHUP/SIGTERM into ``SystemExit`` while the UI runs, so ``App.shutdown()`` still runs.

    A command started from the UI leads its own session and no longer receives the terminal's
    hangup, so without this a closed terminal would leave an install script running unattended.
    """
    previous: Dict[int, object] = {}

    def handler(signum, frame):  # noqa: ARG001 - signature fixed by signal.signal
        raise SystemExit(128 + signum)

    for name in ("SIGHUP", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, handler)
        except (ValueError, OSError):  # not the main thread, or not allowed here
            continue
    try:
        yield
    finally:
        for signum, old in previous.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signum, signal.SIG_DFL if old is None else old)


def run(paths, start_screen: str = "overview") -> int:
    """Run the interactive UI and return the process exit code.

    ``installer.tui.app`` (and with it curses) is imported lazily so that merely
    importing ``installer.tui`` stays cheap and works without a terminal.
    """
    from installer.tui.app import run as run_app

    with exit_on_hangup():
        return run_app(paths, start_screen)
