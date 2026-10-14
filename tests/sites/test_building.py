"""Tests for buildings: thin shared walls, a connected door graph, a street door and furnished rooms."""

from __future__ import annotations

import random
from collections import deque

import numpy as np
import pytest

from biomegen.sites.building import Building, Spec, build_building
from biomegen.sites.cells import PASSABLE
from biomegen.world.tile import Cell

VOID, FLOOR, WALL, DOOR = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR))
FURNITURE = {
    "hall": [(Cell.TABLE, 3.0), (Cell.CHAIR, 2.0)],
    "bedroom": [(Cell.BED, 4.0), (Cell.CHEST, 1.0)],
    "storage": [(Cell.BARREL, 2.0), (Cell.CRATE, 2.0)],
}


def _spec(**overrides: object) -> Spec:
    fields: dict = {
        "min_room_rows": 3,
        "aspect": 2.0,
        "roles": ("hall", "bedroom", "storage"),
        "furniture": FURNITURE,
        "density": 0.15,
    }
    fields.update(overrides)
    return Spec(**fields)


def _build(rows: int = 15, cols: int = 36, seed: int = 1, toward=(-5, 7), **overrides: object) -> Building:
    building = build_building(rows, cols, random.Random(seed), _spec(**overrides), toward)
    assert building is not None
    return building


def _reachable(building: Building, start: tuple[int, int]) -> set[tuple[int, int]]:
    rows, cols = building.cells.shape
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in seen and int(building.cells[ny, nx]) in PASSABLE:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def test_a_building_is_deterministic() -> None:
    assert np.array_equal(_build().cells, _build().cells)


def test_different_seeds_give_different_buildings() -> None:
    assert not np.array_equal(_build(seed=1).cells, _build(seed=2).cells)


def test_a_building_fits_its_space() -> None:
    assert _build(11, 24).cells.shape == (11, 24)


def test_a_space_too_small_for_a_room_gives_none() -> None:
    assert build_building(4, 8, random.Random(1), _spec(), None) is None


def test_every_floor_cell_is_inside_walls() -> None:
    # No floor cell touches void or the grid edge: the footprint is closed.
    building = _build()
    cells = building.cells
    padded = np.pad(cells, 1, constant_values=VOID)
    floor = np.argwhere(cells != VOID).tolist()
    for y, x in floor:
        if cells[y, x] == FLOOR:
            around = padded[y : y + 3, x : x + 3]
            assert (around != VOID).all()


def test_the_footprint_is_exactly_the_non_void_cells() -> None:
    building = _build()
    assert np.array_equal(building.footprint, building.cells != VOID)


def test_walls_are_one_cell_thick() -> None:
    # Rooms share their walls, so no two-by-two block of wall or door cells exists anywhere.
    cells = _build(19, 40).cells
    wall = np.isin(cells, (WALL, DOOR))
    block = wall[:-1, :-1] & wall[1:, :-1] & wall[:-1, 1:] & wall[1:, 1:]
    assert not block.any()


def test_every_room_is_reachable_from_the_street_door() -> None:
    # Walking through doors and over furniture reaches every cell inside the building.
    building = _build(19, 40)
    rows, cols = building.cells.shape
    open_cells = {(x, y) for y in range(rows) for x in range(cols) if int(building.cells[y, x]) not in (VOID, WALL)}
    seen = {building.doors[0]}
    queue = deque([building.doors[0]])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in open_cells and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    assert open_cells <= seen


def test_furniture_never_blocks_the_way_between_doors() -> None:
    # Furnishing keeps a walkable path (floor, rubble, door, stairs) between the street door and every other door.
    building = _build(19, 40)
    reached = _reachable(building, building.doors[0])
    assert set(building.doors) <= reached


def test_a_large_building_has_several_rooms_and_doors_between_them() -> None:
    building = _build(19, 40)
    assert len(building.roles) >= 3 and len(building.doors) >= len(building.roles)


def test_the_street_door_faces_the_street() -> None:
    # A plain rectangle with the street to the west has its street door on the west wall.
    building = _build(shapes=("rect",), toward=(-5, 7))
    assert building.doors[0][0] == 0 and building.front == (-1, building.doors[0][1])


def test_the_street_door_faces_a_street_to_the_south() -> None:
    building = _build(shapes=("rect",), toward=(18, 40))
    assert building.doors[0][1] == building.cells.shape[0] - 1


def test_no_street_means_no_street_door() -> None:
    building = _build(toward=None)
    assert building.front is None and DOOR in building.cells


def test_an_l_shaped_building_does_not_fill_its_bounding_box() -> None:
    building = _build(19, 40, shapes=("L",))
    assert not building.footprint.all() and building.footprint.any()


def test_the_largest_room_takes_the_first_role() -> None:
    building = _build(shapes=("rect",))
    assert building.roles[0][0] == "hall"


def test_a_single_role_serves_every_room() -> None:
    building = _build(19, 40, roles=("hall",), furniture={"hall": FURNITURE["hall"]})
    assert {role for role, _ in building.roles} == {"hall"}


def test_rooms_are_furnished_by_role() -> None:
    cells = _build(19, 40).cells
    kinds = {int(c) for c in np.unique(cells)}
    assert kinds & {int(Cell.TABLE), int(Cell.BED), int(Cell.BARREL)}


def test_furniture_stays_off_the_cells_in_front_of_doors() -> None:
    building = _build(19, 40)
    for x, y in building.doors:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= ny < building.cells.shape[0] and 0 <= nx < building.cells.shape[1]:
                assert int(building.cells[ny, nx]) in (VOID, FLOOR, WALL, DOOR)


@pytest.mark.parametrize("seed", range(8))
def test_a_door_never_joins_a_room_to_the_void(seed: int) -> None:
    # Every door has floor on two opposite sides, or floor on one side and open ground on the other (the street door).
    building = _build(19, 40, seed=seed)
    cells = building.cells
    rows, cols = cells.shape
    for x, y in building.doors[1:]:
        pair = [(x - 1, y, x + 1, y), (x, y - 1, x, y + 1)]
        assert any(int(cells[y1, x1]) != VOID and int(cells[y2, x2]) != VOID for x1, y1, x2, y2 in pair)


def test_no_furniture_without_density() -> None:
    cells = _build(density=0.0).cells
    assert set(np.unique(cells).tolist()) <= {VOID, FLOOR, WALL, DOOR}
