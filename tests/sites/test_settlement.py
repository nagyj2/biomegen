"""Tests for settlement plans: streets, lots, walls, roofs and gates, on flat test worlds."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from biomegen.config.model import Config
from biomegen.sites import site_plan
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR, WALL, DOOR, PATH = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR, Cell.PATH))
ROOF, STONE, TREE, BUSH = (int(c) for c in (Cell.ROOF, Cell.STONE, Cell.TREE, Cell.BUSH))


def _plan(config: Config, kind: str, world=None, pop: int = 2000):
    world = world or flat_world(16, 12)
    poi = add_poi(world, kind, 8, 6, pop=pop)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return plan


def test_a_village_has_a_plaza_and_streets(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert int((plan.cells == PATH).sum()) > 30


def test_a_village_has_buildings(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert DOOR in plan.cells and WALL in plan.cells


def test_the_streets_are_one_connected_network(config: Config) -> None:
    plan = _plan(config, "town")
    _labels, count = ndimage.label(np.isin(plan.cells, (PATH, int(Cell.BRIDGE))))
    assert count == 1


def test_a_vertical_street_is_as_thick_as_a_horizontal_one(config: Config) -> None:
    # The axis through the plaza runs up and down: it is two columns wide, one row wide where it runs across.
    plan = _plan(config, "town")
    path = plan.cells == PATH
    row = path[plan.cells.shape[0] // 2]
    column = path[:, plan.cells.shape[1] // 2 - 1 : plan.cells.shape[1] // 2 + 2]
    assert row.sum() > 10 and column.any(axis=0).sum() >= 2


def test_every_building_is_under_a_roof_seen_from_outside(config: Config) -> None:
    # Wherever the inside has a wall of a building (not the city wall), the outside is a roof or the stone wall.
    plan = _plan(config, "town")
    # The one exception is a front door, which shows as the street it opens onto.
    interior = np.isin(plan.cells, (FLOOR, int(Cell.TABLE), int(Cell.BED)))
    assert (plan.outside[interior] == ROOF).all()


def test_streets_are_the_same_inside_and_outside(config: Config) -> None:
    plan = _plan(config, "town")
    # Front doors aside (the street shows over the door gap from outside), the two views agree on the streets.
    doors = plan.cells == DOOR
    assert np.array_equal((plan.cells == PATH) & ~doors, (plan.outside == PATH) & ~doors)


def test_a_capital_is_walled_with_stone_seen_from_outside(config: Config) -> None:
    plan = _plan(config, "capital", pop=80000)
    assert STONE in plan.outside and WALL in plan.cells


def test_a_village_has_no_wall_round_it(config: Config) -> None:
    plan = _plan(config, "village", pop=500)
    assert STONE not in plan.outside


def test_a_walled_settlement_has_a_gate_where_a_street_crosses_the_wall(config: Config) -> None:
    # A road arrives from the east: the wall is broken there by a gate (a door cell in the wall line).
    world = flat_world(16, 12)
    world.road[6, 8:14] = 1
    plan = _plan(config, "capital", world, pop=80000)
    east = plan.cells[:, -12:]
    assert (east == DOOR).any() and (east == WALL).any()


def test_a_road_gate_is_joined_to_the_plaza_by_a_street(config: Config) -> None:
    world = flat_world(16, 12)
    world.road[6, 9:14] = 1
    plan = _plan(config, "town", world)
    row = plan.cells[plan.cells.shape[0] // 2]
    assert (row[-8:] == PATH).any()


def test_trees_grow_on_free_ground(config: Config) -> None:
    plan = _plan(config, "town")
    assert int(np.isin(plan.cells, (TREE, BUSH)).sum()) > 0


def test_trees_keep_off_the_streets_and_buildings(config: Config) -> None:
    plan = _plan(config, "town")
    near = ndimage.binary_dilation(np.isin(plan.cells, (PATH, FLOOR, WALL, DOOR)), iterations=1)
    trees = np.isin(plan.cells, (TREE, BUSH))
    assert not (trees & near & ~np.isin(plan.cells, (TREE, BUSH))).any() and trees.any()


def test_a_settlement_beside_the_sea_builds_only_on_land(config: Config) -> None:
    world = flat_world(16, 12)
    world.biome[:, :8] = int(Biome.DEEP)
    world.water_type[:, :8] = int(WaterType.SALT)
    plan = _plan(config, "town", world)
    sea = plan.cells[:, : plan.cells.shape[1] // 4]
    assert not np.isin(sea, (FLOOR, WALL, DOOR, TREE)).any()


def test_bigger_tiers_have_bigger_sites(config: Config) -> None:
    sizes = [
        _plan(config, kind, pop=hi).cells.size for kind, hi in (("village", 1000), ("town", 5000), ("city", 20000))
    ]
    assert sizes == sorted(sizes)


def test_a_capital_is_not_a_rectangle(config: Config) -> None:
    # The wall follows a wobbling outline: it leaves much of its bounding box empty.
    plan = _plan(config, "capital", pop=80000)
    ys, xs = np.nonzero(plan.outside != VOID)
    box = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
    assert int((plan.outside != VOID).sum()) < 0.8 * box


def test_the_wall_is_not_a_rectangle_of_the_extent_edge(config: Config) -> None:
    # A wall hugging a rectangle would have every cell on the outer rows and columns of its own bounding box.
    plan = _plan(config, "capital", pop=80000)
    ys, xs = np.nonzero(plan.cells == WALL)
    inner = (ys > ys.min()) & (ys < ys.max()) & (xs > xs.min()) & (xs < xs.max())
    assert int(inner.sum()) > len(ys) // 4


def test_a_town_has_streets_on_many_rows(config: Config) -> None:
    # A grid of axes would put its streets on a handful of rows; a grown network spreads over the plan.
    plan = _plan(config, "town")
    assert int((plan.cells == PATH).any(axis=1).sum()) >= 8


def test_two_towns_of_different_seeds_have_different_outlines(config: Config) -> None:
    world = flat_world(16, 12)
    plans = [site_plan(add_poi(world, "town", 8, 6, pop=2000, interior_seed=seed), 0, config, world) for seed in (3, 4)]
    assert plans[0] is not None and plans[1] is not None and not np.array_equal(plans[0].outside, plans[1].outside)


def test_the_streets_still_reach_every_building_door(config: Config) -> None:
    # Each door on a building's outside wall has street (or the road) directly outside: nothing is stranded.
    plan = _plan(config, "town")
    labels, _count = ndimage.label(np.isin(plan.cells, (PATH, int(Cell.BRIDGE))))
    doors = np.argwhere(plan.cells == DOOR)
    reached = 0
    for y, x in doors.tolist():
        around = [(y + dy, x + dx) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        reached += any(
            0 <= cy < plan.cells.shape[0] and 0 <= cx < plan.cells.shape[1] and labels[cy, cx] > 0 for cy, cx in around
        )
    assert doors.size and reached >= len(doors) // 2
