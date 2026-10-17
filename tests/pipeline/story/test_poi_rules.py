"""Tests for the event-to-POI rule table: which events make which POIs, how many, and that a plan is pure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story.poi_rules import PoiPlan, event_key, poi_for_event
from biomegen.world.entities import ChronicleEvent, Relation
from biomegen.world.world import World

SEED = 5
YEAR = 1200


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture()
def world() -> World:
    made = World(10, 10, 1)
    made.year = YEAR
    made.relations = [Relation(a=0, b=1, kind="war", border_km=650.0), Relation(a=0, b=2, kind="war", border_km=100.0)]
    return made


def _event(kind: str, event_id: int = 3, year: int = 500, **fields: object) -> ChronicleEvent:
    # The draws are keyed on an event's content, not its id, so the number also sets its location.
    fields.setdefault("location", (event_id, 0))
    return ChronicleEvent(id=event_id, year=year, kind=kind, **fields)  # type: ignore[arg-type]


def _kinds(plans: list[PoiPlan]) -> list[str]:
    return [plan.kind for plan in plans]


def _plan(world: World, config: Config, event: ChronicleEvent, kind: str, **options: object) -> PoiPlan | None:
    return next((p for p in poi_for_event(world, config, SEED, event, **options) if p.kind == kind), None)  # type: ignore[arg-type]


def _share(world: World, config: Config, kind: str, make) -> float:
    """The share of 400 events (ids 0..399) made by ``make(id)`` that produce a ``kind`` plan."""
    return sum(1 for n in range(400) if _plan(world, config, make(n), kind) is not None) / 400


# --------------------------------------------------------------------------- ruins from a fall
def test_a_fall_always_makes_a_ruin(world: World, cfg: Config) -> None:
    assert all(_plan(world, cfg, _event("fall", n), "ruin") is not None for n in range(50))


def test_a_ruin_comes_with_zero_to_two_holdings(world: World, cfg: Config) -> None:
    # The capital ruin plus the row's [0, 2] holdings: one to three ruins.
    counts = {_plan(world, cfg, _event("fall", n), "ruin").count for n in range(200)}  # type: ignore[union-attr]
    assert counts == {1, 2, 3}


def test_each_ruin_has_one_fate_that_generation_may_use(world: World, cfg: Config) -> None:
    plans = [_plan(world, cfg, _event("fall", n), "ruin") for n in range(100)]
    assert all(p is not None and len(p.fates) == p.count and set(p.fates) <= {"ruin", "bandit"} for p in plans)


def test_a_quarter_of_ruins_are_bandit_held(world: World, cfg: Config) -> None:
    # Weights 3 : 1 give a bandit fate to a quarter of the ruins.
    fates = [f for n in range(300) if (p := _plan(world, cfg, _event("fall", n), "ruin")) for f in p.fates]
    assert 0.2 < fates.count("bandit") / len(fates) < 0.3


def test_a_simulation_may_draw_the_sim_only_fates(world: World, cfg: Config) -> None:
    fates = {
        f for n in range(300) if (p := _plan(world, cfg, _event("fall", n), "ruin", simulated=True)) for f in p.fates
    }
    assert {"captured", "successor"} <= fates


# --------------------------------------------------------------------------- a plan is pure
def test_the_same_event_gives_the_same_plans(world: World, cfg: Config) -> None:
    event = _event("fall", 17)
    assert poi_for_event(world, cfg, SEED, event) == poi_for_event(world, cfg, SEED, event)


def test_a_plan_depends_on_its_event_not_on_the_others(world: World, cfg: Config) -> None:
    # Asking about other events first changes nothing: every draw is keyed on the event.
    first = poi_for_event(world, cfg, SEED, _event("fall", 17))
    for n in range(5):
        poi_for_event(world, cfg, SEED, _event("fall", n))
    assert poi_for_event(world, cfg, SEED, _event("fall", 17)) == first


def test_a_plan_does_not_depend_on_the_events_id(world: World, cfg: Config) -> None:
    # An id is a ledger position that shifts when events are added; the same event under another id draws the same.
    plans = [poi_for_event(world, cfg, SEED, _event("fall", n, location=(4, 4))) for n in (0, 9, 400)]
    assert plans[0] == [replace(p, event_id=0) for p in plans[1]] == [replace(p, event_id=0) for p in plans[2]]


def test_events_that_differ_in_content_have_different_keys() -> None:
    keys = {
        event_key(_event("battle", year=500, realm_ids=[0, 1], location=(3, 4))),
        event_key(_event("battle", year=501, realm_ids=[0, 1], location=(3, 4))),
        event_key(_event("battle", year=500, realm_ids=[1, 0], location=(3, 4))),
        event_key(_event("battle", year=500, realm_ids=[0, 1], location=(4, 3))),
        event_key(_event("war", year=500, realm_ids=[0, 1], location=(3, 4))),
        event_key(_event("battle", year=500, realm_ids=[0], fallen_ids=[1], location=(3, 4))),
        event_key(_event("battle", year=500, realm_ids=[0, 1], location=(3, 4), tags=("decisive",))),
    }
    assert len(keys) == 7


def test_the_table_does_not_touch_the_world(world: World, cfg: Config) -> None:
    poi_for_event(world, cfg, SEED, _event("fall", 1))
    assert world.pois == [] and world.chronicle == []


# --------------------------------------------------------------------------- battlefields
def _battle(n: int, tags: tuple[str, ...] = ("decisive",), year: int = 500) -> ChronicleEvent:
    return _event("battle", n, year=year, tags=tags)


def test_a_quarter_of_decisive_old_battles_make_a_battlefield(world: World, cfg: Config) -> None:
    assert 0.18 < _share(world, cfg, "battlefield", _battle) < 0.32


def test_a_battle_that_is_not_decisive_makes_no_battlefield(world: World, cfg: Config) -> None:
    assert _share(world, cfg, "battlefield", lambda n: _battle(n, tags=("front",))) == 0.0


def test_a_young_battle_makes_no_battlefield(world: World, cfg: Config) -> None:
    # A battle needs 30 years to become a field: one 29 years old makes none, one 30 years old may.
    assert _share(world, cfg, "battlefield", lambda n: _battle(n, year=YEAR - 29)) == 0.0
    assert _share(world, cfg, "battlefield", lambda n: _battle(n, year=YEAR - 30)) > 0.0


def test_a_simulation_counts_the_age_to_its_own_year(world: World, cfg: Config) -> None:
    young = _battle(0, year=YEAR + 10)
    assert all(_plan(world, cfg, young, "battlefield", now=YEAR + 50) is None for _ in range(1))
    assert any(_plan(world, cfg, _battle(n, year=YEAR + 10), "battlefield", now=YEAR + 50) for n in range(100))


# --------------------------------------------------------------------------- watchtowers
def _war(front_realms: tuple[int, int], tags: tuple[str, ...] = ("ongoing",)) -> ChronicleEvent:
    return _event("war", 9, year=900, realm_ids=list(front_realms), tags=tags)


def test_a_long_front_gets_at_most_three_watchtowers(world: World, cfg: Config) -> None:
    # 650 km of front is three 300 km stretches, rounded up, and three is the cap.
    plan = _plan(world, cfg, _war((0, 1)), "watchtower")
    assert plan is not None and plan.count == 3


def test_a_short_front_gets_one_watchtower(world: World, cfg: Config) -> None:
    plan = _plan(world, cfg, _war((0, 2)), "watchtower")
    assert plan is not None and plan.count == 1


def test_a_war_that_is_over_makes_watchtowers_too(world: World, cfg: Config) -> None:
    # They stand while the war lasts and are dismantled or abandoned at the peace.
    assert _plan(world, cfg, _war((0, 1), tags=("ended",)), "watchtower") is not None


def test_a_war_with_no_relation_makes_no_watchtower(world: World, cfg: Config) -> None:
    assert _plan(world, cfg, _war((3, 4)), "watchtower") is None


# --------------------------------------------------------------------------- shrines
def _succession(old: str, new: str) -> ChronicleEvent:
    return _event("succession", 4, realm_ids=[2], tags=(f"from:{old}", f"to:{new}"))


def test_an_aggressive_predecessor_gives_a_shrine_near_the_seat(world: World, cfg: Config) -> None:
    plan = _plan(world, cfg, _succession("martial", "pious"), "shrine")
    assert plan is not None and plan.site == "shrine_near_seat"


def test_a_passive_predecessor_gives_a_wilderness_shrine(world: World, cfg: Config) -> None:
    plan = _plan(world, cfg, _succession("gentle", "pious"), "shrine")
    assert plan is not None and plan.site == "shrine_wild"


def test_a_shrine_belongs_to_the_realm_whose_ruler_changed(world: World, cfg: Config) -> None:
    plan = _plan(world, cfg, _succession("martial", "pious"), "shrine")
    assert plan is not None and plan.realm_id == 2


def test_a_succession_into_another_style_makes_no_shrine(world: World, cfg: Config) -> None:
    assert _plan(world, cfg, _succession("martial", "gentle"), "shrine") is None


def test_a_succession_without_a_previous_style_makes_no_shrine(world: World, cfg: Config) -> None:
    event = _event("succession", 4, realm_ids=[2], tags=("to:pious",))
    assert _plan(world, cfg, event, "shrine") is None


# --------------------------------------------------------------------------- towers and dungeons from history
def test_a_fifth_of_falls_make_a_wild_tower(world: World, cfg: Config) -> None:
    assert 0.13 < _share(world, cfg, "tower", lambda n: _event("fall", n)) < 0.27


def test_only_a_conquered_fall_can_make_a_dungeon(world: World, cfg: Config) -> None:
    natural = _share(world, cfg, "dungeon", lambda n: _event("fall", n))
    conquered = _share(world, cfg, "dungeon", lambda n: _event("fall", n, tags=("conquered",)))
    assert natural == 0.0 and 0.13 < conquered < 0.27


# --------------------------------------------------------------------------- what is never made
def test_location_kinds_are_never_made_from_events(world: World, cfg: Config) -> None:
    kinds = {
        k for n in range(100) for k in _kinds(poi_for_event(world, cfg, SEED, _event("fall", n, tags=("conquered",))))
    }
    assert not kinds & {"camp", "boat"}


def test_an_event_of_another_kind_makes_nothing(world: World, cfg: Config) -> None:
    assert poi_for_event(world, cfg, SEED, _event("treaty")) == []
