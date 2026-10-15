"""Tests for the secession score: each term, the weighted mean and the entry points, on a small hand-made world."""

from __future__ import annotations

import copy

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story import secession
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, Realm, Relation, Ruler
from biomegen.world.world import World

YEAR = 600


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _ruler(realm_id: int, trust: float = 0.5, aggression: float = 0.5) -> Ruler:
    traits = {"aggression": aggression, "greed": 0.5, "trust": trust, "expansionism": 0.5, "caution": 0.5}
    return Ruler(id=realm_id, realm_id=realm_id, from_year=10, to_year=None, style="martial", traits=traits)


def _world(*, parent_trust: float = 0.5) -> World:
    """Realm 0 is old and big, realm 1 a smaller bordering neighbour at war with it, realm 2 a far small ally.

    Seats are 100 km apart per cell: realm 1's is 400 km from realm 0's, realm 2's 2,600 km.
    """
    world = World(30, 10, 1, grid_scale(30, 10, (3000.0, 1000.0), 30.0, 0.0))
    world.year = 1200
    world.pois = [
        POI(kind="capital", x=2, y=5, interior_seed=1, civilized=True),
        POI(kind="capital", x=6, y=5, interior_seed=2, civilized=True),
        POI(kind="capital", x=28, y=5, interior_seed=3, civilized=True),
    ]
    world.realms = [
        Realm(id=0, kind="major", seat_poi=0, area_km2=1_000_000.0, pop=2_000_000, founded=10),
        Realm(id=1, kind="major", seat_poi=1, area_km2=300_000.0, pop=900_000, founded=300),
        Realm(id=2, kind="major", seat_poi=2, area_km2=250_000.0, pop=500_000, founded=300),
    ]
    world.relations = [
        Relation(a=0, b=1, kind="war", border_km=300.0),
        Relation(a=0, b=2, kind="alliance", border_km=0.0),
    ]
    world.rulers = [_ruler(0, trust=parent_trust), _ruler(1), _ruler(2)]
    return world


# --- the terms ---


def test_sides_that_border_each_other_are_as_close_as_can_be(cfg: Config) -> None:
    assert secession.proximity_term(cfg, 5000.0, True) == 1.0


def test_proximity_falls_with_the_distance_between_the_seats(cfg: Config) -> None:
    far = float(cfg.get("history.secession.proximity_km"))
    assert [secession.proximity_term(cfg, km, False) for km in (0.0, far / 2, far, 2 * far)] == [1.0, 0.5, 0.0, 0.0]


def test_a_breakaway_inside_the_size_share_fits_fully(cfg: Config) -> None:
    low, high = cfg.get("history.secession.size_share")
    assert secession.size_term(cfg, (low + high) / 2) == 1.0


def test_a_tiny_breakaway_fits_less_than_a_middling_one(cfg: Config) -> None:
    assert secession.size_term(cfg, 0.05) < secession.size_term(cfg, 0.4)


def test_a_breakaway_as_big_as_its_parent_does_not_fit(cfg: Config) -> None:
    assert secession.size_term(cfg, 1.0) == 0.0 and secession.size_term(cfg, 1.5) == 0.0


def test_the_halves_of_a_split_balance(cfg: Config) -> None:
    assert [secession.balance_term(a, b) for a, b in ((5.0, 5.0), (5.0, 10.0), (0.0, 0.0))] == [1.0, 0.5, 0.0]


def test_a_parent_is_old_enough_at_the_age_cap(cfg: Config) -> None:
    cap = float(cfg.get("history.secession.age_years"))
    assert [secession.age_term(cfg, y) for y in (0, cap / 2, cap, 3 * cap)] == [0.0, 0.5, 1.0, 1.0]


def test_a_war_parts_sides_more_readily_than_none(cfg: Config) -> None:
    assert (
        secession.relation_term(cfg, "war")
        > secession.relation_term(cfg, "alliance")
        > secession.relation_term(cfg, None)
    )


def test_a_richer_breakaway_scores_more(cfg: Config) -> None:
    full = float(cfg.get("history.secession.prosperity_ratio"))
    assert [secession.prosperity_term(cfg, r) for r in (0.5, 1.0, (1 + full) / 2, full)] == [0.0, 0.0, 0.5, 1.0]


def test_a_distrustful_aggressive_ruler_is_a_poor_keeper() -> None:
    poor, good = _ruler(0, trust=0.0, aggression=1.0), _ruler(0, trust=1.0, aggression=0.0)
    assert (secession.leader_term(poor), secession.leader_term(good)) == (1.0, 0.0)


def test_no_ruler_leaves_the_leader_term_out() -> None:
    assert secession.leader_term(None) is None


def test_a_weak_parent_scores_more_than_a_strong_one(cfg: Config) -> None:
    weak = float(cfg.get("history.secession.weak_strength"))
    assert [secession.strength_term(cfg, r) for r in (weak / 2, weak, 1.0, 2.0)] == [1.0, 1.0, 0.0, 0.0]


def test_no_strength_leaves_the_strength_term_out(cfg: Config) -> None:
    assert secession.strength_term(cfg, None) is None


# --- the mean ---


def test_the_score_is_the_weighted_mean_of_the_terms(cfg: Config) -> None:
    config = copy.deepcopy(cfg)
    config.data["tables"]["secession_terms"]["proximity"]["weight"] = 3.0
    config.data["tables"]["secession_terms"]["size"]["weight"] = 1.0
    assert secession.combine(config, {"proximity": 1.0, "size": 0.0}) == pytest.approx(0.75)


