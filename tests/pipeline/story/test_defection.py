"""Tests for defections: a town that left an older realm for its holder, planned from the map and checked in a year."""

from __future__ import annotations

import numpy as np
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


def _eager(**overrides: object) -> Config:
    """Defaults where only defections happen, and every candidate's chance is its score (chance 1, no cap)."""
    config = load_config(None)
    config.data["history"]["secession"].update({"chance": 1.0, "max_per_world": 99, **overrides})
    for form, weight in (("offshoot", 0.0), ("split", 0.0), ("defection", 1.0)):
        config.data["tables"]["secession_forms"][form]["weight"] = weight
    return config


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest) -> World:
    return pipeline.generate(_eager(), request.param)


def _defections(world: World):
    return [e for e in world.chronicle if e.kind == "secession" and "defection" in e.tags]


def _settlings(world: World, index: int):
    return [e for e in world.chronicle if e.kind == "settling" and e.poi_ids == [index] and "free" not in e.tags]


# --- generated worlds ------------------------------------------------------------------------------------------------


def test_an_eager_world_has_defections(world: World) -> None:
    assert _defections(world)


def test_a_defection_names_the_holder_and_the_realm_left(world: World) -> None:
    for event in _defections(world):
        holder, old = event.realm_ids
        assert world.pois[event.poi_ids[0]].realm_id == holder and holder != old


def test_the_two_sides_of_a_defection_are_different_powers(world: World) -> None:
    for event in _defections(world):
        assert world.top_realm(event.realm_ids[0]) != world.top_realm(event.realm_ids[1])


def test_a_defecting_town_is_not_a_seat_and_is_a_settling_kind(world: World) -> None:
    kinds, seats = set(load_config(None).get("history.settle_kinds")), {r.seat_poi for r in world.realms}
    for event in _defections(world):
        assert event.poi_ids[0] not in seats and world.pois[event.poi_ids[0]].kind in kinds


def test_a_town_was_settled_by_the_realm_it_later_left(world: World) -> None:
    for event in _defections(world):
        settling = _settlings(world, event.poi_ids[0])
        assert len(settling) == 1 and settling[0].realm_ids == [event.realm_ids[1]]


def test_the_old_owner_existed_when_the_town_was_settled(world: World) -> None:
    gap = int(load_config(None).get("history.min_gap_years"))
    for event in _defections(world):
        town, old = world.pois[event.poi_ids[0]], world.realms[event.realm_ids[1]]
        assert old.founded + gap <= town.founded


def test_a_town_defects_after_it_was_settled(world: World) -> None:
    gap = int(load_config(None).get("history.min_gap_years"))
    for event in _defections(world):
        assert world.pois[event.poi_ids[0]].founded + gap <= event.year <= world.year


def test_the_realm_left_lies_within_reach_of_the_town(world: World) -> None:
    limit = float(load_config(None).get("history.secession.defect_km"))
    for event in _defections(world):
        town = world.pois[event.poi_ids[0]]
        rows, cols = np.nonzero(world.realm_id == event.realm_ids[1])
        km = np.hypot((cols - town.x) * world.scale.km_per_col, (rows - town.y) * world.scale.km_per_row).min()
        assert km <= limit


def test_a_defection_names_the_town_and_both_realms(world: World) -> None:
    for event in _defections(world):
        text = event.text.lower()
        assert world.pois[event.poi_ids[0]].name.lower() in text
        assert all(
            world.realms[r].name.lower() in text or world.realms[r].short.lower() in text for r in event.realm_ids
        )


def test_a_defection_marks_the_town_and_both_realms(world: World) -> None:
    for event in _defections(world):
        kinds = sorted(kind for *_, kind, _ident in event.refs)
        assert "poi" in kinds and kinds.count("realm") >= 2


def test_a_defection_is_worded_by_the_relation_between_the_sides(world: World) -> None:
    config = load_config(None)
    for event in _defections(world):
        holder, old = (world.realms[r] for r in event.realm_ids)
        assert secession.relation_tag(world, config, old, holder) in event.tags


def test_the_town_is_marked_by_both_its_settling_and_its_defection(world: World) -> None:
    for event in _defections(world):
        marks = world.pois[event.poi_ids[0]].event_ids
        assert event.id in marks and _settlings(world, event.poi_ids[0])[0].id in marks


def test_every_held_town_of_a_settling_kind_has_one_settling_event(world: World) -> None:
    kinds, seats = set(load_config(None).get("history.settle_kinds")), {r.seat_poi for r in world.realms}
    for index, poi in enumerate(world.pois):
        if poi.civilized and poi.kind in kinds and poi.realm_id >= 0 and index not in seats:
            assert len(_settlings(world, index)) == 1


