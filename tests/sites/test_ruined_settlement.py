"""Tests for ruins that were a settlement: the tier's own plan with a fall pass (buildings, wall, gates, extent)."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config.model import Config
from biomegen.sites import SitePlan, site_geometry, site_plan
from biomegen.sites.kinds import roof_cell, tier_centre
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world, roofs

PATH, RUBBLE, DOOR = (int(c) for c in (Cell.PATH, Cell.RUBBLE, Cell.DOOR))
SEED = 77


@pytest.fixture(scope="module")
def full(config: Config) -> Config:
    """The test config with every tier's ruin drawn at full extent, so a ruin and its settlement share their lots."""
    cfg = copy.deepcopy(config)
    for row in cfg.data["tables"]["sites"].values():
        if "ruin_extent_share" in row:
            row["ruin_extent_share"] = 1.0
    return cfg


def _plans(config: Config, tier: str, fell: int | None, seed: int = SEED, pop: int = 2500) -> tuple[SitePlan, SitePlan]:
    """The settlement of ``tier`` and the ruin it became (same cell, seed and population), as plans."""
    world = flat_world(16, 12)
    world.year = 1200
    town = add_poi(world, tier, 8, 6, pop=pop, interior_seed=seed)
    other = flat_world(16, 12)
    other.year = 1200
    ruin = add_poi(other, "ruin", 8, 6, pop=pop, interior_seed=seed, ruin_of=tier, fell=fell, floor_count=1)
    built, fallen = site_plan(town, 0, config, world), site_plan(ruin, 0, config, other)
    assert built is not None and fallen is not None
    return built, fallen


def test_a_ruin_that_was_a_town_has_the_towns_streets(full: Config) -> None:
    # The fall pass touches buildings and the wall, never the streets, so the paths are the settlement's own.
    town, ruin = _plans(full, "town", fell=900)
    assert np.array_equal(town.cells == PATH, ruin.cells == PATH)


def test_a_ruin_has_fewer_roofs_than_the_town_it_was(full: Config) -> None:
    town, ruin = _plans(full, "town", fell=900)
    assert roofs(ruin.outside).sum() < roofs(town.outside).sum()


@pytest.mark.parametrize("seed", range(12))
def test_at_least_one_building_always_stands(full: Config, seed: int) -> None:
    _town, ruin = _plans(full, "village", fell=None, seed=seed, pop=300)
    assert (ruin.cells == int(Cell.WALL)).any()


def test_a_young_ruin_keeps_more_floor_than_an_old_one(full: Config) -> None:
    _t, young = _plans(full, "town", fell=1195)
    _t, old = _plans(full, "town", fell=None)
    assert (young.cells == int(Cell.FLOOR)).sum() > (old.cells == int(Cell.FLOOR)).sum()


def test_every_gate_of_a_walled_ruin_is_breached(full: Config) -> None:
    # In the settlement a gate is a door that shows as street from outside; the ruin has rubble in its place.
    town, ruin = _plans(full, "city", fell=500, pop=20000)
    gates = (town.cells == DOOR) & (town.outside == PATH)
    assert gates.any() and (ruin.cells[gates] == RUBBLE).all()


def test_part_of_the_wall_falls(full: Config) -> None:
    town, ruin = _plans(full, "capital", fell=None, pop=80000)
    wall = int(Cell.WALL)
    assert (ruin.cells == wall).sum() < (town.cells == wall).sum()


def test_a_ruins_floor_is_cracked_into_rubble(full: Config) -> None:
    town, ruin = _plans(full, "town", fell=None)
    assert (ruin.cells == RUBBLE).sum() > (town.cells == RUBBLE).sum()


def test_the_same_ruin_gives_the_same_plan(full: Config) -> None:
    _t, first = _plans(full, "town", fell=700)
    from biomegen.sites import clear_cache

    clear_cache()
    _t, second = _plans(full, "town", fell=700)
    assert np.array_equal(first.cells, second.cells)


