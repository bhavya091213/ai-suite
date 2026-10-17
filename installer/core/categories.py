"""Skill categories and tags: the grouping the installer and the Claude mod filter by.

``shared/skill-categories.json`` maps a skill name to one category and to any number of tags, and
fixes the display order of both::

    {"order": ["Orchestration", ..., "Other"], "categories": {"<skill name>": "<category>"},
     "tags_order": ["design", ...], "tags": {"<skill name>": ["design", "frontend"]}}

A category is the README section a skill sits in (exactly one per skill); a tag is a use-case
filter (a skill has several). The file is read from the repo (like ``shared/extras.json``) and
installed nowhere. A skill has the same category and tags whatever its scope, so a Claude/Codex
variant pair shares them. A skill without a category is "Other"; one without tags has none.
Loading never raises: a missing or unusable file gives empty mappings, an order of just "Other"
and no tags, so filtering degrades instead of breaking the commands that call it.

Terminal-free and pure apart from the one file read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from installer.core.paths import Paths

CATEGORIES_RELPATH = os.path.join("shared", "skill-categories.json")
DEFAULT_CATEGORY = "Other"

_EMPTY: Mapping[str, str] = MappingProxyType({})
_NO_TAGS: Mapping[str, Tuple[str, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class Categories:
    """Display orders plus the skill name -> category and skill name -> tags mappings."""

    order: Tuple[str, ...] = (DEFAULT_CATEGORY,)
    by_name: Mapping[str, str] = field(default_factory=lambda: _EMPTY)
    tags_order: Tuple[str, ...] = ()
    tags_by_name: Mapping[str, Tuple[str, ...]] = field(default_factory=lambda: _NO_TAGS)


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(raw: Any) -> Mapping[str, str]:
    """The valid ``name -> category`` pairs of the file's "categories" object."""
    if not isinstance(raw, dict):
        return _EMPTY
    pairs = {_clean(name): _clean(category) for name, category in raw.items()}
    return MappingProxyType({name: category for name, category in pairs.items() if name and category})


def _unique(items: Iterable[Any]) -> List[str]:
    """The non-empty strings of `items`, trimmed, without repeats, in first-seen order."""
    seen: List[str] = []
    for item in items:
        text = _clean(item)
        if text and text not in seen:
            seen.append(text)
    return seen


def _order(raw: Any, used: Iterable[str]) -> Tuple[str, ...]:
    """Declared categories (deduplicated), then any used but undeclared one, with "Other" present."""
    declared = _unique(raw if isinstance(raw, list) else ())
    declared.extend(sorted(set(used) - set(declared) - {DEFAULT_CATEGORY}))
    if DEFAULT_CATEGORY not in declared:
        declared.append(DEFAULT_CATEGORY)
    return tuple(declared)


def _tag_mapping(raw: Any) -> Mapping[str, Tuple[str, ...]]:
    """The ``name -> tags`` pairs of the file's "tags" object; entries that are not a list of
    strings, or that end up with no tag, are dropped."""
    if not isinstance(raw, dict):
        return _NO_TAGS
    pairs = {_clean(name): tuple(_unique(tags)) if isinstance(tags, list) else ()
             for name, tags in raw.items()}
    return MappingProxyType({name: tags for name, tags in pairs.items() if name and tags})


def _tag_order(raw: Any, used: Iterable[str]) -> Tuple[str, ...]:
    """Declared tags (deduplicated), then any used but undeclared one. There is no default tag."""
    declared = _unique(raw if isinstance(raw, list) else ())
    declared.extend(sorted(set(used) - set(declared)))
    return tuple(declared)


def load(paths: Paths) -> Categories:
    """The categories and tags from ``<repo>/shared/skill-categories.json``; defaults when absent
    or unusable."""
    try:
        with open(os.path.join(paths.repo_dir, CATEGORIES_RELPATH), encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError):  # RecursionError: absurdly nested JSON
        return Categories()
    if not isinstance(data, dict):
        return Categories()
    by_name = _mapping(data.get("categories"))
    tags_by_name = _tag_mapping(data.get("tags"))
    used_tags = {tag for tags in tags_by_name.values() for tag in tags}
    return Categories(order=_order(data.get("order"), by_name.values()), by_name=by_name,
                      tags_order=_tag_order(data.get("tags_order"), used_tags),
                      tags_by_name=tags_by_name)


def category_of(cats: Categories, name: str) -> str:
    """The category of skill `name`; "Other" when it is not mapped."""
    return cats.by_name.get(name, DEFAULT_CATEGORY)


def tags_of(cats: Categories, name: str) -> Tuple[str, ...]:
    """The tags of skill `name`, in file order; empty when it is not mapped."""
    return cats.tags_by_name.get(name, ())


def has_tag(cats: Categories, name: str, tag: str) -> bool:
    """Whether skill `name` carries `tag` (case-insensitive)."""
    wanted = tag.strip().casefold()
    return any(own.casefold() == wanted for own in tags_of(cats, name))


def canonical(choices: Sequence[str], wanted: str) -> Optional[str]:
    """The entry of `choices` that equals `wanted` ignoring case and outer spaces, else None."""
    target = wanted.strip().casefold()
    return next((choice for choice in choices if choice.casefold() == target), None)


def counts(cats: Categories, names: Iterable[str]) -> Tuple[Tuple[str, int], ...]:
    """``(category, how many of names)`` for every category, in ``cats.order`` (zeros included).

    Each entry of `names` counts once, so pass distinct names to count skills."""
    tally = {category: 0 for category in cats.order}
    for name in names:
        category = category_of(cats, name)
        tally[category] = tally.get(category, 0) + 1
    return tuple(tally.items())


def tag_counts(cats: Categories, names: Iterable[str]) -> Tuple[Tuple[str, int], ...]:
    """``(tag, how many of names carry it)`` for every tag, in ``cats.tags_order`` (zeros
    included), then any tag the names carry that the order does not list, sorted.

    A skill has several tags, so the counts add up to more than the number of skills. Each entry
    of `names` counts once per tag, so pass distinct names to count skills."""
    tally = {tag: 0 for tag in cats.tags_order}
    extra: dict = {}
    for name in names:
        for tag in tags_of(cats, name):
            target = tally if tag in tally else extra
            target[tag] = target.get(tag, 0) + 1
    return tuple(tally.items()) + tuple(sorted(extra.items()))
