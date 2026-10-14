"""Tests for the camp layout: clearing, tents, wagon, supplies and the track to a road gate."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import read_patch, site_geometry, site_plan
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR, PATH, TENT, WAGON, FIRE = (
    int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.PATH, Cell.TENT, Cell.WAGON, Cell.CAMPFIRE)
)


def _camp(config: Config, world=None):
    world = world or flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return poi, world, plan


def test_a_camp_has_one_campfire(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int((plan.cells == FIRE).sum()) == 1


def test_the_campfire_is_near_the_middle_of_the_clearing(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    ys, xs = np.nonzero(plan.cells != VOID)
    fy, fx = (int(v[0]) for v in np.nonzero(plan.cells == FIRE))
    assert abs(fx - (xs.min() + xs.max()) / 2) <= 3 and abs(fy - (ys.min() + ys.max()) / 2) <= 3


def test_a_camp_has_at_least_the_minimum_tents(config: Config) -> None:
    # Tents are separate blobs of TENT cells; overlapping pitches may merge, so count cells instead of blobs.
    _poi, _world, plan = _camp(config)
    assert int((plan.cells == TENT).sum()) >= int(config.get("sites.camp.min_tents")) * 4


def test_the_clearing_is_bare_ground_outside_the_plan_edge(config: Config) -> None:
    # The clearing is an ellipse: the corners of the plan stay void so terrain shows through.
    _poi, _world, plan = _camp(config)
    assert plan.cells[0, 0] == VOID and plan.cells[-1, -1] == VOID


def test_a_camp_has_no_walls(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int(Cell.WALL) not in plan.cells


def test_a_camp_is_open_air_so_both_views_agree(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert np.array_equal(plan.cells, plan.outside)


def test_a_camp_keeps_off_water(config: Config) -> None:
    world = flat_world(14, 10, Biome.GRASS)
    world.biome[:, :6] = int(Biome.SHALLOW)
    world.water_type[:, :6] = int(WaterType.SALT)
    poi, world, plan = _camp(config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert not ((plan.cells != VOID) & patch.water).any()


def test_a_track_joins_the_camp_to_a_road_gate(config: Config) -> None:
    world = flat_world(14, 10)
    world.road[5, 8:14] = 1  # a road arrives from the east
    _poi, _world, plan = _camp(config, world)
    assert PATH in plan.cells


def test_a_camp_without_a_road_has_no_track(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert PATH not in plan.cells
