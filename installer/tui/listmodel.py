"""ListModel: cursor, scroll offset, multi-selection and substring filter over
an immutable sequence. Pure Python (no curses), so screens stay testable.

`cursor` and `offset` are positions inside `filtered()`; `selected` holds
ORIGINAL indices into `items`, so a selection survives filtering and item
replacement. Every mutator returns a new ListModel; nothing mutates `self`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, FrozenSet, Generic, Iterable, Optional, Tuple, TypeVar

T = TypeVar("T")

Rows = Tuple[Tuple[int, T], ...]


def _clamp_view(cursor: int, offset: int, total: int, height: int) -> Tuple[int, int]:
    """Keep `cursor` inside [0, total) and `offset` so the cursor is on screen.

    Invariants afterwards (when total > 0): 0 <= offset <= cursor < offset + height
    and offset <= max(0, total - height), so the window never scrolls past the end.
    """
    height = max(1, height)
    cursor = 0 if total <= 0 else min(max(cursor, 0), total - 1)
    offset = min(max(offset, 0), max(0, total - height))
    if cursor < offset:
        offset = cursor
    elif cursor >= offset + height:
        offset = cursor - height + 1
    return cursor, offset


@dataclass(frozen=True)
class ListModel(Generic[T]):
    items: Tuple[T, ...] = ()
    cursor: int = 0
    offset: int = 0
    selected: FrozenSet[int] = frozenset()
    query: str = ""
    key_fn: Callable[[T], str] = str

    def __post_init__(self) -> None:
        # Normalise loosely typed constructor arguments. A frozen dataclass can
        # only do this through object.__setattr__, and only while being built.
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "selected", frozenset(self.selected))

    # ------------------------------------------------------------- queries

    @property
    def count(self) -> int:
        """Number of items, filtered or not."""
        return len(self.items)

    @property
    def filtered_count(self) -> int:
        return len(self.filtered())

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    def filtered(self) -> Rows:
        """(original index, item) for every item matching `query` (all when empty)."""
        query = self.query.lower()
        if not query:
            return tuple(enumerate(self.items))
        return tuple(
            (index, item) for index, item in enumerate(self.items)
            if query in self.key_fn(item).lower()
        )

    def visible(self, height: int) -> Rows:
        """The slice of filtered rows that fits in `height` lines from `offset`."""
        rows = self.filtered()
        return rows[self.offset:self.offset + max(0, height)]

    def current_index(self) -> Optional[int]:
        """Original index of the row under the cursor, None when there is none."""
        rows = self.filtered()
        if 0 <= self.cursor < len(rows):
            return rows[self.cursor][0]
        return None

    def current(self) -> Optional[T]:
        """The item under the cursor, None for an empty (or filtered-to-empty) model."""
        index = self.current_index()
        return None if index is None else self.items[index]

    def is_selected(self, index: int) -> bool:
        return index in self.selected

    def selected_items(self) -> Tuple[T, ...]:
        """Selected items in their original order."""
        return tuple(self.items[i] for i in sorted(self.selected) if 0 <= i < len(self.items))

    # ---------------------------------------------------------- navigation

    def _place(self, cursor: int, height: int, offset: Optional[int] = None) -> "ListModel[T]":
        offset = self.offset if offset is None else offset
        cursor, offset = _clamp_view(cursor, offset, len(self.filtered()), height)
        return replace(self, cursor=cursor, offset=offset)

    def move(self, delta: int, height: int) -> "ListModel[T]":
        """Move the cursor by `delta` rows, scrolling only when it leaves the window."""
        return self._place(self.cursor + delta, height)

    def page(self, delta: int, height: int) -> "ListModel[T]":
        """Move cursor and window by `delta` pages of `height` rows."""
        step = delta * max(1, height)
        return self._place(self.cursor + step, height, self.offset + step)

    def home(self, height: int) -> "ListModel[T]":
        return self._place(0, height)

    def end(self, height: int) -> "ListModel[T]":
        return self._place(len(self.filtered()) - 1, height)

    # ----------------------------------------------------------- selection

    def toggle(self) -> "ListModel[T]":
        """Flip the selection of the row under the cursor."""
        index = self.current_index()
        if index is None:
            return replace(self)
        return replace(self, selected=self.selected ^ frozenset((index,)))

    def select_all_visible(self) -> "ListModel[T]":
        """Add every row that matches the current filter."""
        return replace(self, selected=self.selected | frozenset(i for i, _ in self.filtered()))

    def select_none(self) -> "ListModel[T]":
        return replace(self, selected=frozenset())

    # -------------------------------------------------------- replacement

    def set_query(self, query: str) -> "ListModel[T]":
        """Change the filter; cursor and offset restart at 0, selection is kept."""
        return replace(self, query=query, cursor=0, offset=0)

    def with_items(self, items: Iterable[T]) -> "ListModel[T]":
        """Swap the items: keep query, clamp cursor, drop selections that vanished."""
        new_items = tuple(items)
        selected = frozenset(i for i in self.selected if 0 <= i < len(new_items))
        model = replace(self, items=new_items, selected=selected)
        total = len(model.filtered())
        cursor = 0 if total == 0 else min(max(self.cursor, 0), total - 1)
        offset = min(max(self.offset, 0), cursor)
        return replace(model, cursor=cursor, offset=offset)
