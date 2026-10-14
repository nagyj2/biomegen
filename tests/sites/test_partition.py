"""Tests for the binary space partition."""

from __future__ import annotations

import random

from biomegen.sites.partition import bsp_rooms


def _rooms(seed: int = 1, cols: int = 60, rows: int = 24):
    return bsp_rooms(random.Random(seed), cols, rows, (3, 6), 2.0)


def test_rooms_lie_inside_the_border() -> None:
    assert all(x >= 1 and y >= 1 and x + w <= 59 and y + h <= 23 for x, y, w, h in _rooms())


def test_rooms_do_not_overlap() -> None:
    rooms = _rooms()
    cells = [(x + i, y + j) for x, y, w, h in rooms for i in range(w) for j in range(h)]
    assert len(cells) == len(set(cells))


def test_room_height_respects_the_row_limits() -> None:
    assert all(3 <= h <= 6 for _x, _y, _w, h in _rooms())


def test_room_width_is_widened_by_the_aspect() -> None:
    # A room of three to six rows is six to twelve columns wide at an aspect of two.
    assert all(6 <= w <= 12 for _x, _y, w, _h in _rooms())


def test_the_same_seed_gives_the_same_rooms() -> None:
    assert _rooms(7) == _rooms(7)


def test_a_grid_too_small_for_two_rooms_gives_one() -> None:
    assert len(bsp_rooms(random.Random(1), 14, 8, (3, 6), 2.0)) == 1


def test_a_big_grid_is_split_into_several_rooms() -> None:
    assert len(_rooms(1, 120, 40)) >= 4
