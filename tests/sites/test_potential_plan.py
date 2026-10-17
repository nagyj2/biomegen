"""Tests that a settlement's plan is drawn for its potential and reads what stands from the manifest."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_geometry, site_plan
from biomegen.sites.geometry import site_row_for
from biomegen.sites.potential import plan_tier
from biomegen.sites.surroundings import settlement_kinds
from biomegen.world.entities import POI
from biomegen.world.manifest import SiteManifest
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world

STONE = int(Cell.STONE)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _poi(kind: str, **fields: object) -> POI:
    return POI(kind=kind, x=10, y=7, interior_seed=11, civilized=True, **fields)  # type: ignore[arg-type]


def test_the_plan_tier_is_the_stored_potential(cfg: Config) -> None:
    assert plan_tier(cfg, _poi("village", potential="town")) == "town"


def test_a_poi_with_no_potential_is_planned_as_its_own_tier(cfg: Config) -> None:
    assert plan_tier(cfg, _poi("village")) == "village"


def test_a_settlement_is_drawn_from_the_row_of_its_potential(cfg: Config) -> None:
    assert site_row_for(cfg, _poi("village", potential="town")) == "town"


def test_a_ruin_is_drawn_from_the_row_of_its_potential_not_the_tier_it_was(cfg: Config) -> None:
    ruin = POI(kind="ruin", x=10, y=7, interior_seed=11, ruin_of="village", potential="town")
    assert site_row_for(cfg, ruin) == "town"


def test_a_homestead_keeps_its_own_row(cfg: Config) -> None:
    homestead = POI(kind="homestead", x=10, y=7, interior_seed=11, style="farm", potential="village")
    assert site_row_for(cfg, homestead) == "homestead_farm"


def test_the_extent_does_not_depend_on_the_population(cfg: Config) -> None:
    low, high = cfg.get("tables.tiers.village.pop")
    assert site_geometry(_poi("village", pop=low), cfg) == site_geometry(_poi("village", pop=high), cfg)


def _plan(config: Config, poi: POI, manifest: SiteManifest | None = None):
    world = flat_world(20, 14)
    placed = add_poi(
        world,
        poi.kind,
        poi.x,
        poi.y,
        civilized=True,
        pop=poi.pop,
        potential=poi.potential,
        floor_count=poi.floor_count,
        interior_seed=poi.interior_seed,
    )
    clear_cache()
    plan = site_plan(placed, 0, config, world, manifest)
    assert plan is not None
    return plan


def test_a_plan_does_not_read_the_tier_or_the_population(cfg: Config) -> None:
    # Two POIs that differ only in tier and population, given the same potential and manifest, draw one plan.
    manifest = SiteManifest("village", 3, 1, False)
    village = _plan(cfg, _poi("village", pop=100, potential="city"), manifest)
    town = _plan(cfg, _poi("town", pop=6000, potential="city"), manifest)
    assert np.array_equal(village.cells, town.cells) and np.array_equal(village.outside, town.outside)


def test_the_centre_follows_the_manifests_tier(cfg: Config) -> None:
    plan = _plan(cfg, _poi("village", pop=100, potential="city"), SiteManifest("town", 3, 1, False))
    from biomegen.sites.kinds import roof_cell

    assert roof_cell(cfg, "hall") in plan.outside and roof_cell(cfg, "chapel") not in plan.outside


def test_the_wall_stands_only_when_the_manifest_says_so(cfg: Config) -> None:
    poi = _poi("city", pop=20000, potential="city")
    without = _plan(cfg, poi, SiteManifest("city", 3, 1, False))
    walled = _plan(cfg, poi, SiteManifest("city", 3, 1, True))
    assert (STONE in walled.outside) and (STONE not in without.outside)


def test_the_specialized_kinds_do_not_depend_on_the_population(cfg: Config) -> None:
    world = flat_world(20, 14)
    small = add_poi(world, "town", 10, 7, civilized=True, pop=1600, potential="town")
    large = add_poi(world, "town", 10, 7, civilized=True, pop=7900, potential="town")
    assert settlement_kinds(world, cfg, small) == settlement_kinds(world, cfg, large)


def test_a_settlement_is_chosen_no_more_kinds_than_its_potentials_slots(cfg: Config) -> None:
    world = flat_world(20, 14)
    village = add_poi(world, "village", 10, 7, civilized=True, pop=100, potential="town")
    assert len(settlement_kinds(world, cfg, village)) <= cfg.get("tables.sites.town.specialized")[1]


def test_a_smaller_potential_chooses_a_prefix_of_the_kinds_a_larger_one_does(cfg: Config) -> None:
    # The slots are shared out one at a time, so the first of a long list are the whole of a shorter one.
    world = flat_world(20, 14)
    village = add_poi(world, "village", 10, 7, civilized=True, pop=100, potential="village")
    capital = add_poi(world, "village", 10, 7, civilized=True, pop=100, potential="city")
    short, long = settlement_kinds(world, cfg, village), settlement_kinds(world, cfg, capital)
    assert long[: len(short)] == short
