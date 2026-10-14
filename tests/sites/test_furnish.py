"""Tests for furnishing helpers."""

from __future__ import annotations

import random

import numpy as np

from biomegen.sites.carve import carve_room
from biomegen.sites.furnish import adjacent, free_floor, keep_reachable, scatter, weighted_choice
from biomegen.world.tile import Cell

FLOOR, WALL, VOID = int(Cell.FLOOR), int(Cell.WALL), int(Cell.VOID)


def _room() -> np.ndarray:
    grid = np.full((7, 12), VOID, dtype=np.uint8)
    carve_room(grid, (1, 1, 10, 5))
    return grid


def test_free_floor_skips_reserved_cells() -> None:
    assert (1, 1) not in free_floor(_room(), [(1, 1)])


def test_free_floor_is_in_row_major_order() -> None:
    free = free_floor(_room())
    assert free == sorted(free, key=lambda p: (p[1], p[0]))


def test_scatter_dresses_the_density_fraction() -> None:
    grid = _room()
    scatter(grid, random.Random(1), free_floor(grid), 0.2, lambda r, x, y: Cell.BARREL)
    assert int((grid == int(Cell.BARREL)).sum()) == 10


def test_scatter_leaves_cells_the_chooser_declines() -> None:
    grid = _room()
    scatter(grid, random.Random(1), free_floor(grid), 1.0, lambda r, x, y: None)
    assert int((grid == FLOOR).sum()) == 50


def test_weighted_choice_only_returns_listed_cells() -> None:
    table = [(Cell.BED, 1.0), (Cell.TABLE, 3.0)]
    assert {weighted_choice(random.Random(i), table) for i in range(50)} <= {Cell.BED, Cell.TABLE}


def test_adjacent_marks_the_four_neighbours() -> None:
    mask = np.zeros((3, 3), dtype=bool)
    mask[1, 1] = True
    assert int(adjacent(mask).sum()) == 4


def test_keep_reachable_clears_furniture_blocking_the_route() -> None:
    grid = np.full((3, 7), VOID, dtype=np.uint8)
    grid[1, 0:7] = FLOOR
    grid[1, 3] = int(Cell.BARREL)
    keep_reachable(grid, [(0, 1), (6, 1)])
    assert grid[1, 3] == FLOOR
