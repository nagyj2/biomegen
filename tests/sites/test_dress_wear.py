"""Tests for the wear a ruin gives its dressings: fields, piers, boats and wheels fade back into the terrain."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from biomegen.config.model import Config
from biomegen.sites import SitePlan, site_plan
from biomegen.sites.dress import variant_cell
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world


@pytest.fixture(scope="module")
def full(config: Config) -> Config:
    """The test config with every tier's ruin drawn at full extent, so a ruin shares its settlement's lots."""
    cfg = copy.deepcopy(config)
    for row in cfg.data["tables"]["sites"].values():
        if "ruin_extent_share" in row:
            row["ruin_extent_share"] = 1.0
    return cfg


def _world(sea: bool = False, river: bool = False):
    world = flat_world(16, 12, Biome.GRASS)
    if sea:
        world.biome[:, 6:] = int(Biome.DEEP)
        world.water_type[:, 6:] = int(WaterType.SALT)
    if river:
        world.water_type[:, 7] = int(WaterType.FRESH)
    return world


def _pair(config: Config, tier: str, tags=(), fell: int | None = None, sea=False, river=False, pop=3000):
    """The standing settlement and the ruin of it (same cell, seed and tags), as plans."""
    x = 5 if sea else 6 if river else 8  # beside the sea, beside the river, or in open grass
    standing, ruin_world = _world(sea, river), _world(sea, river)
    ruin_world.year = standing.year = 1200
    poi = add_poi(standing, tier, x, 6, pop=pop, civilized=True, tags=tags)
    ruin = add_poi(ruin_world, "ruin", x, 6, pop=pop, ruin_of=tier, tags=tags, fell=fell, floor_count=1)
    built, fallen = site_plan(poi, 0, config, standing), site_plan(ruin, 0, config, ruin_world)
    assert built is not None and fallen is not None
    return built, fallen


def _count(plan: SitePlan, cells) -> int:
    return int(np.isin(plan.cells, [int(c) for c in cells]).sum())


def _field(config: Config) -> list[int]:
    return [int(Cell.WHEAT)] + [variant_cell(config, "field", v) for v in ("harvested", "dead")]


def test_a_ruins_field_is_worn_back_into_the_terrain(full: Config) -> None:
    standing, ruin = _pair(full, "town")
    assert 0 < _count(ruin, _field(full)) < _count(standing, _field(full))


def test_a_young_ruin_keeps_more_of_its_field_than_an_old_one(full: Config) -> None:
    _s, young = _pair(full, "town", fell=1198)
    _s, old = _pair(full, "town", fell=None)
    assert _count(young, _field(full)) > _count(old, _field(full))


def test_a_ruins_pier_loses_planks(full: Config) -> None:
    standing, ruin = _pair(full, "town", ("port",), sea=True)
    assert 0 < _count(ruin, [Cell.BRIDGE]) < _count(standing, [Cell.BRIDGE])


def test_a_ruins_moored_boats_are_lost(full: Config) -> None:
    standing, ruin = _pair(full, "town", ("port",), sea=True)
    assert _count(ruin, [Cell.HULL]) < _count(standing, [Cell.HULL])


def test_a_ruins_water_wheel_loses_pieces(full: Config) -> None:
    standing, ruin = _pair(full, "town", ("river",), river=True)
    assert _count(standing, [Cell.WHEEL]) > 0 and _count(ruin, [Cell.WHEEL]) < _count(standing, [Cell.WHEEL])


def test_without_wear_a_ruins_dressings_are_kept(full: Config) -> None:
    # Wear is the only thing that takes a dressing: with every share at 0 the ruin has as many field cells as the town.
    unworn = copy.deepcopy(full)
    for row in unworn.data["tables"]["dress"].values():
        row["wear"] = {"void": 0.0, "rubble": 0.0, "overgrown": 0.0}
    standing, ruin = _pair(unworn, "town")
    assert _count(ruin, _field(unworn)) == _count(standing, _field(unworn))


def test_a_standing_site_is_not_touched_by_wear(full: Config) -> None:
    # The wear shares are read only by a ruin: changing them leaves a standing settlement's plan as it was.
    heavy = copy.deepcopy(full)
    heavy.data["tables"]["dress"]["field"]["wear"] = {"void": 1.0, "rubble": 0.0, "overgrown": 0.0}
    first, _r = _pair(full, "town")
    second, _r = _pair(heavy, "town")
    assert np.array_equal(first.cells, second.cells)


def test_wear_is_deterministic(full: Config) -> None:
    _s, first = _pair(full, "town")
    _s, second = _pair(full, "town")
    assert np.array_equal(first.cells, second.cells)
