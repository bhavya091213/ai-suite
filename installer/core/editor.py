"""Pick the user's editor and run it on a file.

Pure helpers: the curses suspend/resume dance belongs to the TUI, which wraps
``edit_file``. Nothing here prints or reads stdin.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections import abc
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

FALLBACK_EDITORS: Tuple[str, ...] = ("nano", "vim", "vi")
LAST_RESORT: Tuple[str, ...] = ("vi",)


def _split(value: object) -> Tuple[str, ...]:
    """shlex-split a candidate command; empty, non-string or unparsable values give ``()``."""
    if not isinstance(value, str) or not value.strip():
        return ()
    try:
        return tuple(shlex.split(value))
    except ValueError:  # unbalanced quotes: treat the source as unusable
        return ()


def _config_data(config: Any) -> Mapping[str, Any]:
    """The mapping behind ``config``: a ``Config`` (its ``.data``), a plain mapping, or ``None``.

    Duck-typed on purpose so this module never imports ``installer.core.config``.
    Anything else gives an empty mapping.
    """
    if isinstance(config, abc.Mapping):
        return config
    data = getattr(config, "data", None)
    return data if isinstance(data, abc.Mapping) else {}


def resolve_editor(
    config: Any,
    env: Mapping[str, str],
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[str, ...]:
    """Return the editor argv prefix, e.g. ``("code", "--wait")``.

    ``config`` is a ``Config`` (anything with a mapping ``.data``), a plain
    mapping such as ``config.data``, or ``None``; this module deliberately does
    not import ``installer.core.config``. Order of precedence:
    ``config["editor"]``, ``$VISUAL``, ``$EDITOR``, the first of nano / vim / vi
    that ``which`` finds, and finally ``("vi",)``. A source that is empty or
    cannot be shell-split is skipped.
    """
    candidates = (
        _config_data(config).get("editor"),
        env.get("VISUAL"),
        env.get("EDITOR"),
    )
    for candidate in candidates:
        argv = _split(candidate)
        if argv:
            return argv
    for name in FALLBACK_EDITORS:
        if which(name):
            return (name,)
    return LAST_RESORT


def edit_file(
    path: str,
    argv: Sequence[str],
    run: Callable[[Sequence[str]], int] = subprocess.call,
) -> int:
    """Run ``argv + [path]`` and return the editor's exit status.

    A plain blocking call; the TUI suspends curses around it. A path that
    starts with ``-`` is passed as ``./<path>`` so an editor cannot mistake it
    for an option. Raises ``ValueError`` for an empty ``argv`` and lets
    ``OSError`` (editor not found / not executable) propagate so the caller
    can show the reason.
    """
    if not argv:
        raise ValueError("editor command is empty")
    target = os.path.join(".", path) if path.startswith("-") else path
    return int(run(list(argv) + [target]))