def test_a_term_left_out_does_not_pull_the_mean_down(cfg: Config) -> None:
    assert secession.combine(cfg, {"proximity": 0.8, "leader": None}) == pytest.approx(0.8)


def test_a_term_with_weight_zero_counts_for_nothing(cfg: Config) -> None:
    config = copy.deepcopy(cfg)
    config.data["tables"]["secession_terms"]["size"]["weight"] = 0.0
    assert secession.combine(config, {"proximity": 0.5, "size": 1.0}) == pytest.approx(0.5)


def test_no_applicable_term_scores_nothing(cfg: Config) -> None:
    assert secession.combine(cfg, {"leader": None, "strength": None}) == 0.0


# --- relations ---


def test_sides_find_the_relation_between_them() -> None:
    world = _world()
    relation = secession.relation_between(world, world.realms[0], world.realms[1])
    assert relation is not None and relation.kind == "war"


def test_a_vassal_has_its_lieges_relations() -> None:
    world = _world()
    world.realms[2].liege = 1
    relation = secession.relation_between(world, world.realms[0], world.realms[2])
    assert relation is not None and relation.kind == "war"  # realm 2 stands under realm 1, which is at war with realm 0


def test_sides_of_one_power_have_no_relation() -> None:
    world = _world()
    world.realms[1].liege = 0
    assert secession.relation_between(world, world.realms[0], world.realms[1]) is None


def test_a_war_is_worded_bitter_and_an_alliance_amicable(cfg: Config) -> None:
    world = _world()
    assert (
        secession.relation_tag(world, cfg, world.realms[0], world.realms[1]),
        secession.relation_tag(world, cfg, world.realms[0], world.realms[2]),
    ) == ("bitter", "amicable")


# --- the entry points ---


def test_every_score_is_a_share(cfg: Config) -> None:
    world = _world()
    realms = world.realms
    scores = [
        secession.offshoot_score(world, cfg, realms[1], realms[0], YEAR, 0.4),
        secession.split_score(world, cfg, realms[1], realms[2], YEAR, 100),
        secession.defection_score(world, cfg, world.pois[1], realms[0], realms[1], YEAR, 0.4),
        secession.fracture_score(world, cfg, realms[0], YEAR, 0.4),
    ]
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_a_near_smaller_hostile_neighbour_is_likelier_to_have_broken_away_than_a_far_ally(cfg: Config) -> None:
    world = _world()
    near = secession.offshoot_score(world, cfg, world.realms[1], world.realms[0], YEAR)
    far = secession.offshoot_score(world, cfg, world.realms[2], world.realms[0], YEAR)
    assert near > far


def test_a_weak_parent_is_likelier_to_lose_a_realm_than_a_strong_one(cfg: Config) -> None:
    world = _world()
    weak = secession.offshoot_score(world, cfg, world.realms[1], world.realms[0], YEAR, 0.3)
    strong = secession.offshoot_score(world, cfg, world.realms[1], world.realms[0], YEAR, 1.5)
    assert weak > strong


def test_a_poor_ruler_makes_a_secession_likelier() -> None:
    config = load_config(None)
    poor, good = _world(parent_trust=0.0), _world(parent_trust=1.0)
    assert secession.offshoot_score(poor, config, poor.realms[1], poor.realms[0], YEAR) > secession.offshoot_score(
        good, config, good.realms[1], good.realms[0], YEAR
    )


def test_an_older_parent_is_likelier_to_lose_a_realm_than_a_young_one(cfg: Config) -> None:
    world = _world()
    assert secession.offshoot_score(world, cfg, world.realms[1], world.realms[0], 600) > secession.offshoot_score(
        world, cfg, world.realms[1], world.realms[0], 40
    )


def test_even_halves_split_more_readily_than_uneven_ones(cfg: Config) -> None:
    world = _world()
    uneven = secession.split_score(world, cfg, world.realms[0], world.realms[1], YEAR, 100)
    even_world = _world()
    even_world.realms[1].area_km2 = 1_000_000.0
    assert secession.split_score(even_world, cfg, even_world.realms[0], even_world.realms[1], YEAR, 100) > uneven


def test_a_split_ignores_the_rulers_since_no_parent_lives(cfg: Config) -> None:
    poor, good = _world(parent_trust=0.0), _world(parent_trust=1.0)
    assert secession.split_score(poor, cfg, poor.realms[0], poor.realms[1], YEAR, 100) == secession.split_score(
        good, cfg, good.realms[0], good.realms[1], YEAR, 100
    )


def test_a_defection_is_likelier_from_a_weak_old_owner(cfg: Config) -> None:
    world = _world()
    realms, town = world.realms, world.pois[1]
    weak = secession.defection_score(world, cfg, town, realms[0], realms[1], YEAR, 0.3)
    strong = secession.defection_score(world, cfg, town, realms[0], realms[1], YEAR, 1.5)
    assert weak > strong


def test_a_large_old_realm_with_hostile_neighbours_is_likelier_to_fracture_than_a_small_one(cfg: Config) -> None:
    world = _world()
    assert secession.fracture_score(world, cfg, world.realms[0], YEAR) > secession.fracture_score(
        world, cfg, world.realms[2], YEAR
    )


def test_scoring_does_not_change_the_world(cfg: Config) -> None:
    world = _world()
    before = (copy.deepcopy(world.realms), copy.deepcopy(world.rulers), copy.deepcopy(world.relations))
    secession.offshoot_score(world, cfg, world.realms[1], world.realms[0], YEAR, 0.5)
    secession.fracture_score(world, cfg, world.realms[0], YEAR)
    assert (world.realms, world.rulers, world.relations) == before
