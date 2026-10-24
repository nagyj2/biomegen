"""Tests for the boat layout: hull, deck, deckhouse and cargo, all on water."""

from __future__ import annotations

import copy

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import read_patch, site_geometry, site_plan, site_roof_floor
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, FLOOR, WALL, DOOR, HULL = (int(c) for c in (Cell.VOID, Cell.FLOOR, Cell.WALL, Cell.DOOR, Cell.HULL))


def _sea() -> object:
    world = flat_world(14, 10, Biome.SHALLOW)
    world.water_type[:] = int(WaterType.SALT)
    return world


def _boat(config: Config):
    world = _sea()
    poi = add_poi(world, "boat", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return poi, world, plan


def test_a_boat_has_a_hull_round_its_deck(config: Config) -> None:
    _poi, _world, plan = _boat(config)
    assert HULL in plan.cells and FLOOR in plan.cells


def test_the_hull_closes_the_deck(config: Config) -> None:
    # No deck cell touches void: the planking surrounds it.
    _poi, _world, plan = _boat(config)
    cells = np.pad(plan.cells, 1, constant_values=VOID)
    deck = cells[1:-1, 1:-1] == FLOOR
    open_side = (
        (cells[:-2, 1:-1] == VOID) | (cells[2:, 1:-1] == VOID) | (cells[1:-1, :-2] == VOID) | (cells[1:-1, 2:] == VOID)
    )
    assert not (deck & open_side).any()


def test_a_boat_is_longer_than_it_is_wide(config: Config) -> None:
    _poi, _world, plan = _boat(config)
    ys, xs = np.nonzero(plan.cells != VOID)
    assert (xs.max() - xs.min()) > (ys.max() - ys.min())


def _big_boat(config: Config):
    """A boat wide enough for a deckhouse (the default one is too narrow): its config, POI, world and ground plan."""
    big = copy.deepcopy(config)
    big.data["tables"]["sites"]["boat"]["extent_tiles"] = [1.0, 0.6]
    world = _sea()
    poi = add_poi(world, "boat", 7, 5)
    plan = site_plan(poi, 0, big, world)
    assert plan is not None
    return big, poi, world, plan


def test_a_big_boat_has_a_cabin_with_a_door(config: Config) -> None:
    _big, _poi, _world, plan = _big_boat(config)
    assert WALL in plan.cells and DOOR in plan.cells


def test_the_deckhouse_is_a_roof_from_outside_over_the_cabin(config: Config) -> None:
    # Seen from above the cabin's walls are hidden under the deckhouse roof; the deck and hull stay as they are.
    big, _poi, _world, plan = _big_boat(config)
    roof = plan.outside == roof_cell(big, "deckhouse")
    assert roof.any() and (plan.cells[plan.outside != plan.cells] != VOID).all() and WALL not in plan.outside
    assert (plan.cells[roof] != VOID).all() and HULL in plan.outside


def test_a_boat_has_a_roof_level_that_roofs_its_deckhouse(config: Config) -> None:
    big, poi, world, plan = _big_boat(config)
    roof = site_plan(poi, site_roof_floor(poi, big), big, world)
    assert roof is not None and np.array_equal(roof.cells, plan.outside)


def test_the_deckhouse_is_a_listed_building(config: Config) -> None:
    _big, _poi, _world, plan = _big_boat(config)
    assert [building.kind for building in plan.buildings] == ["deckhouse"]


def test_a_boat_carries_cargo(config: Config) -> None:
    _poi, _world, plan = _boat(config)
    cargo = {int(Cell.CARGO), int(Cell.BARREL), int(Cell.CRATE), int(Cell.CHEST)}
    assert cargo & set(np.unique(plan.cells).tolist())


def test_a_boat_lies_wholly_on_water(config: Config) -> None:
    poi, world, plan = _boat(config)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert not ((plan.cells != VOID) & ~patch.water).any()


def test_a_boat_is_cut_by_the_shore(config: Config) -> None:
    # Half the water becomes land: the boat keeps only the wet half, or has no plan at all.
    world = _sea()
    world.biome[:, 7:] = int(Biome.GRASS)
    world.water_type[:, 7:] = int(WaterType.NONE)
    poi = add_poi(world, "boat", 7, 5)
    plan = site_plan(poi, 0, config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert plan is None or not ((plan.cells != VOID) & ~patch.water).any()


def test_a_boat_with_no_deckhouse_is_open_air_so_both_views_agree(config: Config) -> None:
    _poi, _world, plan = _boat(config)
    assert np.array_equal(plan.cells, plan.outside) and plan.buildings == ()


def test_a_moored_boat_is_stamped_on_open_water() -> None:
    import random

    import numpy as np

    from biomegen.sites.boat import moor_boat
    from biomegen.world.tile import Cell

    grid = np.zeros((12, 24), dtype=np.uint8)
    water = np.ones(grid.shape, dtype=bool)
    assert moor_boat(grid, water, 6, 4, 4, 10, random.Random(1)) and int(Cell.HULL) in grid and int(Cell.FLOOR) in grid


def test_a_moored_boat_is_refused_where_there_is_land() -> None:
    import random

    import numpy as np

    from biomegen.sites.boat import moor_boat

    grid = np.zeros((12, 24), dtype=np.uint8)
    water = np.ones(grid.shape, dtype=bool)
    water[5, 8] = False
    assert not moor_boat(grid, water, 6, 4, 4, 10, random.Random(1)) and not grid.any()


def test_a_moored_boat_is_refused_over_existing_cells() -> None:
    import random

    import numpy as np

    from biomegen.sites.boat import moor_boat

    grid = np.zeros((12, 24), dtype=np.uint8)
    grid[5, 8] = 7
    assert not moor_boat(grid, np.ones(grid.shape, dtype=bool), 6, 4, 4, 10, random.Random(1))
