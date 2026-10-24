"""Tests for the shrine layout: one small walled room with a door and an altar."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan, site_roof_floor
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world

WALL, DOOR, HEARTH = int(Cell.WALL), int(Cell.DOOR), int(Cell.HEARTH)


def _shrine(config: Config):
    world = flat_world(14, 10)
    poi = add_poi(world, "shrine", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return world, poi, plan


def test_a_shrine_has_one_altar_at_its_middle(config: Config) -> None:
    _world, _poi, plan = _shrine(config)
    ys, xs = np.nonzero(plan.cells == HEARTH)
    walls = np.argwhere(plan.cells == WALL)
    assert (
        len(ys) == 1 and walls[:, 0].min() < ys[0] < walls[:, 0].max() and walls[:, 1].min() < xs[0] < walls[:, 1].max()
    )


def test_a_shrine_is_walled_and_has_a_door(config: Config) -> None:
    _world, _poi, plan = _shrine(config)
    assert (plan.cells == WALL).any() and (plan.cells == DOOR).any()


def test_a_shrine_is_a_roof_of_its_own_kind_from_outside(config: Config) -> None:
    # Like every building the shrine's roof has a colour of its own, not the roof of another kind.
    _world, _poi, plan = _shrine(config)
    assert (plan.outside == roof_cell(config, "shrine")).any() and not (plan.outside == roof_cell(config, "ruin")).any()


def test_a_shrine_has_a_roof_level_like_the_other_buildings(config: Config) -> None:
    world = flat_world(14, 10)
    poi = add_poi(world, "shrine", 7, 5)
    roof = site_plan(poi, site_roof_floor(poi, config), config, world)
    assert roof is not None and (roof.cells == roof_cell(config, "shrine")).any()


def test_a_shrine_is_smaller_than_a_ruin(config: Config) -> None:
    world = flat_world(14, 10)
    shrine, ruin = add_poi(world, "shrine", 3, 5), add_poi(world, "ruin", 10, 5)
    sized = [int((site_plan(p, 0, config, world).cells != 0).sum()) for p in (shrine, ruin)]  # type: ignore[union-attr]
    assert sized[0] < sized[1]


def test_a_shrine_is_deterministic(config: Config) -> None:
    world, poi, first = _shrine(config)
    clear_cache()
    again = site_plan(poi, 0, config, world)
    assert again is not None and np.array_equal(first.cells, again.cells)
