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


@pytest.fixture(scope="module", params=SEEDS)
def busy(request: pytest.FixtureRequest) -> World:
    """A world with many episodes and hard-pressed fallen realms, so those events are always there to check."""
    config = load_config(None)
    config.data["history"].update(fallen_wars=[2, 4], fall_strength=0.9)
    config.data["history"]["episodes"].update(
        first_chance=1.0, more_chance=0.95, decay=0.9, max_per_pair=6, max_wars_per_pair=3
    )
    config.data["tables"]["episode_kinds"]["war"]["weight_scale"] = 5.0
    return pipeline.generate(config, request.param)


def _events(world: World, kind: str, *tags: str) -> list[ChronicleEvent]:
    return [e for e in world.chronicle if e.kind == kind and set(tags) <= set(e.tags)]


def _pairs(world: World) -> dict[frozenset[int], object]:
    """The pairs a relation or an ended episode joins."""
    return {frozenset((r.a, r.b)): r for r in [*world.relations, *world.episodes]}


def _present(world: World, kind: str) -> list[ChronicleEvent]:
    """The starting events of today's relations of ``kind`` (none belongs to an ended episode)."""
    return [e for e in world.chronicle if e.kind == kind and e.episode < 0 and "ended" not in e.tags]


# --- relations ------------------------------------------------------------------------------------


def test_every_war_relation_is_one_ongoing_war(world: World) -> None:
    wars = [r for r in world.relations if r.kind == "war"]
    assert wars and len(_events(world, "war", "ongoing")) == len(wars)


def test_every_rivalry_relation_is_one_rivalry_event(world: World) -> None:
    assert len(_present(world, "rivalry")) == sum(1 for r in world.relations if r.kind == "rivalry")


def test_every_pact_relation_is_one_treaty_tagged_with_its_kind(world: World) -> None:
    pacts = sorted(r.kind for r in world.relations if r.kind in ("alliance", "trade"))
    assert pacts and pacts == sorted(e.tags[0] for e in _present(world, "treaty"))


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
    wars = [*(r for r in world.relations if r.kind == "war"), *(r for r in world.episodes if r.kind == "war")]
    assert all(world.realms[i].liege < 0 for r in wars for i in (r.a, r.b)) and all(r.border_km > 0 for r in wars)


def test_an_episode_begins_after_both_powers_exist(world: World, cfg: Config) -> None:
    gap = cfg.get("history.min_gap_years")
    starts = [e for e in world.chronicle if e.kind in ("war", "rivalry", "treaty") and not e.fallen_ids]
    for event in starts:
        if "conquest" in event.tags:
            continue
        first = min(max(world.realms[i].founded for i in event.realm_ids) + gap, world.year)
        assert event.year >= first


def test_relations_are_not_confined_to_one_period() -> None:
    # Episodes start anywhere between the realms' foundings and the present: over two worlds they span centuries.
    config = load_config(None)
    years = []
    for seed in SEEDS:
        world = pipeline.generate(config, seed)
        years += [e.year for e in world.chronicle if e.kind in ("war", "rivalry", "treaty")]
    assert max(years) - min(years) > 600


# --- episodes -------------------------------------------------------------------------------------


def test_a_present_relation_is_no_older_than_its_kinds_age_range(world: World, cfg: Config) -> None:
    oldest = max(
        int(cfg.get(f"tables.episode_kinds.{k}.present_age")[1]) for k in ("war", "rivalry", "alliance", "trade")
    )
    assert all(world.year - e.year <= oldest for e in _events(world, "war", "ongoing") + _present(world, "treaty"))


def test_a_pairs_episodes_never_overlap(busy: World) -> None:
    for pair in {frozenset((e.a, e.b)) for e in busy.episodes}:
        runs = sorted((e.start, e.end) for e in busy.episodes if frozenset((e.a, e.b)) == pair)
        assert all(before[1] < after[0] for before, after in zip(runs, runs[1:], strict=False))


def test_an_ended_episode_comes_before_the_present_relation_of_its_pair(busy: World) -> None:
    present = {
        frozenset((r.a, r.b)): e.year
        for r in busy.relations
        for e in _present(busy, r.kind)
        if frozenset(e.realm_ids) == frozenset((r.a, r.b))
    }
    ended = [e for e in busy.episodes if frozenset((e.a, e.b)) in present]
    assert ended and all(e.end < present[frozenset((e.a, e.b))] for e in ended)


