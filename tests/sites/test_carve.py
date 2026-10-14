"""Tests for the carving primitives: rooms, corridors, walls and connectivity."""

from __future__ import annotations

import numpy as np

from biomegen.sites.carve import (
    add_walls,
    border_void,
    carve_corridor,
    carve_room,
    connect_floor_components,
    fill_enclosed,
    largest_component,
    nearest_true,
    rect_in_mask,
    wall_ring,
)
from biomegen.world.tile import Cell

VOID, FLOOR, WALL = int(Cell.VOID), int(Cell.FLOOR), int(Cell.WALL)


def _grid(rows: int = 9, cols: int = 15) -> np.ndarray:
    return np.full((rows, cols), VOID, dtype=np.uint8)


def test_carve_room_fills_the_rectangle() -> None:
    grid = _grid()
    carve_room(grid, (2, 1, 4, 3))
    assert int((grid == FLOOR).sum()) == 12 and grid[1, 2] == FLOOR and grid[3, 5] == FLOOR


def test_corridor_runs_across_then_up_and_down() -> None:
    grid = _grid()
    carve_corridor(grid, (1, 2), (10, 6), vertical_width=1)
    assert (grid[2, 1:11] == FLOOR).all() and (grid[2:7, 10] == FLOOR).all()


def test_vertical_corridor_is_wider_than_it_is_tall() -> None:
    # Cells are taller than wide, so the up-and-down run is two columns thick to look like the across run.
    grid = _grid()
    carve_corridor(grid, (1, 2), (10, 6), vertical_width=2)
    assert int((grid[4] == FLOOR).sum()) == 2


def test_add_walls_rings_a_floor_including_corners() -> None:
    grid = _grid(5, 7)
    grid[2, 3] = FLOOR
    add_walls(grid)
    assert int((grid == WALL).sum()) == 8


def test_wall_ring_walls_only_void_cells() -> None:
    grid = _grid()
    carve_room(grid, (4, 3, 3, 2))
    grid[2, 5] = int(Cell.PATH)  # a street already on the ring stays
    wall_ring(grid, (4, 3, 3, 2))
    assert grid[2, 5] == int(Cell.PATH) and grid[2, 4] == WALL and grid[3, 3] == WALL


def test_wall_ring_is_clipped_at_the_grid_edge() -> None:
    grid = _grid()
    wall_ring(grid, (0, 0, 3, 2))
    assert grid[2, 0] == WALL and grid[0, 3] == WALL and (grid[0:2, 0:3] == VOID).all()


def test_largest_component_drops_the_small_one() -> None:
    mask = np.zeros((5, 9), dtype=bool)
    mask[1:4, 1:5] = True
    mask[2, 7] = True
    assert largest_component(mask).sum() == 12


def test_fill_enclosed_walls_a_pocket_but_not_the_outside() -> None:
    grid = _grid(7, 7)
    grid[1:6, 1:6] = WALL
    grid[3, 3] = VOID
    fill_enclosed(grid)
    assert grid[3, 3] == WALL and grid[0, 0] == VOID


def test_border_void_excludes_a_sealed_pocket() -> None:
    grid = _grid(7, 7)
    grid[1:6, 1:6] = WALL
    grid[3, 3] = VOID
    assert not border_void(grid)[3, 3] and border_void(grid)[0, 0]


def test_connect_floor_components_joins_two_rooms() -> None:
    grid = _grid()
    carve_room(grid, (1, 1, 3, 3))
    carve_room(grid, (10, 5, 3, 3))
    connect_floor_components(grid)
    from scipy import ndimage

    assert ndimage.label(grid == FLOOR)[1] == 1


def test_rect_in_mask_needs_every_cell() -> None:
    mask = np.ones((6, 10), dtype=bool)
    mask[2, 3] = False
    assert rect_in_mask((5, 1, 3, 3), mask) and not rect_in_mask((2, 1, 3, 3), mask)


def test_nearest_true_finds_the_closest_cell_on_screen() -> None:
    # A cell two rows up is as far on screen as one four columns across at an aspect of two.
    mask = np.zeros((9, 15), dtype=bool)
    mask[2, 7] = True
    mask[4, 11] = True
    assert nearest_true(mask, (7, 4), aspect=2.0) == (7, 2)


def test_nearest_true_of_an_empty_mask_is_none() -> None:
    assert nearest_true(np.zeros((3, 3), dtype=bool), (1, 1)) is None
