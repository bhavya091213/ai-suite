"""Skill categories: the grouping the installer and the Claude mod filter by.

``shared/skill-categories.json`` maps a skill name to one category and fixes the display order::

    {"order": ["Orchestration", ..., "Other"], "categories": {"<skill name>": "<category>"}}

The file is read from the repo (like ``shared/extras.json``) and installed nowhere. A skill has one
category whatever its scope, so a Claude/Codex variant pair shares it. Anything unmapped is
"Other". Loading never raises: a missing or unusable file gives an empty mapping and an order of
just "Other", so filtering degrades instead of breaking the commands that call it.

Terminal-free and pure apart from the one file read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, List, Mapping, Tuple

from installer.core.paths import Paths

CATEGORIES_RELPATH = os.path.join("shared", "skill-categories.json")
DEFAULT_CATEGORY = "Other"

_EMPTY: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class Categories:
    """Display order of the categories plus the skill name -> category mapping."""

    order: Tuple[str, ...] = (DEFAULT_CATEGORY,)
    by_name: Mapping[str, str] = field(default_factory=lambda: _EMPTY)


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(raw: Any) -> Mapping[str, str]:
    """The valid ``name -> category`` pairs of the file's "categories" object."""
    if not isinstance(raw, dict):
        return _EMPTY
    pairs = {_clean(name): _clean(category) for name, category in raw.items()}
    return MappingProxyType({name: category for name, category in pairs.items() if name and category})


def _order(raw: Any, used: Iterable[str]) -> Tuple[str, ...]:
    """Declared categories (deduplicated), then any used but undeclared one, with "Other" present."""
    declared: List[str] = []
    for item in raw if isinstance(raw, list) else ():
        name = _clean(item)
        if name and name not in declared:
            declared.append(name)
    declared.extend(sorted(set(used) - set(declared) - {DEFAULT_CATEGORY}))
    if DEFAULT_CATEGORY not in declared:
        declared.append(DEFAULT_CATEGORY)
    return tuple(declared)


def load(paths: Paths) -> Categories:
    """The categories from ``<repo>/shared/skill-categories.json``; defaults when absent or unusable."""
    try:
        with open(os.path.join(paths.repo_dir, CATEGORIES_RELPATH), encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):  # RecursionError: absurdly nested JSON
        return Categories()
    if not isinstance(data, dict):
        return Categories()
    by_name = _mapping(data.get("categories"))
    return Categories(order=_order(data.get("order"), by_name.values()), by_name=by_name)


def category_of(cats: Categories, name: str) -> str:
    """The category of skill `name`; "Other" when it is not mapped."""
    return cats.by_name.get(name, DEFAULT_CATEGORY)


def counts(cats: Categories, names: Iterable[str]) -> Tuple[Tuple[str, int], ...]:
    """``(category, how many of names)`` for every category, in ``cats.order`` (zeros included).

    Each entry of `names` counts once, so pass distinct names to count skills."""
    tally = {category: 0 for category in cats.order}
    for name in names:
        category = category_of(cats, name)
        tally[category] = tally.get(category, 0) + 1
    return tuple(tally.items())