def test_a_war_episode_ends_in_one_peace(busy: World) -> None:
    wars = [i for i, e in enumerate(busy.episodes) if e.kind == "war"]
    peaces = [e.episode for e in _events(busy, "peace")]
    assert wars and sorted(peaces) == wars


def test_a_peace_follows_its_war(busy: World) -> None:
    starts = {e.episode: e.year for e in _events(busy, "war", "ended") if e.episode >= 0}
    peaces = _events(busy, "peace")
    assert peaces and all(e.year > starts[e.episode] for e in peaces)


def test_a_peace_names_the_winner_then_the_loser(world: World) -> None:
    pairs = _pairs(world)
    assert all(frozenset(e.realm_ids) in pairs for e in _events(world, "peace"))


def _war_of(world: World, peace: ChronicleEvent) -> ChronicleEvent:
    """The war a peace ends."""
    return next(e for e in world.chronicle if e.kind == "war" and e.episode == peace.episode)


def test_a_peace_takes_the_salience_of_its_war(busy: World) -> None:
    peaces = _events(busy, "peace")
    assert peaces and all(e.salience == _war_of(busy, e).salience for e in peaces)


def test_a_truce_is_worded_by_the_truce_row(busy: World, cfg: Config) -> None:
    truces = _events(busy, "peace", "truce")
    assert truces and all(e.template in cfg.get("tables.chronicle.peace_truce.templates") for e in truces)


def test_no_ended_wars_with_no_wars_allowed() -> None:
    config = load_config(None)
    config.data["history"]["episodes"]["max_wars_per_pair"] = 0
    world = pipeline.generate(config, 42)
    assert _events(world, "peace") == [] and not [e for e in world.episodes if e.kind == "war"]


def test_no_episodes_at_chance_zero() -> None:
    config = load_config(None)
    config.data["history"]["episodes"]["first_chance"] = 0.0
    config.data["history"]["episodes"]["more_chance"] = 0.0
    assert pipeline.generate(config, 42).episodes == []


def test_an_ended_trade_or_alliance_ends_minor(busy: World) -> None:
    ended = [e for e in busy.chronicle if e.kind == "treaty" and "ended" in e.tags]
    assert ended and all(e.salience == "minor" for e in ended)


def test_a_trade_event_is_minor(busy: World) -> None:
    trades = [e for e in busy.chronicle if e.kind == "treaty" and "trade" in e.tags]
    assert trades and all(e.salience == "minor" for e in trades)


def test_an_alliance_event_is_major(busy: World) -> None:
    allies = [e for e in busy.chronicle if e.kind == "treaty" and "alliance" in e.tags and "ended" not in e.tags]
    assert allies and all(e.salience == "major" for e in allies)


def test_a_purchase_is_paid_in_money_by_a_realm_of_the_pair(busy: World) -> None:
    buys = [e for e in busy.episodes if e.deal in ("buy_once", "buy_ongoing")]
    assert buys and all(e.buyer in (e.a, e.b) and len(e.goods) == 1 for e in buys)


def test_a_swap_gives_two_different_resources_and_never_money(busy: World) -> None:
    swaps = [e for e in busy.episodes if e.deal == "swap"]
    assert swaps and all(len(e.goods) == 2 and e.goods[0] != e.goods[1] and "money" not in e.goods for e in swaps)


def test_a_one_off_purchase_has_no_end_event(busy: World) -> None:
    once = [i for i, e in enumerate(busy.episodes) if e.deal == "buy_once"]
    ends = [e for e in busy.chronicle if e.kind == "treaty" and "ended" in e.tags and e.episode in once]
    assert once and ends == []


def test_every_trade_has_a_volume(busy: World) -> None:
    trades = [r for r in [*busy.relations, *busy.episodes] if r.kind == "trade"]
    assert trades and all(r.volume in ("small", "steady", "large") for r in trades)


def test_only_a_war_between_small_powers_is_minor(busy: World, cfg: Config) -> None:
    small = set(cfg.get("history.episodes.minor_war_kinds"))
    wars = [e for e in busy.chronicle if e.kind == "war" and not e.fallen_ids and "conquest" not in e.tags]
    assert all((e.salience == "minor") == all(busy.realms[i].kind in small for i in e.realm_ids) for e in wars)


