"""Tests for the population of a realm: its places, plus the people living outside them."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.config.population import pop_scale, scaled_people
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=(42, 7))
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _settled(world: World, realm_id: int) -> int:
    return sum(p.pop for p in world.pois if (p.civilized or p.kind == "homestead") and p.realm_id == realm_id)


def test_a_realm_holds_at_least_the_people_in_its_places(world: World) -> None:
    assert all(realm.pop >= _settled(world, realm.id) for realm in world.realms)


def test_a_realm_has_no_more_than_its_places_plus_the_outside_terms(world: World, cfg: Config) -> None:
    for realm in world.realms:
        row = cfg.get(f"tables.realm_kinds.{realm.kind}")
        rural = row["rural_per_km2"][1] * pop_scale(cfg)
        most = _settled(world, realm.id) * (1 + row["outside_share"][1]) + realm.area_km2 * rural
        assert realm.pop <= most + 1


def test_a_realm_is_not_millions_with_a_town_for_a_capital(world: World) -> None:
    # The old area-times-density sum gave a realm of 150,000 in its capital four million people.
    for realm in world.realms:
        assert realm.pop <= 8 * max(1, _settled(world, realm.id)) + realm.area_km2 * 0.2


def test_every_homestead_has_a_household(world: World, cfg: Config) -> None:
    low, high = (scaled_people(cfg, v) for v in cfg.get("poi.homestead_people"))
    homesteads = [p for p in world.pois if p.kind == "homestead"]
    assert homesteads and all(low <= p.pop <= high for p in homesteads)


def test_realms_have_their_own_jitter(world: World) -> None:
    ratios = {round(r.pop / max(1, _settled(world, r.id)), 2) for r in world.realms if _settled(world, r.id)}
    assert len(ratios) > 3


def test_the_population_is_the_same_on_every_run(cfg: Config) -> None:
    first, second = pipeline.generate(cfg, 7), pipeline.generate(cfg, 7)
    assert [r.pop for r in first.realms] == [r.pop for r in second.realms]
