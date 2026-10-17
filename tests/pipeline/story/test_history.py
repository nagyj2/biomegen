"""Tests for the history stage: dating realms and settlements, fallen realms, and founding, settling and conquest."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.civilization.settlements import habitability
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
    keys = [(event.year, EVENT_KINDS.index(event.kind)) for event in world.chronicle if event.salience == "major"]
    assert keys == sorted(keys)


def test_event_ids_are_their_indexes(world: World) -> None:
    assert [event.id for event in world.chronicle] == list(range(len(world.chronicle)))


def test_every_event_has_a_month_in_range(world: World, cfg: Config) -> None:
    months = cfg.get("history.months_per_year")
    assert all(1 <= event.month <= months for event in world.chronicle)


def test_months_never_go_backwards_within_a_year(world: World) -> None:
    # Months are dealt out in event order, so an event never precedes an earlier one of its year.
    keys = [(event.year, event.month) for event in world.chronicle]
    assert keys == sorted(keys)


def test_events_fall_inside_the_span(world: World) -> None:
    assert all(0 <= event.year <= world.year for event in world.chronicle)


def test_the_oldest_realm_is_founded_in_the_first_year(world: World, cfg: Config) -> None:
    # Foundings are shifted so the history starts around year 0, not somewhere in the middle of the span.
    assert min(realm.founded for realm in world.realms) == cfg.get("history.first_founding_year")


def test_no_event_comes_before_the_first_year(world: World, cfg: Config) -> None:
    major = [event.year for event in world.chronicle if event.salience == "major"]  # a minor one may be year 0
    assert min(major) >= cfg.get("history.first_founding_year")


def _beginnings(world: World) -> dict[int, object]:
    """Each realm's beginning: its founding event, or the secession that made it (the first listing the realm)."""
    beginnings: dict[int, object] = {}
    for e in world.chronicle:
        if e.kind == "founding" and e.realm_ids:
            beginnings[e.realm_ids[0]] = e
        elif e.kind == "secession" and "split" in e.tags:  # a split begins both its realms
            beginnings.update({realm_id: e for realm_id in e.realm_ids})
        elif e.kind == "secession":  # an offshoot begins the first realm it names
            beginnings[e.realm_ids[0]] = e
    return beginnings


def test_every_realm_has_one_founding_or_secession(world: World) -> None:
    founded = sorted(r for e in world.chronicle if e.kind == "founding" for r in e.realm_ids)
    seceded = sorted(realm.id for realm in world.realms if realm.origin)
    assert sorted(founded + seceded) == [realm.id for realm in world.realms]


def test_a_realms_first_event_is_its_founding_or_secession(world: World) -> None:
    # Causality: nothing happens to a realm before it exists.
    assert all(world.events_of(realm.id)[0].kind in ("founding", "secession") for realm in world.realms)


def test_founding_event_is_dated_by_the_realm(world: World) -> None:
    beginnings = _beginnings(world)
    assert all(beginnings[realm.id].year == realm.founded for realm in world.realms)  # type: ignore[attr-defined]


def test_a_capitals_founding_carries_the_capital_tag(world: World) -> None:
    beginnings = _beginnings(world)
    seated = [r for r in world.realms if r.seat_poi >= 0 and world.pois[r.seat_poi].kind == "capital"]
    assert seated and all("capital" in beginnings[r.id].tags for r in seated)  # type: ignore[attr-defined]


def test_a_seat_is_as_old_as_its_realm(world: World) -> None:
    # An offshoot's seat stood under its parent before the break, so it may be older.
    assert all(
        world.pois[r.seat_poi].founded == r.founded or (r.origin and world.pois[r.seat_poi].founded < r.founded)
        for r in world.realms
        if r.seat_poi >= 0
    )


def test_a_settlement_is_never_older_than_its_realm(world: World) -> None:
    # An offshoot's seat stood under its parent before the break, so it may be older (as the seat test above allows).
    seats = {r.seat_poi for r in world.realms if r.origin}
    pairs = [
        (p.founded, world.realms[p.realm_id].founded)
        for i, p in enumerate(world.pois)
        if p.civilized and p.realm_id >= 0 and i not in seats
    ]
    assert pairs and all(own >= realm for own, realm in pairs)


def test_settlements_are_founded_by_the_present(world: World) -> None:
    assert all(0 <= p.founded <= world.year for p in world.pois if p.civilized)


def test_wild_pois_placed_by_location_stay_undated(world: World) -> None:
    # Only a POI an event made (a fallen realm's ruin) takes a date; the rest of the wild ones have none (a homestead
    # is dated by the styles pass).
    assert all(p.founded == 0 for p in world.pois if not p.civilized and not p.event_ids and not p.style)


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