def test_only_a_decisive_battle_of_a_major_war_is_major(busy: World) -> None:
    fronts = _events(busy, "battle", "front")
    assert fronts and all(e.salience == "minor" for e in fronts if "decisive" not in e.tags)


def test_an_ended_war_has_one_decisive_battle(busy: World) -> None:
    for index in [i for i, e in enumerate(busy.episodes) if e.kind == "war"]:
        battles = [e for e in _events(busy, "battle", "front") if e.episode == index]
        assert len([e for e in battles if "decisive" in e.tags]) <= 1


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


def test_a_conquered_realm_falls_to_a_realm_that_existed(busy: World) -> None:
    conquered = _events(busy, "fall", "conquered")
    assert conquered and all(len(e.realm_ids) == 1 and busy.realms[e.realm_ids[0]].founded <= e.year for e in conquered)


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
    assert [e.realm_ids for e in timeline.ledger.finish(0) if e.kind == "battle"] == [[0, 1]]


def test_a_fallen_realm_beaten_below_the_floor_is_conquered() -> None:
    timeline = _timeline({(REALM, 0): 1e9, (FALLEN, 0): 0.31})
    timeline.plan(100, "battle", (REALM, 0), (FALLEN, 0), ("t",), (2, 2))
    timeline.play()
    falls = [e for e in timeline.ledger.finish(0) if e.kind == "fall"]
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
    assert len([e for e in timeline.ledger.finish(0) if e.kind == "battle"]) == 1


def test_a_surviving_fallen_realm_falls_at_its_natural_year() -> None:
    timeline = _timeline({})
    timeline.play()
    falls = [e for e in timeline.ledger.finish(0) if e.kind == "fall"]
    assert [(e.year, e.tags) for e in falls] == [(500, ())]


# --- decisive battles --------------------------------------------------------------------------------


def _front_battles(world: World, pair: frozenset[int]) -> list[ChronicleEvent]:
    return [e for e in _events(world, "battle", "front") if frozenset(e.realm_ids) == pair]


def test_the_last_battle_of_an_older_war_is_decisive(busy: World) -> None:
    # Each decisive front battle is followed by its pair's peace with no other battle of that pair in between.
    peaces = _events(busy, "peace")
    decisive = _events(busy, "battle", "front", "decisive")
    assert decisive
    for battle in decisive:
        pair = frozenset(battle.realm_ids)
        later = [p for p in peaces if frozenset(p.realm_ids) == pair and p.year >= battle.year]
        assert later
        peace = min(later, key=lambda p: p.year)
        assert not [b for b in _front_battles(busy, pair) if battle.year < b.year <= peace.year]


def test_only_the_last_battle_before_a_peace_is_decisive(busy: World) -> None:
    # A pair's decisive battles never outnumber its peaces: an older war has one decisive battle at most.
    for pair in {frozenset(e.realm_ids) for e in _events(busy, "battle", "front", "decisive")}:
        decisive = [e for e in _front_battles(busy, pair) if "decisive" in e.tags]
        assert len(decisive) <= len([p for p in _events(busy, "peace") if frozenset(p.realm_ids) == pair])


def test_a_battle_of_a_war_still_going_is_never_decisive(busy: World) -> None:
    # Only a war that ended in peace has a decisive battle; the battles of the ongoing wars come after it.
    peace_years = {frozenset(p.realm_ids): p.year for p in _events(busy, "peace")}
    for battle in _events(busy, "battle", "front", "decisive"):
        assert battle.year <= peace_years[frozenset(battle.realm_ids)]


def test_the_battle_that_conquers_a_fallen_realm_is_decisive(busy: World) -> None:
    conquered = _events(busy, "fall", "conquered")
    assert conquered
    for fall in conquered:
        battles = [b for b in _events(busy, "battle", "ruins", "decisive") if b.fallen_ids == fall.fallen_ids]
        assert len(battles) == 1 and battles[0].year <= fall.year


def test_a_battle_at_ruins_that_does_not_end_the_realm_is_not_decisive(busy: World) -> None:
    conquered_ids = {e.fallen_ids[0] for e in _events(busy, "fall", "conquered")}
    for battle in _events(busy, "battle", "ruins", "decisive"):
        assert battle.fallen_ids[0] in conquered_ids
