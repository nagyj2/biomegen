"""Tests for the homestead layout: one house in a yard, dressed for its style, a pure function of the site seed."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config.model import Config
from biomegen.sites import clear_cache, read_patch, site_geometry, site_plan
from biomegen.sites.geometry import site_row_for
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

ROOF, DOOR, WHEEL, BRIDGE = (int(c) for c in (Cell.ROOF, Cell.DOOR, Cell.WHEEL, Cell.BRIDGE))
STYLES = ("farm", "mill", "mine", "lodge", "fishery")


def _homestead(config: Config, style: str = "farm", world=None, tags: tuple[str, ...] = (), x: int = 7, y: int = 5):
    world = world or flat_world(16, 12)
    poi = add_poi(world, "homestead", x, y, style=style, tags=tags)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return poi, world, plan


def test_every_style_has_a_site_row_that_fits_the_extent(config: Config) -> None:
    # Each style draws from its own `homestead_<style>` row, and none is too small to hold a plan.
    world = flat_world(16, 12)
    for style in STYLES:
        poi = add_poi(world, "homestead", 7, 5, style=style)
        assert site_row_for(config, poi) == f"homestead_{style}" and site_geometry(poi, config) is not None
        world.pois.clear()


def test_an_unknown_style_falls_back_to_the_plain_row(config: Config) -> None:
    poi = add_poi(flat_world(16, 12), "homestead", 7, 5, style="orchard")
    assert site_row_for(config, poi) == "homestead"


@pytest.mark.parametrize("style", STYLES)
def test_a_homestead_is_one_building(config: Config, style: str) -> None:
    # Roofs seen from outside form a single connected blob: one house, however it is dressed.
    tags = {"mill": ("river",), "fishery": ("port",)}.get(style, ())
    _poi, _world, plan = _homestead(config, style, tags=tags)
    _labels, count = ndimage.label(plan.outside == ROOF)
    assert count == 1


def test_a_homestead_house_has_a_street_door(config: Config) -> None:
    _poi, _world, plan = _homestead(config)
    assert DOOR in plan.cells


def test_a_homestead_is_a_pure_function_of_its_seed(config: Config) -> None:
    # The same POI gives the same plan after the cache is dropped; a different seed gives a different one.
    poi, world, plan = _homestead(config)
    clear_cache()
    again = site_plan(poi, 0, config, world)
    assert again is not None and np.array_equal(again.cells, plan.cells)


def test_a_different_seed_gives_a_different_house(config: Config) -> None:
    world = flat_world(16, 12)
    a = site_plan(add_poi(world, "homestead", 4, 5, style="lodge", interior_seed=1), 0, config, world)
    b = site_plan(add_poi(world, "homestead", 11, 5, style="lodge", interior_seed=2), 0, config, world)
    assert a is not None and b is not None and not np.array_equal(a.cells, b.cells)


WHEAT, LOG, FLOOR = (int(c) for c in (Cell.WHEAT, Cell.LOG, Cell.FLOOR))


def test_a_farm_sows_a_wheat_field_and_keeps_a_wagon(config: Config) -> None:
    _poi, _world, plan = _homestead(config, "farm")
    assert int((plan.cells == WHEAT).sum()) >= 20 and int((plan.cells == int(Cell.WAGON)).sum()) == 1


def test_a_farm_has_no_hedge_ring(config: Config) -> None:
    # The wheat field replaced the ring of bushes: a ring would be dozens of bushes; only the odd scattered one is
    # left (trees and bushes scatter at the plain wooded share, which a farm leaves at the default).
    _poi, _world, plan = _homestead(config, "farm")
    assert int((plan.cells == int(Cell.BUSH)).sum()) <= 12


def test_the_wheat_field_is_open_ground_from_outside(config: Config) -> None:
    # Seen from outside (the map, zoom and local views, and an upper floor) wheat stays wheat: only the house is roofed.
    _poi, _world, plan = _homestead(config, "farm")
    assert int((plan.outside == WHEAT).sum()) == int((plan.cells == WHEAT).sum())


def test_the_wheat_field_does_not_touch_the_house(config: Config) -> None:
    # Every wheat cell keeps a cell clear of the walls, so the field never grows into the building.
    _poi, _world, plan = _homestead(config, "farm")
    roof = ndimage.binary_dilation(plan.outside == ROOF, iterations=1)
    assert not (roof & (plan.cells == WHEAT)).any()


def test_the_wheat_field_is_one_block(config: Config) -> None:
    labels, count = ndimage.label(plan_wheat := _homestead(config, "farm")[2].cells == WHEAT)
    assert count >= 1 and int(plan_wheat.sum()) >= 20


def test_a_lodge_has_a_felled_timber_clearing(config: Config) -> None:
    # A bare working area with felled trunks lying in it, beside the house.
    _poi, _world, plan = _homestead(config, "lodge")
    assert int((plan.cells == LOG).sum()) >= 6 and int((plan.cells == FLOOR).sum()) > int((plan.cells == LOG).sum())


def test_a_lodges_trunks_lie_on_its_clearing(config: Config) -> None:
    # Each felled trunk cell has bare floor of the clearing at its side, not woods.
    _poi, _world, plan = _homestead(config, "lodge")
    logs = plan.cells == LOG
    beside = ndimage.binary_dilation(logs, iterations=1) & ~logs
    assert (plan.cells[beside] == FLOOR).mean() > 0.5


def test_a_lodge_scatters_trees_round_it(config: Config) -> None:
    _poi, _world, plan = _homestead(config, "lodge")
    assert int((plan.cells == int(Cell.TREE)).sum()) >= 10


def test_a_mine_heaps_spoil(config: Config) -> None:
    _poi, _world, plan = _homestead(config, "mine")
    assert int(np.isin(plan.cells, [int(Cell.ROCK), int(Cell.RUBBLE)]).sum()) >= 10


def test_a_lodge_is_woodier_than_a_plain_homestead(config: Config) -> None:
    _p, _w, lodge = _homestead(config, "lodge")
    _p, _w, plain = _homestead(config, "orchard")
    trees = lambda plan: int((plan.cells == int(Cell.TREE)).sum())  # noqa: E731
    assert trees(lodge) > trees(plain)


def _riverside(config: Config, tags: tuple[str, ...], style: str = "mill"):
    world = flat_world(16, 12)
    world.water_type[:, 8] = int(WaterType.FRESH)
    return _homestead(config, style, world, tags)


def test_a_mill_turns_a_wheel_in_the_river(config: Config) -> None:
    # A river homestead of style mill sets a multi-cell water wheel into the river, as a river settlement's mill does.
    poi, world, plan = _riverside(config, ("river",))
    patch = read_patch(poi, site_geometry(poi, config), world, config)  # type: ignore[arg-type]
    wheel = plan.cells == WHEEL
    assert wheel.sum() >= 8 and patch.river[wheel].all()


def test_a_mill_without_a_river_in_reach_is_a_plain_house(config: Config) -> None:
    _poi, _world, plan = _homestead(config, "mill", tags=("river",))
    assert WHEEL not in plan.cells and DOOR in plan.cells


def _coast(config: Config, tags: tuple[str, ...], style: str = "fishery"):
    world = flat_world(16, 12)
    world.biome[:, 8:] = int(Biome.DEEP)
    world.water_type[:, 8:] = int(WaterType.SALT)
    return _homestead(config, style, world, tags, x=7, y=6)


def test_a_fishery_builds_a_pier_into_open_water(config: Config) -> None:
    poi, world, plan = _coast(config, ("port",))
    patch = read_patch(poi, site_geometry(poi, config), world, config)  # type: ignore[arg-type]
    assert (plan.cells[patch.still] == BRIDGE).any()


def test_a_fishery_without_the_port_tag_builds_no_pier(config: Config) -> None:
    poi, world, plan = _coast(config, ())
    patch = read_patch(poi, site_geometry(poi, config), world, config)  # type: ignore[arg-type]
    assert not (plan.cells[patch.still] != int(Cell.VOID)).any()


def test_a_farm_builds_nothing_over_water(config: Config) -> None:
    # Only a mill's wheel and a fishery's pier may stand over water; a farm on a shore keeps to dry ground.
    poi, world, plan = _coast(config, (), style="farm")
    patch = read_patch(poi, site_geometry(poi, config), world, config)  # type: ignore[arg-type]
    assert not (plan.cells[patch.water] != int(Cell.VOID)).any()


def test_a_homestead_on_a_one_cell_island_still_gets_a_plan_or_none(config: Config) -> None:
    # With no dry ground the layout declines (None) instead of failing.
    world = flat_world(16, 12)
    world.biome[:] = int(Biome.DEEP)
    world.water_type[:] = int(WaterType.SALT)
    poi = add_poi(world, "homestead", 7, 5, style="farm")
    assert site_plan(poi, 0, config, world) is None


@pytest.mark.parametrize("style", STYLES)
def test_every_style_gets_a_plan_whatever_its_seeds_size(style: str) -> None:
    # The extent jitters with the seed, down to 0.75 of its size: a small extent still holds the house and its yard.
    from biomegen.config import load_config

    config = load_config(None)
    for seed in range(1, 31):
        world = flat_world(16, 12)
        poi = add_poi(world, "homestead", 7, 5, style=style, interior_seed=seed)
        assert site_plan(poi, 0, config, world) is not None, seed


def test_a_homestead_on_a_shore_takes_the_smallest_house_when_the_big_one_does_not_fit(config: Config) -> None:
    # Water takes all but a corner of the extent; a small house still fits there, so the site is not lost.
    world = flat_world(16, 12)
    for row in range(12):
        world.water_type[row, 7 + row // 3 :] = int(WaterType.SALT)
        world.biome[row, 7 + row // 3 :] = int(Biome.DEEP)
    world.water_type[:5, 7:] = int(WaterType.NONE)
    world.biome[:5, 7:] = int(Biome.GRASS)
    world.water_type[:, 8:] = int(WaterType.SALT)
    world.biome[:, 8:] = int(Biome.DEEP)
    poi = add_poi(world, "homestead", 7, 5, style="farm")
    plan = site_plan(poi, 0, config, world)
    assert plan is not None and int((plan.outside == ROOF).sum()) > 0
