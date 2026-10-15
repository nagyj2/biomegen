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


# --- watchtowers -------------------------------------------------------------------------------------


def _towers(world: World) -> list[POI]:
    return [p for p in world.pois if p.kind == "watchtower"]


def test_every_watchtower_stands_for_an_ongoing_war(world: World) -> None:
    for tower in _towers(world):
        event = world.chronicle[tower.event_ids[0]]
        assert event.kind == "war" and "ongoing" in event.tags


def test_a_war_gets_at_most_the_rows_cap_of_towers(world: World, cfg: Config) -> None:
    cap = cfg.get("tables.pois.watchtower.max_per_event")
    per_war: dict[int, int] = {}
    for tower in _towers(world):
        per_war[tower.event_ids[0]] = per_war.get(tower.event_ids[0], 0) + 1
    assert all(count <= cap for count in per_war.values())


def test_a_watchtower_stands_on_its_wars_front(world: World) -> None:
    from biomegen.pipeline.civilization.diplomacy import front_cells

    for tower in _towers(world):
        cells = front_cells(world, *world.chronicle[tower.event_ids[0]].realm_ids)
        assert tower.y * world.width + tower.x in set(cells.tolist())


def test_a_watchtower_belongs_to_a_realm_of_its_war(world: World) -> None:
    for tower in _towers(world):
        powers = set(world.chronicle[tower.event_ids[0]].realm_ids)
        assert tower.realm_id >= 0 and world.top_realm(tower.realm_id) in powers


def test_a_watchtower_is_newer_than_its_lifespan_and_its_war(world: World, cfg: Config) -> None:
    lifespan = cfg.get("tables.pois.watchtower.lifespan")
    for tower in _towers(world):
        assert max(world.chronicle[tower.event_ids[0]].year, world.year - lifespan) <= tower.founded <= world.year


def test_watchtowers_of_one_war_keep_their_spacing(world: World, cfg: Config) -> None:
    spacing = cfg.get("tables.pois.watchtower.kind_spacing_km")
    towers = _towers(world)
    for i, tower in enumerate(towers):
        assert all(world.scale.distance_km(tower.x, tower.y, q.x, q.y) >= spacing - 1e-6 for q in towers[:i])


def test_a_watchtower_keeps_its_spacing_from_the_pois_before_it(world: World, cfg: Config) -> None:
    spacing = cfg.get("tables.pois.watchtower.min_spacing_km")
    for index, p in enumerate(world.pois):
        if p.kind == "watchtower":
            assert all(world.scale.distance_km(p.x, p.y, q.x, q.y) >= spacing - 1e-6 for q in world.pois[:index])


def test_watchtowers_are_dynamic_and_stand(cfg: Config) -> None:
    # The row marks them dynamic with a lifespan for the simulation; generation never dismantles one.
    assert cfg.get("tables.pois.watchtower.dynamic") is True and cfg.get("tables.pois.watchtower.lifespan") > 0


def test_no_watchtower_has_fallen(world: World) -> None:
    assert all(tower.fell is None for tower in _towers(world))


# --- shrines -----------------------------------------------------------------------------------------


@pytest.fixture(scope="module", params=SEEDS)
def shrines(request: pytest.FixtureRequest) -> World:
    """A world with many successions, so shrines of both sites are there to check."""
    config = load_config(None)
    config.data["history"].update(succession_years=[60, 120], succession_change_chance=1.0)
    return pipeline.generate(config, request.param)


def _shrines(world: World) -> list[POI]:
    return [p for p in world.pois if p.kind == "shrine"]


def _site_of(world: World, shrine: POI, cfg: Config) -> dict:
    """The poi_sites row the previous ruler's temper gave the shrine's succession."""
    event = world.chronicle[shrine.event_ids[0]]
    previous = next(tag.partition(":")[2] for tag in event.tags if tag.startswith("from:"))
    temper = cfg.get(f"tables.ruling_styles.{previous}.temper")
    return next(
        row for row in cfg.get("tables.poi_sites").values() if row["kind"] == "shrine" and row["temper"] == temper
    )


def test_a_shrine_stands_for_a_succession_into_a_devout_style(shrines: World) -> None:
    assert _shrines(shrines) and all(
        shrines.chronicle[s.event_ids[0]].kind == "succession" and "to:pious" in shrines.chronicle[s.event_ids[0]].tags
        for s in _shrines(shrines)
    )


def test_at_most_one_shrine_per_devout_succession(shrines: World) -> None:
    events = [s.event_ids[0] for s in _shrines(shrines)]
    assert len(events) == len(set(events))


def test_a_shrine_lies_in_its_sites_band_from_the_seat(shrines: World, cfg: Config) -> None:
    for shrine in _shrines(shrines):
        site = _site_of(shrines, shrine, cfg)
        realm = shrines.realms[shrines.chronicle[shrine.event_ids[0]].realm_ids[0]]
        seat = shrines.pois[realm.seat_poi]
        assert site["min_km"] <= shrines.scale.distance_km(shrine.x, shrine.y, seat.x, seat.y) <= site["max_km"]


def test_a_quiet_spot_shrine_lies_in_the_realm_that_built_it(shrines: World, cfg: Config) -> None:
    for shrine in _shrines(shrines):
        if _site_of(shrines, shrine, cfg)["land"] == "realm":
            assert shrine.realm_id == shrines.chronicle[shrine.event_ids[0]].realm_ids[0]


def test_both_shrine_sites_are_used(shrines: World, cfg: Config) -> None:
    assert {_site_of(shrines, s, cfg)["temper"] for s in _shrines(shrines)} == {"aggressive", "passive"}


def test_a_shrine_takes_its_connect_flag_from_its_site(shrines: World, cfg: Config) -> None:
    assert all(s.connect == _site_of(shrines, s, cfg)["connect"] for s in _shrines(shrines))


def test_a_shrine_is_dated_by_its_succession(shrines: World) -> None:
    assert all(s.founded == shrines.chronicle[s.event_ids[0]].year for s in _shrines(shrines))


def test_a_shrine_keeps_its_spacing_from_the_pois_before_it(shrines: World, cfg: Config) -> None:
    spacing = cfg.get("tables.pois.shrine.min_spacing_km")
    for index, p in enumerate(shrines.pois):
        if p.kind == "shrine":
            assert all(shrines.scale.distance_km(p.x, p.y, q.x, q.y) >= spacing - 1e-6 for q in shrines.pois[:index])
