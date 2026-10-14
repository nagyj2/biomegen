"""Tests for site plans: caching, determinism, floors, terrain-awareness and entrances, on tiny worlds."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from biomegen.config.model import Config
from biomegen.sites import clear_cache, read_patch, site_geometry, site_plan
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR, WALL, DOOR, PATH = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR, Cell.PATH))


def _plan(config: Config, kind: str, world=None, floor: int = 0, **fields):
    world = world or flat_world()
    poi = add_poi(world, kind, 7, 5, **fields)
    return poi, world, site_plan(poi, floor, config, world)


def test_a_kind_without_a_site_has_no_plan(config: Config) -> None:
    _poi, _world, plan = _plan(config, "bridge")
    assert plan is None


@pytest.mark.parametrize("kind", ["village", "tower", "dungeon", "ruin", "camp"])
def test_plan_covers_the_extent_box(config: Config, kind: str) -> None:
    poi, world, plan = _plan(config, kind, floor_count=1, pop=500)
    geometry = site_geometry(poi, config)
    assert plan is not None and geometry is not None
    assert plan.cells.shape == (geometry.box_rows, geometry.box_cols)


def test_plan_cells_are_read_only(config: Config) -> None:
    _poi, _world, plan = _plan(config, "village", pop=500)
    assert plan is not None and not plan.cells.flags.writeable


def test_the_same_inputs_give_the_same_plan(config: Config) -> None:
    poi, world, first = _plan(config, "village", pop=500)
    clear_cache()
    second = site_plan(poi, 0, config, world)
    assert first is not None and second is not None and np.array_equal(first.cells, second.cells)


def test_a_plan_is_cached(config: Config) -> None:
    poi, world, first = _plan(config, "village", pop=500)
    assert site_plan(poi, 0, config, world) is first


def test_different_seeds_give_different_plans(config: Config) -> None:
    world = flat_world()
    a = add_poi(world, "dungeon", 3, 4, interior_seed=1, floor_count=1)
    b = add_poi(world, "dungeon", 3, 4, interior_seed=2, floor_count=1)
    plan_a, plan_b = site_plan(a, 0, config, world), site_plan(b, 0, config, world)
    assert plan_a is not None and plan_b is not None and not np.array_equal(plan_a.cells, plan_b.cells)


def test_window_cells_embed_the_box_and_leave_the_margin_void(config: Config) -> None:
    _poi, _world, plan = _plan(config, "village", pop=500)
    assert plan is not None
    window = plan.window_cells()
    col0, row0, col1, row1 = plan.geometry.box
    assert np.array_equal(window[row0:row1, col0:col1], plan.cells) and (window[:row0] == VOID).all()


def test_a_floor_outside_the_site_is_clamped(config: Config) -> None:
    poi, world, ground = _plan(config, "tower", floor_count=3)
    above = site_plan(poi, 9, config, world)
    top = site_plan(poi, 2, config, world)
    assert above is top and ground is not None


def test_a_boat_stays_on_the_water(config: Config) -> None:
    world = flat_world(14, 10, Biome.SHALLOW)
    world.water_type[:] = int(WaterType.SALT)
    poi, _world, plan = _plan(config, "boat", world=world)
    assert plan is not None and (plan.cells != VOID).any()


def test_a_boat_on_dry_land_has_no_plan(config: Config) -> None:
    _poi, _world, plan = _plan(config, "boat")
    assert plan is None


def test_a_camp_has_a_campfire(config: Config) -> None:
    _poi, _world, plan = _plan(config, "camp")
    assert plan is not None and int(Cell.CAMPFIRE) in plan.cells


def test_a_camp_pitches_tents(config: Config) -> None:
    _poi, _world, plan = _plan(config, "camp")
    assert plan is not None and int(Cell.TENT) in plan.cells


def test_a_village_has_buildings_with_doors(config: Config) -> None:
    _poi, _world, plan = _plan(config, "village", pop=500)
    assert plan is not None and DOOR in plan.cells and WALL in plan.cells


def test_a_village_has_a_plaza_of_path(config: Config) -> None:
    _poi, _world, plan = _plan(config, "village", pop=500)
    assert plan is not None and PATH in plan.cells


def test_a_ruin_has_breaches_where_walls_fell(config: Config) -> None:
    # Erosion turns walls to void inside the outline: the same ruin without erosion has fewer gaps.
    poi, world, eroded = _plan(config, "ruin", floor_count=1)
    intact_config = copy.deepcopy(config)
    intact_config.data["sites"]["ruin_erosion"] = 0.0
    intact = site_plan(poi, 0, intact_config, world)
    assert eroded is not None and intact is not None
    assert int((eroded.cells == VOID).sum()) > int((intact.cells == VOID).sum())


def test_a_dungeon_floor_zero_has_an_entrance_door(config: Config) -> None:
    _poi, _world, plan = _plan(config, "dungeon", floor_count=3, lowest_floor=-2)
    assert plan is not None and DOOR in plan.cells


def test_a_deeper_dungeon_floor_has_no_entrance(config: Config) -> None:
    poi, world, _ = _plan(config, "dungeon", floor_count=3, lowest_floor=-2)
    deep = site_plan(poi, -2, config, world)
    assert deep is not None and DOOR not in deep.cells


def test_the_deepest_dungeon_floor_has_only_up_stairs(config: Config) -> None:
    poi, world, _ = _plan(config, "dungeon", floor_count=3, lowest_floor=-2)
    deep = site_plan(poi, -2, config, world)
    assert deep is not None and int(Cell.STAIRS_UP) in deep.cells and int(Cell.STAIRS_DOWN) not in deep.cells


def _stairs(cells: np.ndarray, cell: Cell) -> set[tuple[int, int]]:
    ys, xs = np.nonzero(cells == int(cell))
    return {(int(x), int(y)) for x, y in zip(xs, ys, strict=True)}


def test_tower_stairs_line_up_from_floor_to_floor(config: Config) -> None:
    # The up stairs of one floor are the down stairs of the next, so the shafts stack.
    poi, world, _ = _plan(config, "tower", floor_count=3)
    plans = [site_plan(poi, floor, config, world) for floor in range(3)]
    assert all(p is not None for p in plans)
    for lower, upper in zip(plans, plans[1:], strict=False):
        assert lower is not None and upper is not None
        assert _stairs(lower.cells, Cell.STAIRS_UP) == _stairs(upper.cells, Cell.STAIRS_DOWN)


def test_a_tower_rises_from_the_ground(config: Config) -> None:
    poi, world, ground = _plan(config, "tower", floor_count=3)
    assert ground is not None and int(Cell.STAIRS_UP) in ground.cells and int(Cell.STAIRS_DOWN) not in ground.cells
    top = site_plan(poi, 2, config, world)
    assert top is not None and int(Cell.STAIRS_DOWN) in top.cells and int(Cell.STAIRS_UP) not in top.cells


def test_a_structure_stays_off_the_water(config: Config) -> None:
    # A lake along the east edge of the extent: no wall or floor of a dungeon stands on it.
    world = flat_world()
    world.biome[:, 8:] = int(Biome.LAKE)
    world.water_type[:, 8:] = int(WaterType.FRESH)
    poi, _world, plan = _plan(config, "dungeon", world=world, floor_count=1)
    patch = read_patch(poi, site_geometry(poi, config), world, config)  # type: ignore[arg-type]
    assert plan is not None and not ((plan.cells != VOID) & ~patch.dry).any()


def test_the_entrance_door_faces_the_road(config: Config) -> None:
    # A road arriving from the west puts the dungeon's door on its western half.
    world = flat_world()
    world.road[5, 3:6] = 1
    _poi, _world, plan = _plan(config, "dungeon", world=world, floor_count=1)
    assert plan is not None
    xs = np.nonzero(plan.cells == DOOR)[1]
    assert len(xs) == 1 and int(xs[0]) < plan.cells.shape[1] // 2


def test_the_entrance_door_faces_a_road_from_the_east(config: Config) -> None:
    world = flat_world()
    world.road[5, 9:12] = 1
    _poi, _world, plan = _plan(config, "dungeon", world=world, floor_count=1)
    assert plan is not None
    xs = np.nonzero(plan.cells == DOOR)[1]
    assert len(xs) == 1 and int(xs[0]) > plan.cells.shape[1] // 2


def test_a_road_gate_is_joined_to_the_door_by_a_street(config: Config) -> None:
    world = flat_world()
    world.road[5, 3:6] = 1
    _poi, _world, plan = _plan(config, "dungeon", world=world, floor_count=1)
    assert plan is not None and PATH in plan.cells


def test_a_village_between_two_rivers_is_bridged_to_the_roads(config: Config) -> None:
    # Rivers run either side of the village and roads arrive beyond them, so each gate must bridge the water.
    wide = copy.deepcopy(config)
    wide.data["sites"]["bridge_max_rows"] = 12
    world = flat_world()
    world.water_type[:, 6] = int(WaterType.FRESH)
    world.water_type[:, 8] = int(WaterType.FRESH)
    world.road[5, 4:6] = 1
    world.road[5, 9:11] = 1
    _poi, _world, plan = _plan(wide, "village", world=world, pop=500)
    assert plan is not None and int(Cell.BRIDGE) in plan.cells


def test_a_village_on_an_island_in_the_sea_still_has_a_plan(config: Config) -> None:
    world = flat_world()
    world.water_type[:, 0:4] = int(WaterType.SALT)
    world.biome[:, 0:4] = int(Biome.SHALLOW)
    _poi, _world, plan = _plan(config, "village", world=world, pop=500)
    assert plan is not None
