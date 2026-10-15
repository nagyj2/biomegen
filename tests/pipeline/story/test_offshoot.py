"""Tests for offshoots: a realm that left an older one, planned from the finished map and checked on the timeline."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story import conflicts, secession
from biomegen.pipeline.story.ledger import Ledger
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, Realm
from biomegen.world.world import World

SEEDS = (42, 7)


def _eager() -> Config:
    """Defaults where every candidate offshoot happens (chance 1, no cap), so each world has several."""
    config = load_config(None)
    config.data["history"]["secession"].update(chance=1.0, max_per_world=99)
    return config


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest) -> World:
    return pipeline.generate(_eager(), request.param)


def _offshoots(world: World) -> list[Realm]:
    return [r for r in world.realms if r.origin == "offshoot"]


def _secession(world: World, realm_id: int):
    return next(e for e in world.chronicle if e.kind == "secession" and e.realm_ids[0] == realm_id)


# --- generated worlds ------------------------------------------------------------------------------------------------


def test_an_eager_world_has_offshoots(world: World) -> None:
    assert _offshoots(world)


def test_an_offshoots_parent_is_an_older_living_major_realm(world: World) -> None:
    gap = int(load_config(None).get("history.min_gap_years"))
    for realm in _offshoots(world):
        parent = world.realms[realm.parent]
        assert parent.kind == "major" and parent.founded + gap <= realm.founded


def test_a_tribe_never_breaks_away(world: World) -> None:
    assert not [r for r in world.realms if r.kind == "tribal" and r.origin]


def test_an_offshoot_begins_with_its_secession_not_a_founding(world: World) -> None:
    for realm in _offshoots(world):
        events = world.events_of(realm.id)
        assert events[0].kind == "secession" and not [e for e in events if e.kind == "founding"]


def test_a_secession_is_dated_by_the_realm_and_names_both_sides(world: World) -> None:
    for realm in _offshoots(world):
        event = _secession(world, realm.id)
        assert event.year == realm.founded and event.realm_ids == [realm.id, realm.parent]


def test_a_secession_text_names_both_realms_and_the_new_ruler(world: World) -> None:
    for realm in _offshoots(world):
        text = _secession(world, realm.id).text.lower()
        assert realm.name.lower() in text or realm.short.lower() in text
        assert world.realms[realm.parent].name.lower() in text or world.realms[realm.parent].short.lower() in text


def test_a_secession_is_worded_by_the_relation_between_the_sides(world: World) -> None:
    config = load_config(None)
    for realm in _offshoots(world):
        tag = secession.relation_tag(world, config, world.realms[realm.parent], realm)
        assert tag in _secession(world, realm.id).tags


def test_an_offshoots_seat_stood_before_the_break(world: World) -> None:
    for realm in _offshoots(world):
        if realm.seat_poi >= 0:
            assert world.pois[realm.seat_poi].founded <= realm.founded


def test_an_offshoots_seat_is_marked_by_the_secession(world: World) -> None:
    for realm in _offshoots(world):
        if realm.seat_poi >= 0:
            assert _secession(world, realm.id).id in world.pois[realm.seat_poi].event_ids


def test_an_offshoots_seat_takes_the_secession_text_as_its_hook(world: World) -> None:
    for realm in _offshoots(world):
        if realm.seat_poi >= 0:
            assert world.pois[realm.seat_poi].hook == _secession(world, realm.id).text


def test_the_parent_keeps_its_name_ruler_and_origin(world: World) -> None:
    for realm in _offshoots(world):
        parent = world.realms[realm.parent]
        assert parent.name and parent.ruler and parent.origin != "split"


def test_a_realm_that_left_nobody_has_no_parent(world: World) -> None:
    assert all(r.parent == -1 for r in world.realms if r.origin != "offshoot")


def test_the_partition_is_untouched_by_secession(world: World) -> None:
    plain = pipeline.generate(load_config(None), world.seed)
    assert world.fingerprint() == plain.fingerprint()


def test_the_world_is_deterministic() -> None:
    first, second = pipeline.generate(_eager(), 42), pipeline.generate(_eager(), 42)
    assert [(r.origin, r.parent) for r in first.realms] == [(r.origin, r.parent) for r in second.realms]


def test_the_cap_limits_the_secessions_of_a_world() -> None:
    config = _eager()
    config.data["history"]["secession"]["max_per_world"] = 1
    assert len([r for r in pipeline.generate(config, 42).realms if r.origin]) <= 1


def test_no_chance_means_no_secession() -> None:
    config = _eager()
    config.data["history"]["secession"]["chance"] = 0.0
    made = pipeline.generate(config, 42)
    assert not [r for r in made.realms if r.origin] and not [e for e in made.chronicle if e.kind == "secession"]


def test_a_switched_off_secession_kind_leaves_every_realm_founded() -> None:
    config = _eager()
    config.data["history"]["kinds"] = [k for k in config.data["history"]["kinds"] if k != "secession"]
    made = pipeline.generate(config, 42)
    assert not [r for r in made.realms if r.origin]
    assert len([e for e in made.chronicle if e.kind == "founding" and e.realm_ids]) == len(made.realms)


def test_the_default_chance_makes_secession_rare() -> None:
    made = pipeline.generate(load_config(None), 42)
    assert len([r for r in made.realms if r.origin]) <= len(made.realms) // 3


# --- the planning and the check --------------------------------------------------------------------------------------


def _tiny() -> World:
    world = World(20, 6, 1, grid_scale(20, 6, (2000.0, 600.0), 30.0, 0.0))
    world.pois = [
        POI(kind="capital", x=2, y=3, interior_seed=1, civilized=True),
        POI(kind="capital", x=6, y=3, interior_seed=2, civilized=True),
    ]
    world.realms = [
        Realm(id=0, kind="major", seat_poi=0, area_km2=900_000.0, pop=1_000_000, founded=10),
        Realm(id=1, kind="major", seat_poi=1, area_km2=300_000.0, pop=500_000, founded=400),
        Realm(id=2, kind="tribal", area_km2=100_000.0, pop=50_000, founded=500),
    ]
    return world


def test_the_oldest_realm_has_no_parent_to_plan() -> None:
    assert 0 not in secession.plan_offshoots(_tiny(), _eager(), 1)


def test_a_candidate_is_planned_under_an_older_major_realm() -> None:
    assert secession.plan_offshoots(_tiny(), _eager(), 1) == {1: 0}


def test_a_tribe_is_never_planned() -> None:
    assert 2 not in secession.plan_offshoots(_tiny(), _eager(), 1)


def test_nothing_is_planned_at_chance_zero() -> None:
    config = _eager()
    config.data["history"]["secession"]["chance"] = 0.0
    assert secession.plan_offshoots(_tiny(), config, 1) == {}


def _check(chance: float, seed: int = 1) -> tuple[World, list]:
    config = _eager()
    config.data["history"]["secession"]["chance"] = chance
    world = _tiny()
    ledger = Ledger(config)
    conflicts.derive(world, config, seed, 1200, ledger, None, {1: 0})
    return world, ledger.finish()


def _kinds_of_realm_one(events: list) -> list[str]:
    return [e.kind for e in events if e.realm_ids[:1] == [1]]


def test_a_check_makes_the_secession_for_some_seeds() -> None:
    # The roll is a draw against chance x score: over many seeds some realm leaves and some founding stands.
    outcomes = {tuple(_kinds_of_realm_one(_check(1.0, seed)[1])) for seed in range(40)}
    assert outcomes == {("secession",), ("founding",)}


def test_a_secession_sets_the_realms_origin_and_parent() -> None:
    for seed in range(40):
        made, events = _check(1.0, seed)
        if _kinds_of_realm_one(events) == ["secession"]:
            assert (made.realms[1].origin, made.realms[1].parent) == ("offshoot", 0)
            return
    pytest.fail("no seed made the secession")


def test_a_failed_check_gives_the_ordinary_founding() -> None:
    for seed in range(20):
        made, events = _check(1e-9, seed)
        assert made.realms[1].origin == "" and _kinds_of_realm_one(events) == ["founding"]


def test_every_planned_realm_gets_exactly_one_beginning() -> None:
    for seed in range(20):
        _made, events = _check(0.5, seed)
        assert len(_kinds_of_realm_one(events)) == 1


def test_a_weaker_parent_makes_a_secession_likelier() -> None:
    config = _eager()
    world = _tiny()
    weak = secession.offshoot_score(world, config, world.realms[1], world.realms[0], 400, 0.2)
    strong = secession.offshoot_score(world, config, world.realms[1], world.realms[0], 400, 2.0)
    assert weak > strong
