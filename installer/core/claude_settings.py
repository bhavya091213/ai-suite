"""Patch and sanity-check ``~/.claude/settings.json``.

Two pure, terminal-free functions:

* ``patch_env`` rewrites the top-level ``env`` object and nothing else. The
  document is parsed (key order preserved), the ``env`` block is rebuilt as a
  new dict, and the whole thing is dumped again with ``indent=2`` and a
  trailing newline. Every other key keeps its value and its position.
* ``warnings`` reports *real* problems only (a local proxy URL with no proxy
  installed, an unknown hook profile). It never raises, so ``doctor`` can call
  it on any file.

Callers back the file up before writing the patched text back.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional, Tuple

ENV_KEY = "env"
BASE_URL_KEY = "ANTHROPIC_BASE_URL"
HOOK_PROFILE_KEY = "ECC_HOOK_PROFILE"
HOOK_PROFILES: Tuple[str, ...] = ("minimal", "standard", "strict")
LOCAL_URL_MARKERS: Tuple[str, ...] = ("127.0.0.1", "localhost")


def _parse(text: str) -> Dict[str, Any]:
    """Parse settings text into an order-preserving dict.

    Blank text counts as an empty object (a missing file is read as ``""``).
    Raises ``ValueError`` with a readable message for invalid JSON or for a
    top-level value that is not an object.
    """
    if not text.strip():
        return {}
    try:
        data = json.loads(text, object_pairs_hook=dict)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "settings.json is not valid JSON: %s (line %d, column %d)" % (exc.msg, exc.lineno, exc.colno)
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("settings.json must contain a JSON object at the top level")
    return data


def _check_updates(updates: Mapping[str, Optional[str]]) -> None:
    for key, value in updates.items():
        if value is not None and not isinstance(value, str):
            raise ValueError("env value for %s must be a string or None, got %s" % (key, type(value).__name__))


def _merged_env(current: Any, updates: Mapping[str, Optional[str]]) -> Dict[str, str]:
    """Return a new env dict: existing order kept, updates applied, ``None`` removes."""
    if current is None:
        base: Dict[str, Any] = {}
    elif isinstance(current, dict):
        base = dict(current)
    else:
        raise ValueError('settings.json "env" must be a JSON object')
    for key, value in updates.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def patch_env(text: str, updates: Mapping[str, Optional[str]]) -> str:
    """Set (str) or remove (None) keys in the ``env`` block of a settings.json text.

    ``env`` is created when absent (appended after the existing keys) and
    dropped entirely when it ends up empty. Everything else is preserved in
    order. Output is ``json.dumps(indent=2)`` plus a trailing newline.

    Raises ``ValueError`` for invalid JSON, a non-object document or ``env``,
    or a non-string update value.
    """
    _check_updates(updates)
    data = _parse(text)
    env = _merged_env(data.get(ENV_KEY), updates)
    if ENV_KEY in data:
        result: Dict[str, Any] = {k: (env if k == ENV_KEY else v) for k, v in data.items()}
        if not env:
            del result[ENV_KEY]
    else:
        result = dict(data)
        if env:
            result[ENV_KEY] = env
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def _headroom_missing(context: Mapping) -> bool:
    """True only when the context positively says headroom is not available."""
    profile = context.get("profile") if isinstance(context, Mapping) else None
    if not isinstance(profile, Mapping) or "headroom" not in profile:
        return False
    return not profile["headroom"]


def _env_of(data: Mapping) -> Tuple[Mapping, Tuple[str, ...]]:
    env = data.get(ENV_KEY)
    if env is None:
        return {}, ()
    if not isinstance(env, Mapping):
        return {}, ('settings.json "env" must be a JSON object',)
    return env, ()


def warnings(text: str, context: Mapping) -> Tuple[str, ...]:
    """Real problems in a settings.json text, as human strings (empty when fine).

    * a local ``ANTHROPIC_BASE_URL`` (127.0.0.1 / localhost) while
      ``context["profile"]["headroom"]`` is false;
    * ``ECC_HOOK_PROFILE`` present but not minimal / standard / strict;
    * unparsable JSON (reported, never raised).
    """
    try:
        data = _parse(text)
    except ValueError as exc:
        return (str(exc),)
    env, found = _env_of(data)
    out = list(found)
    url = env.get(BASE_URL_KEY)
    if isinstance(url, str) and _headroom_missing(context):
        if any(marker in url.lower() for marker in LOCAL_URL_MARKERS):
            out.append(
                "env.%s points at %s but headroom is not installed - every request will fail"
                % (BASE_URL_KEY, url)
            )
    if HOOK_PROFILE_KEY in env and env[HOOK_PROFILE_KEY] not in HOOK_PROFILES:
        out.append(
            "env.%s is %s; expected one of %s"
            % (HOOK_PROFILE_KEY, json.dumps(env[HOOK_PROFILE_KEY]), ", ".join(HOOK_PROFILES))
        )
    return tuple(out)