def test_settling_events_are_for_the_configured_kinds_only(world: World, cfg: Config) -> None:
    kinds = {world.pois[e.poi_ids[0]].kind for e in world.chronicle if e.kind == "settling" and e.salience == "major"}
    assert kinds <= set(cfg.get("history.settle_kinds"))


def test_a_realms_seat_has_no_settling_event(world: World) -> None:
    seats = {r.seat_poi for r in world.realms}
    assert all(e.poi_ids[0] not in seats for e in world.chronicle if e.kind == "settling")


def test_templates_come_from_the_table(world: World, cfg: Config) -> None:
    pool = {
        t
        for row in cfg.get("tables.chronicle")
        for key in ("templates", "templates_near")
        for t in cfg.get(f"tables.chronicle.{row}").get(key, [])
    }
    assert all(e.template in pool for e in world.chronicle)


def test_a_near_template_needs_a_near_settlement(world: World, cfg: Config) -> None:
    near = {
        t for row in cfg.get("tables.chronicle") for t in cfg.get(f"tables.chronicle.{row}").get("templates_near", [])
    }
    assert all(e.near_poi >= 0 for e in world.chronicle if e.template in near)


def test_a_near_settlement_is_close_and_on_the_same_landmass(world: World, cfg: Config) -> None:
    cap = cfg.get("history.near_km")
    located = [e for e in world.chronicle if e.near_poi >= 0]
    assert located
    for event in located:
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


def test_a_switched_off_kind_makes_no_events() -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = ["founding"]
    world = pipeline.generate(config, 42)
    assert {e.kind for e in world.chronicle} == {"founding"}


def test_a_switched_off_kind_still_dates_the_realms() -> None:
    # Dating does not depend on which events are derived.
    config = load_config(None)
    config.data["history"]["kinds"] = []
    world = pipeline.generate(config, 42)
    assert world.chronicle == [] and any(realm.founded > 0 for realm in world.realms)


def test_a_zero_near_cap_names_only_a_settlement_on_the_same_cell() -> None:
    config = load_config(None)
    config.data["history"]["near_km"] = 0.0
    world = pipeline.generate(config, 42)
    assert all(
        world.scale.distance_km(*e.location, world.pois[e.near_poi].x, world.pois[e.near_poi].y) == 0
        for e in world.chronicle
        if e.near_poi >= 0
    )


# --- fallen realms ----------------------------------------------------------------------------------


def test_fallen_realm_ids_are_their_indexes(world: World) -> None:
    assert world.fallen_realms and [f.id for f in world.fallen_realms] == list(range(len(world.fallen_realms)))


def test_every_fallen_realm_has_one_founding(world: World) -> None:
    founded = sorted(f for e in world.chronicle if e.kind == "founding" for f in e.fallen_ids)
    assert founded == [fallen.id for fallen in world.fallen_realms]


def test_a_fallen_realms_founding_is_dated_by_the_realm(world: World) -> None:
    years = {e.fallen_ids[0]: e.year for e in world.chronicle if e.kind == "founding" and e.fallen_ids}
    assert all(years[f.id] == f.founded for f in world.fallen_realms)


def test_a_fallen_realms_first_event_is_its_founding(world: World) -> None:
    firsts = {}
    for event in world.chronicle:
        for fallen_id in event.fallen_ids:
            firsts.setdefault(fallen_id, event.kind)
    assert firsts and set(firsts.values()) == {"founding"}


def test_a_fallen_realm_lived_before_it_fell(world: World, cfg: Config) -> None:
    # Founded no earlier than the first year, fallen at or after its founding and before the present.
    first, last = cfg.get("history.first_founding_year"), world.year - cfg.get("history.fallen_min_years_ago")
    assert all(first <= f.founded <= f.fell <= last for f in world.fallen_realms)


def test_every_fallen_realm_has_one_fall(world: World) -> None:
    falls = sorted(f for e in world.chronicle if e.kind == "fall" for f in e.fallen_ids)
    assert falls == [fallen.id for fallen in world.fallen_realms]


def test_a_fall_is_dated_when_the_realm_fell(world: World) -> None:
    assert all(e.year == world.fallen_realms[e.fallen_ids[0]].fell for e in world.chronicle if e.kind == "fall")


def test_ruins_lie_on_wild_land(world: World) -> None:
    sites = [f.location for f in world.fallen_realms]
    assert all(world.realm_id[y, x] == -1 and world.landmass_id[y, x] >= 0 for x, y in sites)


