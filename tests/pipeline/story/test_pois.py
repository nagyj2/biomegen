"""Tests for the pois stage's history placement: the ruins a fallen realm leaves."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.entities import POI
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _fall_ruins(world: World, fallen_id: int) -> list[POI]:
    """The ruins whose first event is the fall of fallen realm ``fallen_id``."""
    return [
        poi
        for poi in world.pois
        if poi.kind == "ruin" and poi.event_ids and world.chronicle[poi.event_ids[0]].fallen_ids == [fallen_id]
    ]


def test_every_fallen_realm_leaves_its_capital_ruin_on_its_site(world: World) -> None:
    for fallen in world.fallen_realms:
        assert any((poi.x, poi.y) == fallen.location for poi in _fall_ruins(world, fallen.id))


def test_a_fallen_realm_leaves_one_to_three_ruins(world: World) -> None:
    # The capital plus the row's [0, 2] holdings (a holding can fail to find room, never the capital).
    assert all(1 <= len(_fall_ruins(world, fallen.id)) <= 3 for fallen in world.fallen_realms)


def test_a_ruin_carries_the_fall_event_of_its_realm(world: World) -> None:
    for fallen in world.fallen_realms:
        for poi in _fall_ruins(world, fallen.id):
            assert world.chronicle[poi.event_ids[0]].kind == "fall"


def test_a_ruin_is_dated_by_its_fallen_realm(world: World) -> None:
    for fallen in world.fallen_realms:
        assert all((p.founded, p.fell) == (fallen.founded, fallen.fell) for p in _fall_ruins(world, fallen.id))


def test_holdings_lie_in_the_band_round_the_capital_ruin(world: World, cfg: Config) -> None:
    low, high = cfg.get("tables.pois.ruin.holding_km")
    for fallen in world.fallen_realms:
        for poi in _fall_ruins(world, fallen.id):
            if (poi.x, poi.y) != fallen.location:
                assert low <= world.scale.distance_km(*fallen.location, poi.x, poi.y) <= high


def test_holdings_are_on_the_landmass_of_the_capital_ruin(world: World) -> None:
    for fallen in world.fallen_realms:
        landmass = world.landmass_id[fallen.location[1], fallen.location[0]]
        assert all(world.landmass_id[p.y, p.x] == landmass for p in _fall_ruins(world, fallen.id))


def test_a_holding_keeps_its_spacing_from_every_other_poi(world: World, cfg: Config) -> None:
    spacing = cfg.get("tables.pois.ruin.holding_spacing_km")
    for fallen in world.fallen_realms:
        for poi in _fall_ruins(world, fallen.id):
            if (poi.x, poi.y) != fallen.location:
                others = [q for q in world.pois if q is not poi and q.event_ids != poi.event_ids]
                assert all(world.scale.distance_km(poi.x, poi.y, q.x, q.y) >= spacing - 1e-6 for q in others)


def test_only_a_bandit_ruin_holds_bandits(world: World, cfg: Config) -> None:
    strength = cfg.get("tables.pois.ruin.bandit_strength")
    assert all(p.bandit_strength in (0, strength) for p in world.pois if p.kind == "ruin")


def test_some_ruins_are_bandit_held_across_the_seeds(cfg: Config) -> None:
    held = sum(1 for seed in (42, 7, 1337, 9999) for p in pipeline.generate(cfg, seed).pois if p.bandit_strength > 0)
    assert held > 0


def test_ruins_from_a_fall_are_not_in_the_location_pass(world: World) -> None:
    # A POI without events is a location ruin; a fall ruin always has its event, so the two never mix.
    assert all(bool(p.event_ids) == (p.fell is not None) for p in world.pois if p.kind == "ruin")


def test_no_two_pois_share_a_cell(world: World) -> None:
    assert len({(p.x, p.y) for p in world.pois}) == len(world.pois)


def test_the_pois_stage_is_deterministic(cfg: Config) -> None:
    first, second = pipeline.generate(cfg, 42), pipeline.generate(cfg, 42)
    assert [(p.kind, p.x, p.y, p.bandit_strength, p.event_ids) for p in first.pois] == [
        (p.kind, p.x, p.y, p.bandit_strength, p.event_ids) for p in second.pois
    ]


# --- battlefields ------------------------------------------------------------------------------------


@pytest.fixture(scope="module", params=SEEDS)
def fields(request: pytest.FixtureRequest) -> World:
    """A world with many old, decisive battles that always leave a field, so the rule's results are there to check."""
    config = load_config(None)
    config.data["history"].update(past_war_chance=0.8, fallen_wars=[2, 4], fall_strength=0.9)
    config.data["tables"]["pois"]["battlefield"]["chance"] = 1.0
    config.data["tables"]["pois"]["battlefield"]["kind_spacing_km"] = 120.0
    return pipeline.generate(config, request.param)


def _battlefields(world: World) -> list[POI]:
    return [p for p in world.pois if p.kind == "battlefield"]


def test_a_battlefield_stands_for_a_decisive_battle(fields: World) -> None:
    assert _battlefields(fields) and all(
        "decisive" in fields.chronicle[p.event_ids[0]].tags and fields.chronicle[p.event_ids[0]].kind == "battle"
        for p in _battlefields(fields)
    )


def test_a_battlefield_is_at_least_thirty_years_old(fields: World, cfg: Config) -> None:
    age = cfg.get("tables.pois.battlefield.min_age_years")
    assert all(fields.year - fields.chronicle[p.event_ids[0]].year >= age for p in _battlefields(fields))


def test_a_battlefield_is_dated_by_its_battle(fields: World) -> None:
    assert all(p.founded == fields.chronicle[p.event_ids[0]].year for p in _battlefields(fields))


def test_a_battlefield_lies_within_the_offset_of_its_battle(fields: World, cfg: Config) -> None:
    reach = cfg.get("tables.pois.battlefield.offset_km")
    for p in _battlefields(fields):
        assert fields.scale.distance_km(p.x, p.y, *fields.chronicle[p.event_ids[0]].location) <= reach + 1e-6


def test_battlefields_keep_their_distance_from_each_other(fields: World) -> None:
    # Placed with kind_spacing_km 120 in this fixture's config.
    fields_ = _battlefields(fields)
    for i, p in enumerate(fields_):
        assert all(fields.scale.distance_km(p.x, p.y, q.x, q.y) >= 120.0 - 1e-6 for q in fields_[:i])


def test_a_battlefield_keeps_its_spacing_from_the_pois_before_it(fields: World, cfg: Config) -> None:
    spacing = cfg.get("tables.pois.battlefield.min_spacing_km")
    for index, p in enumerate(fields.pois):
        if p.kind == "battlefield":
            assert all(fields.scale.distance_km(p.x, p.y, q.x, q.y) >= spacing - 1e-6 for q in fields.pois[:index])


def test_a_battlefield_stands_on_dry_land(fields: World) -> None:
    from biomegen.world.tile import WaterType

    assert all(fields.water_type[p.y, p.x] == int(WaterType.NONE) for p in _battlefields(fields))


def test_the_default_chance_leaves_fewer_fields_than_decisive_battles(world: World) -> None:
    decisive = [e for e in world.chronicle if e.kind == "battle" and "decisive" in e.tags]
    assert len(_battlefields(world)) <= len(decisive)
