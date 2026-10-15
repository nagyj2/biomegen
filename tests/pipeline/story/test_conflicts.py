"""Tests for the conflicts: relations, older wars and peace, battles, strengths and the falls of fallen realms."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.civilization.diplomacy import front_cells
from biomegen.pipeline.story import conflicts
from biomegen.pipeline.story.conflicts import FALLEN, REALM
from biomegen.pipeline.story.ledger import Ledger
from biomegen.util.units import grid_scale
from biomegen.world.entities import ChronicleEvent, FallenRealm, Realm
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _events(world: World, kind: str, *tags: str) -> list[ChronicleEvent]:
    return [e for e in world.chronicle if e.kind == kind and set(tags) <= set(e.tags)]


def _pairs(world: World) -> dict[frozenset[int], object]:
    return {frozenset((r.a, r.b)): r for r in world.relations}


# --- relations ------------------------------------------------------------------------------------


def test_every_war_relation_is_one_ongoing_war(world: World) -> None:
    wars = [r for r in world.relations if r.kind == "war"]
    assert wars and len(_events(world, "war", "ongoing")) == len(wars)


def test_every_rivalry_is_one_event(world: World) -> None:
    assert len(_events(world, "rivalry")) == sum(1 for r in world.relations if r.kind == "rivalry")


def test_every_pact_is_one_treaty_tagged_with_its_kind(world: World) -> None:
    pacts = sorted(r.kind for r in world.relations if r.kind in ("alliance", "trade"))
    assert pacts and pacts == sorted(e.tags[0] for e in _events(world, "treaty"))


def test_an_ongoing_war_names_the_attacker_first(world: World) -> None:
    attackers = {frozenset((r.a, r.b)): r.attacker for r in world.relations if r.kind == "war"}
    wars = _events(world, "war", "ongoing")
    assert all(e.realm_ids[0] == attackers[frozenset(e.realm_ids)] for e in wars)


def test_an_ongoing_war_carries_the_claimed_town(world: World) -> None:
    claims = {frozenset((r.a, r.b)): r.claim_poi for r in world.relations if r.kind == "war"}
    wars = _events(world, "war", "ongoing")
    expected = [[claims[frozenset(e.realm_ids)]] if claims[frozenset(e.realm_ids)] >= 0 else [] for e in wars]
    assert [e.poi_ids for e in wars] == expected


def test_wars_join_independent_neighbours(world: World) -> None:
    wars = [r for r in world.relations if r.kind == "war"]
    assert all(world.realms[i].liege < 0 for r in wars for i in (r.a, r.b)) and all(r.border_km > 0 for r in wars)


def test_a_relation_begins_after_both_powers_exist(world: World, cfg: Config) -> None:
    gap = cfg.get("history.min_gap_years")
    for event in _events(world, "war", "ongoing") + _events(world, "rivalry") + _events(world, "treaty"):
        first = min(max(world.realms[i].founded for i in event.realm_ids) + gap, world.year)
        assert event.year >= first


def test_relations_are_not_confined_to_one_period() -> None:
    # Wars and pacts start anywhere between the realms' foundings and the present: over two worlds they span centuries.
    config = load_config(None)
    years = []
    for seed in SEEDS:
        world = pipeline.generate(config, seed)
        years += [e.year for e in world.chronicle if e.kind in ("war", "rivalry", "treaty")]
    assert max(years) - min(years) > 600


# --- older wars and peace -------------------------------------------------------------------------


def test_an_older_war_ends_in_one_peace(world: World) -> None:
    ended = _events(world, "war", "ended")
    realm_wars = [e for e in ended if not e.fallen_ids]
    assert realm_wars and len(_events(world, "peace")) == len(realm_wars)


def test_a_peace_follows_its_war(world: World) -> None:
    starts = {frozenset(e.realm_ids): e.year for e in _events(world, "war", "ended") if not e.fallen_ids}
    assert all(e.year > starts[frozenset(e.realm_ids)] for e in _events(world, "peace"))


def test_a_peace_names_the_winner_then_the_loser(world: World) -> None:
    pairs = _pairs(world)
    assert all(frozenset(e.realm_ids) in pairs for e in _events(world, "peace"))


def test_a_relation_that_follows_an_older_war_comes_after_its_peace(world: World, cfg: Config) -> None:
    gap = cfg.get("history.min_gap_years")
    peace = {frozenset(e.realm_ids): e.year for e in _events(world, "peace")}
    later = _events(world, "war", "ongoing") + _events(world, "rivalry") + _events(world, "treaty")
    checked = [e for e in later if frozenset(e.realm_ids) in peace]
    assert checked and all(e.year >= min(peace[frozenset(e.realm_ids)] + gap, world.year) for e in checked)


def test_no_older_wars_at_chance_zero() -> None:
    config = load_config(None)
    config.data["history"]["past_war_chance"] = 0.0
    world = pipeline.generate(config, 42)
    assert _events(world, "peace") == [] and not [
        e for e in _events(world, "war") if not e.fallen_ids and "ended" in e.tags
    ]


# --- battles --------------------------------------------------------------------------------------


def test_a_battle_between_realms_is_fought_on_the_border_of_the_pair(world: World) -> None:
    fronts = _events(world, "battle", "front")
    assert fronts and all(
        e.location[1] * world.width + e.location[0] in front_cells(world, *e.realm_ids).tolist() for e in fronts
    )


def test_a_battle_between_realms_is_between_related_powers(world: World) -> None:
    pairs = _pairs(world)
    assert all(frozenset(e.realm_ids) in pairs for e in _events(world, "battle", "front"))


def test_a_battle_is_fought_while_its_realms_exist(world: World) -> None:
    assert all(e.year >= world.realms[i].founded for e in _events(world, "battle") for i in e.realm_ids)


def test_a_battle_with_a_fallen_realm_is_at_its_ruins(world: World) -> None:
    ruins = _events(world, "battle", "ruins")
    assert ruins and all(e.location == world.fallen_realms[e.fallen_ids[0]].location for e in ruins)


def test_a_ruins_battle_says_who_won(world: World) -> None:
    ruins = _events(world, "battle", "ruins")
    assert all(("won_by_fallen" in e.tags) != ("won_by_realm" in e.tags) for e in ruins)


def test_no_battles_at_rate_zero() -> None:
    config = load_config(None)
    config.data["history"]["battles_per_100km_front"] = 0.0
    world = pipeline.generate(config, 42)
    assert not [e for e in _events(world, "battle", "front") if "ongoing" in e.tags]


# --- fallen realms in the timeline ----------------------------------------------------------------


def test_nothing_happens_to_a_fallen_realm_outside_its_life(world: World) -> None:
    for event in world.chronicle:
        for fallen_id in event.fallen_ids:
            fallen = world.fallen_realms[fallen_id]
            assert fallen.founded <= event.year <= fallen.fell


def test_a_conquered_realm_falls_to_a_realm_that_existed(world: World) -> None:
    conquered = _events(world, "fall", "conquered")
    assert conquered and all(
        len(e.realm_ids) == 1 and world.realms[e.realm_ids[0]].founded <= e.year for e in conquered
    )


# --- strengths ------------------------------------------------------------------------------------


def _timeline(strengths: dict[tuple[str, int], float]) -> conflicts._Timeline:
    """Two realms (one big, one small) and one fallen realm, with the strengths set by the test."""
    config = load_config(None)
    config.data["history"]["kinds"] = ["war", "battle", "peace", "fall"]
    world = World(8, 4, 1, grid_scale(8, 4, (800.0, 400.0), 30.0, 0.0))
    world.realms = [Realm(id=0, kind="major", area_km2=3000.0), Realm(id=1, kind="major", area_km2=1000.0)]
    world.fallen_realms = [FallenRealm(id=0, location=(2, 2), founded=10, fell=500)]
    timeline = conflicts._Timeline(world, config, 1, 1200, Ledger(config))
    timeline.strength.update(strengths)
    return timeline


def test_a_realm_starts_at_its_area_over_the_mean() -> None:
    timeline = _timeline({})
    assert (timeline.strength[(REALM, 0)], timeline.strength[(REALM, 1)]) == (1.5, 0.5)


def test_a_victory_raises_strength_and_a_defeat_lowers_it() -> None:
    timeline = _timeline({(REALM, 0): 1.0, (REALM, 1): 1.0})
    timeline._settle((REALM, 0), (REALM, 1))
    assert (timeline.strength[(REALM, 0)], timeline.strength[(REALM, 1)]) == pytest.approx((1.15, 0.8))


def test_strength_never_falls_below_the_floor() -> None:
    timeline = _timeline({(REALM, 0): 1.0, (REALM, 1): 0.05})
    timeline._settle((REALM, 0), (REALM, 1))
    assert timeline.strength[(REALM, 1)] == 0.05


def test_a_far_stronger_side_wins_a_battle() -> None:
    timeline = _timeline({(REALM, 0): 1e9, (REALM, 1): 1.0})
    timeline.plan(100, "battle", (REALM, 0), (REALM, 1), ("t",), (1, 1))
    timeline.play()
    assert [e.realm_ids for e in timeline.ledger.finish() if e.kind == "battle"] == [[0, 1]]


def test_a_fallen_realm_beaten_below_the_floor_is_conquered() -> None:
    timeline = _timeline({(REALM, 0): 1e9, (FALLEN, 0): 0.31})
    timeline.plan(100, "battle", (REALM, 0), (FALLEN, 0), ("t",), (2, 2))
    timeline.play()
    falls = [e for e in timeline.ledger.finish() if e.kind == "fall"]
    assert [(e.realm_ids, e.fallen_ids, e.tags) for e in falls] == [([0], [0], ("conquered",))]


def test_a_conquered_realm_falls_soon_after_its_last_battle() -> None:
    timeline = _timeline({(REALM, 0): 1e9, (FALLEN, 0): 0.31})
    timeline.plan(100, "battle", (REALM, 0), (FALLEN, 0), ("t",), (2, 2))
    timeline.play()
    assert 100 <= timeline.world.fallen_realms[0].fell <= 125


def test_a_conquered_realm_fights_no_more() -> None:
    timeline = _timeline({(REALM, 0): 1e9, (FALLEN, 0): 0.31})
    timeline.plan(100, "battle", (REALM, 0), (FALLEN, 0), ("t",), (2, 2))
    timeline.plan(200, "battle", (REALM, 1), (FALLEN, 0), ("u",), (2, 2))
    timeline.play()
    assert len([e for e in timeline.ledger.finish() if e.kind == "battle"]) == 1


def test_a_surviving_fallen_realm_falls_at_its_natural_year() -> None:
    timeline = _timeline({})
    timeline.play()
    falls = [e for e in timeline.ledger.finish() if e.kind == "fall"]
    assert [(e.year, e.tags) for e in falls] == [(500, ())]
