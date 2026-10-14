"""Tests for stairs and entrances."""

from __future__ import annotations

import random

import numpy as np

from biomegen.sites.carve import add_walls, carve_room
from biomegen.sites.circulation import floor_links, punch_entrance, stair_links, stamp_stairs
from biomegen.world.tile import Cell

VOID, FLOOR, WALL, DOOR = int(Cell.VOID), int(Cell.FLOOR), int(Cell.WALL), int(Cell.DOOR)


def _mask() -> np.ndarray:
    mask = np.zeros((18, 54), dtype=bool)
    mask[2:16, 2:52] = True
    return mask


def test_a_stack_of_n_floors_has_n_minus_one_links() -> None:
    assert len(stair_links(5, _mask(), 4)) == 3


def test_a_single_floor_has_no_stairs() -> None:
    assert stair_links(5, _mask(), 1) == []


def test_links_lie_inside_the_structure() -> None:
    mask = _mask()
    assert all(mask[y, x] for x, y in stair_links(5, mask, 5))


def test_links_are_distinct_cells() -> None:
    links = stair_links(5, _mask(), 5)
    assert len(set(links)) == len(links)


def test_links_depend_only_on_the_seed_and_mask() -> None:
    assert stair_links(9, _mask(), 4) == stair_links(9, _mask(), 4)


def test_up_stairs_land_on_the_next_floors_down_stairs() -> None:
    links = stair_links(5, _mask(), 3)
    lower_up, _ = floor_links(links, -2, -2, 3)
    _, upper_down = floor_links(links, -1, -2, 3)
    assert lower_up == upper_down


def test_the_top_floor_has_no_up_stairs_and_the_lowest_no_down_stairs() -> None:
    links = stair_links(5, _mask(), 3)
    assert floor_links(links, 0, -2, 3)[0] is None and floor_links(links, -2, -2, 3)[1] is None


def test_stamp_stairs_writes_both_cells() -> None:
    grid = np.full((6, 6), FLOOR, dtype=np.uint8)
    stamp_stairs(grid, (1, 1), (4, 4))
    assert grid[1, 1] == int(Cell.STAIRS_UP) and grid[4, 4] == int(Cell.STAIRS_DOWN)


def _building() -> tuple[np.ndarray, list]:
    grid = np.full((14, 40), VOID, dtype=np.uint8)
    room = (10, 4, 20, 6)
    carve_room(grid, room)
    add_walls(grid)
    return grid, [room]


def test_the_entrance_is_a_door_on_the_outer_wall() -> None:
    grid, rooms = _building()
    door = punch_entrance(grid, rooms, random.Random(1), None)
    assert door is not None and grid[door[1], door[0]] == DOOR


def test_the_door_goes_on_the_wall_nearest_the_gate() -> None:
    grid, rooms = _building()
    door = punch_entrance(grid, rooms, random.Random(1), (0, 6))
    assert door is not None and door[0] == 9


def test_a_door_facing_the_east_gate_is_on_the_east_wall() -> None:
    grid, rooms = _building()
    door = punch_entrance(grid, rooms, random.Random(1), (39, 6))
    assert door is not None and door[0] == 30


def test_no_rooms_means_no_entrance() -> None:
    grid, _ = _building()
    assert punch_entrance(grid, [], random.Random(1), None) is None
