"""Tests for installer.tui.listmodel.ListModel (pure, no curses)."""

from __future__ import annotations

import unittest

from installer.tui.listmodel import ListModel

FRUIT = ("apple", "banana", "cherry", "date", "elderberry", "fig", "grape", "honeydew")
HEIGHTS = (1, 2, 3, 5, 8, 20)


def model(items=FRUIT, **kwargs) -> ListModel:
    return ListModel(items=items, **kwargs)


def assert_view_invariants(case: unittest.TestCase, m: ListModel, height: int) -> None:
    total = m.filtered_count
    if total == 0:
        case.assertEqual((m.cursor, m.offset), (0, 0))
        case.assertIsNone(m.current())
        return
    case.assertGreaterEqual(m.offset, 0)
    case.assertLessEqual(m.offset, m.cursor)
    case.assertLess(m.cursor, m.offset + max(1, height))
    case.assertLess(m.cursor, total)
    case.assertLessEqual(m.offset, max(0, total - max(1, height)))
    case.assertIn(m.current(), [item for _, item in m.visible(height)])


class NavigationTests(unittest.TestCase):
    def test_invariants_hold_across_heights(self):
        for height in HEIGHTS:
            m = model(selected={1})
            for step in (lambda x: x.move(1, height), lambda x: x.move(4, height),
                         lambda x: x.page(1, height), lambda x: x.end(height),
                         lambda x: x.move(-2, height), lambda x: x.page(-1, height),
                         lambda x: x.home(height), lambda x: x.move(-1, height),
                         lambda x: x.page(3, height), lambda x: x.set_query("e"),
                         lambda x: x.end(height), lambda x: x.with_items(FRUIT[:2])):
                m = step(m)
                assert_view_invariants(self, m, height)


class SelectionTests(unittest.TestCase):
    def test_select_all_visible_none_and_selection_surviving_a_filter_in_original_order(self):
        m = model(selected={1}).set_query("e").select_all_visible()
        self.assertEqual((m.selected, m.selected_count), (frozenset({0, 1, 2, 3, 4, 6, 7}), 7))
        self.assertEqual(model().select_all_visible().selected, frozenset(range(len(FRUIT))))
        cleared = model(selected={0, 3}).select_none()
        self.assertEqual((cleared.selected, cleared.selected_items()), (frozenset(), ()))
        hidden = model().move(1, 5).toggle().set_query("zzz")
        self.assertEqual((hidden.selected, hidden.selected_items()), (frozenset({1}), ("banana",)))
        self.assertEqual(hidden.set_query("").selected_items(), ("banana",))
        self.assertEqual(model(selected={6, 0, 3}).selected_items(), ("apple", "date", "grape"))


if __name__ == "__main__":
    unittest.main()