def test_ruins_lie_on_habitable_land(world: World, cfg: Config) -> None:
    score = habitability(world, cfg, world.seed)
    floor = cfg.get("history.fall_min_habitability")
    assert all(score[y, x] >= floor for x, y in (f.location for f in world.fallen_realms))


def test_ruins_keep_their_distance_from_settlements(world: World, cfg: Config) -> None:
    spacing = cfg.get("history.fall_spacing_km")
    settled = [p for p in world.pois if p.civilized and not p.style]  # the styles pass places its hamlets later
    nearest = [min(world.scale.distance_km(*f.location, p.x, p.y) for p in settled) for f in world.fallen_realms]
    assert nearest and min(nearest) >= spacing


def test_ruins_keep_their_distance_from_each_other(world: World, cfg: Config) -> None:
    spacing = cfg.get("history.fall_spacing_km")
    sites = [f.location for f in world.fallen_realms]
    gaps = [world.scale.distance_km(*a, *b) for i, a in enumerate(sites) for b in sites[i + 1 :]]
    assert gaps and min(gaps) >= spacing


def test_a_fall_knows_where_the_ruins_are(world: World) -> None:
    falls = [e for e in world.chronicle if e.kind == "fall"]
    assert all(e.location == world.fallen_realms[e.fallen_ids[0]].location for e in falls)


def test_no_fall_kind_means_no_fallen_realms() -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = ["founding"]
    assert pipeline.generate(config, 42).fallen_realms == []


def test_no_fallen_realms_at_rate_zero() -> None:
    config = load_config(None)
    config.data["history"]["fallen_realms_per_million_km2"] = 0.0
    assert pipeline.generate(config, 42).fallen_realms == []


def test_a_seat_is_marked_by_its_realms_founding(world: World) -> None:
    # Or by the secession that began the realm.
    for realm in world.realms:
        if realm.seat_poi >= 0:
            kind = world.chronicle[world.pois[realm.seat_poi].event_ids[0]].kind
            assert kind == ("secession" if realm.origin else "founding")


def test_a_settlement_is_marked_by_the_event_that_settled_it(world: World) -> None:
    settled = [e for e in world.chronicle if e.kind == "settling"]
    assert settled and all(e.id in world.pois[e.poi_ids[0]].event_ids for e in settled)


# --- a conquest is won in a war -----------------------------------------------------------------------------------


def _vassal_ties(world: World):
    return [(realm.id, realm.liege) for realm in world.realms if realm.liege >= 0]


def _events(world: World, kind: str, vassal: int, liege: int):
    return [e for e in world.chronicle if e.kind == kind and set(e.realm_ids) == {vassal, liege}]


def test_every_conquest_has_a_war_before_it(world: World) -> None:
    # A realm is never taken in peacetime: the overlord's war on it opens before the conquest.
    for vassal, liege in _vassal_ties(world):
        (conquest,) = _events(world, "conquest", vassal, liege)
        wars = [e for e in _events(world, "war", vassal, liege) if "conquest" in e.tags]
        assert len(wars) == 1 and (wars[0].year, wars[0].month) < (conquest.year, conquest.month)


def test_the_overlord_attacks_in_a_conquest_war(world: World) -> None:
    for vassal, liege in _vassal_ties(world):
        war = next(e for e in _events(world, "war", vassal, liege) if "conquest" in e.tags)
        assert war.realm_ids == [liege, vassal]


def test_a_conquest_war_is_fought_between_its_war_and_its_conquest(world: World) -> None:
    for vassal, liege in _vassal_ties(world):
        war = next(e for e in _events(world, "war", vassal, liege) if "conquest" in e.tags)
        (conquest,) = _events(world, "conquest", vassal, liege)
        for battle in _events(world, "battle", vassal, liege):
            assert (war.year, war.month) <= (battle.year, battle.month) < (conquest.year, conquest.month)


def test_the_overlord_wins_the_battle_of_its_conquest_war(world: World) -> None:
    for vassal, liege in _vassal_ties(world):
        for battle in _events(world, "battle", vassal, liege):
            assert battle.realm_ids[0] == liege and "decisive" in battle.tags


def test_every_event_tick_is_its_absolute_month(world: World, cfg: Config) -> None:
    # The tick is the year and month flattened to one number, the same count a simulation's clock keeps.
    months = cfg.get("history.months_per_year")
    assert all(event.tick == event.year * months + event.month - 1 for event in world.chronicle)


def test_every_generated_event_is_derived(world: World) -> None:
    # The history and the annals are derived from the present state; only a simulation emits events that are not.
    assert all(event.derived for event in world.chronicle)
