"""Tests for the history stage: dating realms and settlements, and the founding, settling and conquest events."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.entities import EVENT_KINDS
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _count(world: World, kind: str) -> int:
    return sum(1 for event in world.chronicle if event.kind == kind)


def test_the_present_is_the_span(world: World, cfg: Config) -> None:
    assert world.year == cfg.get("history.span_years")


def test_events_are_sorted_by_year_then_kind(world: World) -> None:
    # Within a year the kinds follow EVENT_KINDS, so a founding precedes everything else of its year.
    keys = [(event.year, EVENT_KINDS.index(event.kind)) for event in world.chronicle]
    assert keys == sorted(keys)


def test_event_ids_are_their_indexes(world: World) -> None:
    assert [event.id for event in world.chronicle] == list(range(len(world.chronicle)))


def test_events_fall_inside_the_span(world: World) -> None:
    assert all(0 <= event.year <= world.year for event in world.chronicle)


def test_every_realm_has_one_founding(world: World) -> None:
    founded = sorted(r for e in world.chronicle if e.kind == "founding" for r in e.realm_ids)
    assert founded == [realm.id for realm in world.realms]


def test_a_realms_first_event_is_its_founding(world: World) -> None:
    # Causality: nothing happens to a realm before it exists.
    assert all(world.events_of(realm.id)[0].kind == "founding" for realm in world.realms)


def test_founding_event_is_dated_by_the_realm(world: World) -> None:
    years = {e.realm_ids[0]: e.year for e in world.chronicle if e.kind == "founding"}
    assert all(years[realm.id] == realm.founded for realm in world.realms)


def test_a_capitals_founding_carries_the_capital_tag(world: World) -> None:
    founding = {e.realm_ids[0]: e for e in world.chronicle if e.kind == "founding"}
    seated = [r for r in world.realms if r.seat_poi >= 0 and world.pois[r.seat_poi].kind == "capital"]
    assert seated and all("capital" in founding[r.id].tags for r in seated)


def test_a_seat_is_as_old_as_its_realm(world: World) -> None:
    assert all(world.pois[r.seat_poi].founded == r.founded for r in world.realms if r.seat_poi >= 0)


def test_a_settlement_is_never_older_than_its_realm(world: World) -> None:
    pairs = [(p.founded, world.realms[p.realm_id].founded) for p in world.pois if p.civilized and p.realm_id >= 0]
    assert pairs and all(own >= realm for own, realm in pairs)


def test_settlements_are_founded_by_the_present(world: World) -> None:
    assert all(0 <= p.founded <= world.year for p in world.pois if p.civilized)


def test_wild_pois_stay_undated(world: World) -> None:
    assert all(p.founded == 0 for p in world.pois if not p.civilized)


def test_each_vassal_tie_is_one_conquest(world: World) -> None:
    assert _count(world, "conquest") == sum(1 for realm in world.realms if realm.liege >= 0)


def test_a_conquest_follows_both_foundings(world: World, cfg: Config) -> None:
    # The conquest comes at least min_gap_years after the later founding (or at the present, if that is later).
    gap = cfg.get("history.min_gap_years")
    for event in world.chronicle:
        if event.kind == "conquest":
            vassal, liege = (world.realms[i] for i in event.realm_ids)
            assert event.year >= min(max(vassal.founded, liege.founded) + gap, world.year)


def test_a_conquest_names_the_vassal_then_its_liege(world: World) -> None:
    events = [e for e in world.chronicle if e.kind == "conquest"]
    assert events and all(world.realms[e.realm_ids[0]].liege == e.realm_ids[1] for e in events)


def test_settling_events_are_for_the_configured_kinds_only(world: World) -> None:
    kinds = {world.pois[e.poi_ids[0]].kind for e in world.chronicle if e.kind == "settling"}
    assert kinds <= {"city"}


def test_a_realms_seat_has_no_settling_event(world: World) -> None:
    seats = {r.seat_poi for r in world.realms}
    assert all(e.poi_ids[0] not in seats for e in world.chronicle if e.kind == "settling")


def test_templates_come_from_the_table(world: World, cfg: Config) -> None:
    pool = {
        t
        for row in ("founding", "settling", "conquest")
        for key in ("templates", "templates_near")
        for t in cfg.get(f"tables.chronicle.{row}", {}).get(key, [])
    }
    assert all(e.template in pool for e in world.chronicle)


def test_a_near_template_needs_a_near_settlement(world: World, cfg: Config) -> None:
    near = {
        t
        for row in ("founding", "settling", "conquest")
        for t in cfg.get(f"tables.chronicle.{row}", {}).get("templates_near", [])
    }
    assert all(e.near_poi >= 0 for e in world.chronicle if e.template in near)


def test_a_near_settlement_is_close_and_on_the_same_landmass(world: World, cfg: Config) -> None:
    cap = cfg.get("history.near_km")
    for event in world.chronicle:
        if event.near_poi >= 0:
            x, y = event.location
            poi = world.pois[event.near_poi]
            assert world.scale.distance_km(x, y, poi.x, poi.y) <= cap
            assert world.landmass_id[y, x] == world.landmass_id[poi.y, poi.x]


def test_the_history_is_the_same_on_a_second_run(cfg: Config) -> None:
    # The same seed gives the same raw events.
    first, second = pipeline.generate(cfg, 42), pipeline.generate(cfg, 42)
    assert [(e.year, e.kind, e.template, e.realm_ids) for e in first.chronicle] == [
        (e.year, e.kind, e.template, e.realm_ids) for e in second.chronicle
    ]


def test_a_switched_off_kind_makes_no_events(cfg: Config) -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = ["founding"]
    world = pipeline.generate(config, 42)
    assert {e.kind for e in world.chronicle} == {"founding"}


def test_a_switched_off_kind_still_dates_the_realms(cfg: Config) -> None:
    # Dating does not depend on which events are derived.
    config = load_config(None)
    config.data["history"]["kinds"] = []
    world = pipeline.generate(config, 42)
    assert world.chronicle == [] and any(realm.founded > 0 for realm in world.realms)


def test_no_near_cap_means_no_near_settlements() -> None:
    config = load_config(None)
    config.data["history"]["near_km"] = 0.0
    world = pipeline.generate(config, 42)
    assert all(e.near_poi == -1 for e in world.chronicle)
