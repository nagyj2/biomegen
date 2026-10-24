"""Tests for the battlefield layout: an open trampled field, debris, wrecked wagons, nothing built."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import clear_cache, read_patch, site_geometry, site_plan
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR = int(Cell.VOID), int(Cell.FLOOR)
BUILT = [int(c) for c in (Cell.WALL, Cell.DOOR, Cell.STONE, Cell.CAMPFIRE, Cell.BED)]


def _field(config: Config, world=None):
    world = world or flat_world(14, 10)
    poi = add_poi(world, "battlefield", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return world, poi, plan


def test_a_battlefield_is_open_ground_with_nothing_built(config: Config) -> None:
    _world, _poi, plan = _field(config)
    assert not np.isin(plan.cells, BUILT).any()


def test_a_battlefield_is_strewn_with_debris(config: Config) -> None:
    _world, _poi, plan = _field(config)
    assert int(np.isin(plan.cells, [int(Cell.RUBBLE), int(Cell.ROCK)]).sum()) > 0


def test_a_battlefield_has_a_standard_at_each_end(config: Config) -> None:
    _world, _poi, plan = _field(config)
    xs = np.nonzero(plan.cells == int(Cell.BANNER))[1]
    assert len(xs) == config.get("sites.battlefield.banners") and xs.min() < plan.cells.shape[1] // 2 < xs.max()


def test_a_battlefield_has_a_burial_ground(config: Config) -> None:
    _world, _poi, plan = _field(config)
    low, high = config.get("sites.battlefield.graves")
    assert 1 <= int((plan.cells == int(Cell.GRAVE)).sum()) <= high and low > 0


def test_the_wreckage_is_thickest_at_the_middle(config: Config) -> None:
    # Debris (anything but floor and the laid-out features) is denser in the middle third than in the outer thirds.
    _world, _poi, plan = _field(config)
    cols = plan.cells.shape[1]
    inside = plan.cells[:, cols // 3 : 2 * cols // 3]
    outer = np.concatenate([plan.cells[:, : cols // 3], plan.cells[:, 2 * cols // 3 :]], axis=1)
    debris = [int(Cell.RUBBLE), int(Cell.BONES), int(Cell.ROCK), int(Cell.CRATE), int(Cell.BARREL)]
    assert np.isin(inside, debris).sum() / inside.size > np.isin(outer, debris).sum() / outer.size


def test_a_battlefield_is_larger_than_a_camp(config: Config) -> None:
    rows = config.get("tables.sites")
    assert rows["battlefield"]["extent_tiles"][0] > rows["camp"]["extent_tiles"][0] * 2


def test_a_battlefield_has_wrecked_wagons_within_the_rows_range(config: Config) -> None:
    _world, _poi, plan = _field(config)
    low, high = config.get("sites.battlefield.wagons")
    assert low <= int((plan.cells == int(Cell.WAGON)).sum()) <= high


def test_the_field_leaves_its_corners_to_the_terrain(config: Config) -> None:
    _world, _poi, plan = _field(config)
    assert plan.cells[0, 0] == VOID and plan.cells[-1, -1] == VOID


def test_a_battlefield_is_deterministic(config: Config) -> None:
    world = flat_world(14, 10)
    poi = add_poi(world, "battlefield", 7, 5)
    first = site_plan(poi, 0, config, world)
    clear_cache()
    again = site_plan(poi, 0, config, world)
    assert first is not None and again is not None and np.array_equal(first.cells, again.cells)


def test_a_battlefield_stays_off_the_water(config: Config) -> None:
    world = flat_world(14, 10, Biome.GRASS)
    world.water_type[:, :6] = int(WaterType.SALT)
    world.biome[:, :6] = int(Biome.SHALLOW)
    poi = add_poi(world, "battlefield", 7, 5)
    plan = site_plan(poi, 0, config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert plan is not None and not ((plan.cells != VOID) & patch.water).any()
