"""Tests for the specialized buildings of a settlement: farmhouse, lodge and mine stand on the outer ground, dressed."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.sites.dress import variant_cell
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Biome, Cell, Relief
from tests.sites.conftest import add_poi, flat_world

FIELD_CELLS = [int(Cell.WHEAT), variant_cell(load_config(None), "field", "harvested")]
DEAD = variant_cell(load_config(None), "field", "dead")


def _plan(config: Config, tier: str, pop: int, biome: Biome = Biome.GRASS, relief: Relief = Relief.NONE, **fields):
    world = flat_world(20, 14, biome)
    world.relief[:] = int(relief)
    poi = add_poi(world, tier, 10, 7, pop=pop, civilized=True, **fields)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return plan


def test_a_farming_village_has_a_farmhouse_with_a_field(config: Config) -> None:
    plan = _plan(config, "village", 800)
    assert roof_cell(config, "farmhouse") in plan.outside and np.isin(plan.outside, FIELD_CELLS).any()


def test_a_forest_city_has_a_lodge_with_a_clearing(config: Config) -> None:
    plan = _plan(config, "city", 20000, Biome.FOREST)
    assert roof_cell(config, "lodge") in plan.outside and int(Cell.LOG) in plan.outside


def test_a_hill_city_has_a_mine_with_spoil(config: Config) -> None:
    plan = _plan(config, "city", 20000, Biome.GRASS, Relief.HILLS)
    assert roof_cell(config, "mine") in plan.outside and int(Cell.ROCK) in plan.outside


def test_a_farm_hamlet_has_its_farmhouse_and_its_gathering_point(config: Config) -> None:
    plan = _plan(config, "hamlet", 40, style="farm")
    assert {roof_cell(config, "farmhouse"), roof_cell(config, "gathering_point")} <= set(
        np.unique(plan.outside).tolist()
    )


def test_a_specialized_building_has_a_door_on_a_street(config: Config) -> None:
    plan = _plan(config, "village", 800)
    footprint = plan.outside == roof_cell(config, "farmhouse")
    doors = (plan.cells == int(Cell.DOOR)) & ndimage.binary_dilation(footprint, iterations=1)
    near = ndimage.binary_dilation(doors, iterations=1) & ~footprint
    assert doors.any() and (plan.cells[near] == int(Cell.PATH)).any()


def test_a_standing_field_is_full_or_harvested_never_dead(config: Config) -> None:
    plan = _plan(config, "village", 800)
    assert DEAD not in plan.outside and int(Cell.WHEAT) in plan.outside


def test_the_field_of_a_ruin_is_harvested_or_dead_never_full(config: Config) -> None:
    world = flat_world(20, 14, Biome.GRASS)
    ruin = add_poi(world, "ruin", 10, 7, pop=800, ruin_of="village", floor_count=1, interior_seed=3)
    plan = site_plan(ruin, 0, config, world)
    assert (
        plan is not None
        and int(Cell.WHEAT) not in plan.outside
        and np.isin(plan.outside, FIELD_CELLS[1:] + [DEAD]).any()
    )


def test_a_kind_with_no_room_is_left_out_and_the_plan_still_builds(config: Config) -> None:
    cramped = load_config(None)
    cramped.data["sites"]["size_jitter"] = 0.0
    cramped.data["tables"]["buildings"]["farmhouse"]["rows"] = [40, 40]
    plan = _plan(cramped, "village", 800)
    assert roof_cell(cramped, "farmhouse") not in plan.outside and roof_cell(cramped, "chapel") in plan.outside


def test_the_specialized_buildings_are_deterministic(config: Config) -> None:
    first = _plan(config, "city", 20000, Biome.FOREST)
    clear_cache()
    second = _plan(config, "city", 20000, Biome.FOREST)
    assert np.array_equal(first.cells, second.cells) and np.array_equal(first.outside, second.outside)


def test_a_building_that_needs_a_river_is_not_placed_as_an_edge_kind(config: Config) -> None:
    # Mills and fisheries have their own siting (river and shore): an edge pass never builds them.
    plan = _plan(config, "city", 20000)
    assert roof_cell(config, "mill") not in plan.outside and roof_cell(config, "fishery") not in plan.outside


# --- river and shore kinds ------------------------------------------------------------------------------------------


def _fresh(config: Config) -> Config:
    """A copy of the test config for editing one building row."""
    other = load_config(None)
    other.data["sites"]["size_jitter"] = 0.0
    return other


def test_a_river_town_has_a_mill_with_its_wheel(config: Config) -> None:
    from tests.sites.test_settlement import _riverside

    _, plan = _riverside(config, ("river",))
    assert roof_cell(config, "mill") in plan.outside and int(Cell.WHEEL) in plan.cells


def test_a_mill_that_is_not_chosen_builds_no_wheel(config: Config) -> None:
    from tests.sites.test_settlement import _riverside

    other = _fresh(config)
    other.data["tables"]["buildings"]["mill"]["min_score"] = 2.0  # no land suits it that well
    _, plan = _riverside(other, ("river",))
    assert roof_cell(other, "mill") not in plan.outside and int(Cell.WHEEL) not in plan.cells


def test_a_port_town_has_a_fishery_beside_its_pier(config: Config) -> None:
    from tests.sites.test_settlement import _coast

    _, plan = _coast(config, ("port",))
    pier = plan.cells == int(Cell.BRIDGE)
    fishery = plan.outside == roof_cell(config, "fishery")
    distance = ndimage.distance_transform_edt(~pier, sampling=(1.0, 0.5))
    assert pier.any() and fishery.any() and float(distance[fishery].min()) <= 18.0


def test_a_port_whose_fishery_is_not_chosen_still_has_its_harbour(config: Config) -> None:
    from tests.sites.test_settlement import _coast

    other = _fresh(config)
    other.data["tables"]["buildings"]["fishery"]["min_score"] = 2.0
    _, plan = _coast(other, ("port",))
    assert int(Cell.BRIDGE) in plan.cells and roof_cell(other, "fishery") not in plan.outside


def test_a_mill_hamlet_always_has_its_mill(config: Config) -> None:
    # No river bank in the extent: the mill hamlet still has its style's building, a plain mill.
    plan = _plan(config, "hamlet", 40, style="mill")
    assert roof_cell(config, "mill") in plan.outside


def test_a_fishery_and_a_mill_are_drawn_from_their_own_rows(config: Config) -> None:
    from tests.sites.test_settlement import _coast, _riverside

    _, coast = _coast(config, ("port",))
    _, river = _riverside(config, ("river",))
    assert {roof_cell(config, "fishery"), roof_cell(config, "mill")} <= set(
        np.unique(np.concatenate([coast.outside.ravel(), river.outside.ravel()])).tolist()
    )


# --- walls and dressings ---------------------------------------------------------------------------------------------


def test_a_walled_cities_dressings_stay_inside_its_wall(config: Config) -> None:
    # A field, clearing or spoil never spills over or past the wall: none is reachable from the plan's edge without
    # crossing a wall or a gate.
    plan = _plan(config, "capital", 90000)
    dress = np.isin(plan.cells, FIELD_CELLS + [int(Cell.LOG), int(Cell.ROCK)])
    walls = np.isin(plan.cells, [int(Cell.WALL), int(Cell.DOOR)])
    labels, _count = ndimage.label(~walls)
    outside = labels == labels[0, 0]
    assert dress.any() and walls.any() and not (dress & outside).any()