def test_a_big_ruin_is_drawn_smaller_by_its_extent_share(config: Config) -> None:
    world = flat_world(16, 12)
    ruin = add_poi(world, "ruin", 8, 6, pop=80000, ruin_of="capital", floor_count=1)
    tier = add_poi(world, "capital", 4, 6, pop=80000)
    share = float(config.get("tables.sites.capital.ruin_extent_share"))
    ruin_geometry, tier_geometry = site_geometry(ruin, config), site_geometry(tier, config)
    assert ruin_geometry is not None and tier_geometry is not None
    width = lambda g: g.extent[2] - g.extent[0]  # noqa: E731
    assert width(ruin_geometry) == pytest.approx(width(tier_geometry) * share)


def test_a_ruin_with_no_origin_keeps_the_single_building_extent(config: Config) -> None:
    world = flat_world(16, 12)
    ruin = add_poi(world, "ruin", 8, 6, floor_count=1)
    geometry = site_geometry(ruin, config)
    assert geometry is not None and geometry.extent[2] - geometry.extent[0] == pytest.approx(
        float(config.get("tables.sites.ruin.extent_tiles")[0])
    )


def test_an_origin_with_no_site_row_falls_back_to_the_single_building(config: Config) -> None:
    world = flat_world(16, 12)
    ruin = add_poi(world, "ruin", 8, 6, ruin_of="fortress", floor_count=1)
    assert site_plan(ruin, 0, config, world) is not None


TIERS = ["hamlet", "village", "town", "city", "capital"]


def _centre_footprint(config: Config, town: SitePlan, tier: str) -> np.ndarray:
    """The cells of the tier's centre building, seen from outside in the standing settlement."""
    return town.outside == roof_cell(config, tier_centre(config, tier))


@pytest.mark.parametrize("tier", TIERS)
@pytest.mark.parametrize("seed", range(6))
def test_the_centre_building_always_survives_a_ruin(full: Config, tier: str, seed: int) -> None:
    # However old the ruin or the draws, the stone centre keeps walls standing where it stood.
    town, ruin = _plans(full, tier, fell=None, seed=seed, pop=300)
    assert (ruin.cells[_centre_footprint(full, town, tier)] == int(Cell.WALL)).any()


@pytest.mark.parametrize("tier", TIERS)
def test_the_surviving_centre_is_damaged_not_whole(full: Config, tier: str) -> None:
    # A survivor is damaged but not destroyed: it keeps walls, yet its cells are not as they were in the settlement.
    town, ruin = _plans(full, tier, fell=900, pop=300)
    footprint = _centre_footprint(full, town, tier)
    assert not np.array_equal(ruin.cells[footprint], town.cells[footprint])


def test_a_building_is_either_a_damaged_survivor_or_wholly_gone(full: Config) -> None:
    # No half measures: of each building of the town, the ruin keeps its walls (a survivor) or no wall and no floor at
    # all (destroyed, with rubble where it stood).
    town, ruin = _plans(full, "town", fell=None)
    labels, count = ndimage.label(roofs(town.outside))
    walls = [(ruin.cells[labels == i] == int(Cell.WALL)).any() for i in range(1, count + 1)]
    floors = [(ruin.cells[labels == i] == int(Cell.FLOOR)).any() for i in range(1, count + 1)]
    assert all(wall or not floor for wall, floor in zip(walls, floors, strict=True))


def test_a_destroyed_building_leaves_rubble_in_its_place(full: Config) -> None:
    town, ruin = _plans(full, "town", fell=None)
    labels, count = ndimage.label(roofs(town.outside))
    gone = [
        i for i in range(1, count + 1) if not (ruin.cells[labels == i] == int(Cell.WALL)).any()
    ]  # buildings with no wall left
    assert gone and all((ruin.cells[labels == i] == RUBBLE).any() for i in gone)


def test_most_buildings_of_an_old_ruin_are_destroyed(full: Config) -> None:
    town, ruin = _plans(full, "town", fell=None)
    labels, count = ndimage.label(roofs(town.outside))
    standing = sum((ruin.cells[labels == i] == int(Cell.WALL)).any() for i in range(1, count + 1))
    assert standing < count / 2