def test_defections_change_no_cell_or_poi(world: World) -> None:
    plain = _eager(chance=0.0)
    assert pipeline.generate(plain, world.seed).fingerprint() == world.fingerprint()


def test_the_cap_limits_the_defections() -> None:
    assert len(_defections(pipeline.generate(_eager(max_per_world=1), 42))) <= 1


def test_no_chance_means_no_defection() -> None:
    assert not _defections(pipeline.generate(_eager(chance=0.0), 42))


def test_a_switched_off_secession_kind_means_no_defection() -> None:
    config = _eager()
    config.data["history"]["kinds"] = [k for k in config.data["history"]["kinds"] if k != "secession"]
    assert not _defections(pipeline.generate(config, 42))


def test_the_world_is_deterministic() -> None:
    first, second = pipeline.generate(_eager(), 42), pipeline.generate(_eager(), 42)
    assert [(e.year, e.poi_ids, e.realm_ids) for e in _defections(first)] == [
        (e.year, e.poi_ids, e.realm_ids) for e in _defections(second)
    ]


# --- the planning and the check --------------------------------------------------------------------------------------


def _tiny() -> World:
    """Realm 0 (old, west) and realm 1 (east) side by side; a town of realm 1 stands next to realm 0."""
    world = World(10, 3, 1, grid_scale(10, 3, (1000.0, 300.0), 30.0, 0.0))
    world.year = 1200
    world.realm_id[:, :5], world.realm_id[:, 5:] = 0, 1
    world.pois = [
        POI(kind="capital", x=1, y=1, interior_seed=1, civilized=True, realm_id=0, founded=10),
        POI(kind="capital", x=8, y=1, interior_seed=2, civilized=True, realm_id=1, founded=100),
        POI(kind="town", x=6, y=1, interior_seed=3, civilized=True, realm_id=1, founded=300),
    ]
    world.realms = [
        Realm(id=0, kind="major", seat_poi=0, area_km2=900_000.0, pop=1_000_000, founded=10),
        Realm(id=1, kind="major", seat_poi=1, area_km2=500_000.0, pop=600_000, founded=100),
    ]
    return world


def test_a_town_beside_an_older_realm_may_have_left_it() -> None:
    planned = secession.plan_defections(_tiny(), _eager(), 1)
    assert list(planned) == [2] and planned[2][0] == 0


def test_the_defection_year_lies_between_the_settling_and_the_present() -> None:
    gap = int(_eager().get("history.min_gap_years"))
    year = secession.plan_defections(_tiny(), _eager(), 1)[2][1]
    assert 300 + gap <= year <= 1200


def test_a_seat_never_defects() -> None:
    assert 1 not in secession.plan_defections(_tiny(), _eager(), 1)


def test_a_town_too_far_from_the_old_realm_is_not_planned() -> None:
    assert secession.plan_defections(_tiny(), _eager(defect_km=10.0), 1) == {}


def test_an_old_owner_founded_after_the_town_is_not_planned() -> None:
    world = _tiny()
    world.realms[0].founded = 400
    assert secession.plan_defections(world, _eager(), 1) == {}


def test_a_vassal_cannot_defect_from_its_own_liege() -> None:
    world = _tiny()
    world.realms[1].liege = 0
    assert secession.plan_defections(world, _eager(), 1) == {}


def test_nothing_is_planned_when_the_defection_form_has_no_weight() -> None:
    config = _eager()
    config.data["tables"]["secession_forms"]["defection"]["weight"] = 0.0
    config.data["tables"]["secession_forms"]["offshoot"]["weight"] = 1.0
    assert secession.plan_defections(_tiny(), config, 1) == {}


def _check(seed: int, chance: float = 1.0) -> list:
    config = _eager(chance=chance)
    world = _tiny()
    ledger = Ledger(config)
    conflicts.derive(world, config, seed, 1200, ledger, None, None, 0, {2: (0, 700)})
    return ledger.finish()


def test_a_check_makes_the_defection_for_some_seeds() -> None:
    # The roll is a draw against chance x score: over many seeds the town defects in some and stays in others.
    outcomes = {tuple(e.kind for e in _check(seed)) for seed in range(40)}
    assert outcomes == {("settling", "secession"), ("settling",)}


def test_a_failed_check_settles_the_town_for_its_holder() -> None:
    for seed in range(20):
        (settling,) = _check(seed, 1e-9)
        assert settling.realm_ids == [1]


def test_a_defection_settles_the_town_for_the_realm_it_left() -> None:
    for seed in range(40):
        events = _check(seed)
        if len(events) == 2:
            assert events[0].realm_ids == [0] and events[1].realm_ids == [1, 0] and events[1].year == 700
            return
    pytest.fail("no seed made the defection")
