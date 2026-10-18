"""Tests for the manifest of a settlement today: its tier and population turned into what stands in its plan."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.config.population import tier_pop_range
from biomegen.sites.kinds import tier_centre
from biomegen.sites.manifest import manifest_buildings, site_manifest
from biomegen.sites.potential import settlement_tier
from biomegen.world.entities import POI
from biomegen.world.manifest import SiteManifest
from biomegen.world.world import World
from tests.sites.conftest import add_poi, flat_world

TIERS = ("hamlet", "village", "town", "city", "capital")


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _poi(kind: str, pop: int, **fields: object) -> POI:
    return POI(kind=kind, x=5, y=5, interior_seed=3, civilized=True, pop=pop, **fields)  # type: ignore[arg-type]


def _pop_range(config: Config, tier: str) -> tuple[int, int]:
    return tier_pop_range(config, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_the_smallest_settlement_of_a_tier_has_the_fewest_houses(cfg: Config, tier: str) -> None:
    manifest = site_manifest(cfg, _poi(tier, _pop_range(cfg, tier)[0]))
    assert manifest is not None and manifest.houses == cfg.get(f"tables.sites.{tier}.houses")[0]


@pytest.mark.parametrize("tier", TIERS)
def test_the_largest_settlement_of_a_tier_has_the_most_houses(cfg: Config, tier: str) -> None:
    manifest = site_manifest(cfg, _poi(tier, _pop_range(cfg, tier)[1]))
    assert manifest is not None and manifest.houses == cfg.get(f"tables.sites.{tier}.houses")[1]


@pytest.mark.parametrize("tier", TIERS)
def test_a_settlement_has_the_specialized_slots_of_its_tier_and_population(cfg: Config, tier: str) -> None:
    low, high = cfg.get(f"tables.sites.{tier}.specialized")
    smallest = site_manifest(cfg, _poi(tier, _pop_range(cfg, tier)[0]))
    largest = site_manifest(cfg, _poi(tier, _pop_range(cfg, tier)[1]))
    assert (smallest.specialized, largest.specialized) == (low, high)  # type: ignore[union-attr]


def test_more_people_never_mean_fewer_houses(cfg: Config) -> None:
    low, high = _pop_range(cfg, "town")
    counts = [site_manifest(cfg, _poi("town", pop)).houses for pop in range(low, high + 1, 500)]  # type: ignore[union-attr]
    assert counts == sorted(counts)


def test_a_population_outside_the_tiers_range_is_held_to_its_ends(cfg: Config) -> None:
    manifest = site_manifest(cfg, _poi("village", 10**6))
    assert manifest is not None and manifest.houses == cfg.get("tables.sites.village.houses")[1]


def test_the_wall_stands_where_the_tiers_site_row_has_one(cfg: Config) -> None:
    walled = {tier: site_manifest(cfg, _poi(tier, 100)).walled for tier in TIERS}  # type: ignore[union-attr]
    assert walled == {"hamlet": False, "village": False, "town": False, "city": True, "capital": True}


def test_a_manifest_names_the_tier_that_stands(cfg: Config) -> None:
    assert site_manifest(cfg, _poi("town", 3000)).tier == "town"  # type: ignore[union-attr]


def test_a_settlement_that_was_never_a_homestead_has_no_origin(cfg: Config) -> None:
    assert site_manifest(cfg, _poi("town", 3000)).grown_from == ""  # type: ignore[union-attr]


def test_a_ruin_is_read_as_the_tier_it_was_at_its_peak(cfg: Config) -> None:
    ruin = POI(kind="ruin", x=1, y=1, interior_seed=1, ruin_of="city", pop=_pop_range(cfg, "city")[1])
    assert site_manifest(cfg, ruin) == SiteManifest("city", 18, 4, True)


@pytest.mark.parametrize("kind", ["tower", "camp", "homestead", "battlefield"])
def test_a_poi_with_no_settlement_plan_has_no_manifest(cfg: Config, kind: str) -> None:
    assert site_manifest(cfg, POI(kind=kind, x=1, y=1, interior_seed=1)) is None


def test_a_ruin_with_no_origin_is_no_settlement(cfg: Config) -> None:
    assert settlement_tier(cfg, POI(kind="ruin", x=1, y=1, interior_seed=1)) == ""


# --- what the manifest says stands --------------------------------------------------------------------------------


def _world_with(kind: str, pop: int) -> tuple[World, POI]:
    world = flat_world(20, 14)
    return world, add_poi(world, kind, 10, 7, civilized=True, pop=pop)


def test_the_centre_comes_first_in_the_buildings_a_manifest_lists(cfg: Config) -> None:
    world, poi = _world_with("village", 500)
    manifest = site_manifest(cfg, poi)
    assert manifest_buildings(world, cfg, poi, manifest)[0] == (tier_centre(cfg, "village"), 1)  # type: ignore[arg-type]


def test_the_houses_come_last_with_the_manifests_count(cfg: Config) -> None:
    world, poi = _world_with("village", 500)
    manifest = SiteManifest("village", 5, 0, False)
    assert manifest_buildings(world, cfg, poi, manifest)[-1] == ("house", 5)


def test_a_manifest_with_no_houses_lists_none(cfg: Config) -> None:
    world, poi = _world_with("village", 500)
    manifest = SiteManifest("village", 0, 0, False)
    assert manifest_buildings(world, cfg, poi, manifest) == [("chapel", 1)]


def test_a_manifest_lists_no_more_specialized_kinds_than_it_says_stand(cfg: Config) -> None:
    world, poi = _world_with("town", 3000)
    few = manifest_buildings(world, cfg, poi, SiteManifest("town", 0, 1, False))
    many = manifest_buildings(world, cfg, poi, SiteManifest("town", 0, 3, False))
    assert sum(count for _, count in few) <= sum(count for _, count in many)


def test_a_manifest_swaps_the_centre_with_its_tier(cfg: Config) -> None:
    world, poi = _world_with("village", 500)
    town = manifest_buildings(world, cfg, poi, SiteManifest("town", 5, 0, False))
    assert town[0] == ("hall", 1)


def test_every_generated_settlement_has_a_manifest_and_every_other_poi_none() -> None:
    config = load_config(None)
    world = pipeline.generate(config, 42)
    assert all((site_manifest(config, poi) is not None) == (bool(settlement_tier(config, poi))) for poi in world.pois)
