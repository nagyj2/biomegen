"""Tests for when a point of interest appears on the map of the past (``world/lifespans.py``)."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.entities import POI, ChronicleEvent
from biomegen.world.lifespans import poi_appears, visible_pois
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _world() -> World:
    """A world with a fall, a battle, a war and a settling in its chronicle and a POI of each kind linked to them."""
    world = World(10, 10, 1)
    world.chronicle = [
        ChronicleEvent(0, 100, "founding", [0], month=3),
        ChronicleEvent(1, 150, "settling", [0], month=5),
        ChronicleEvent(2, 200, "fall", fallen_ids=[0], month=7),
        ChronicleEvent(3, 220, "battle", [0, 1], month=2),
        ChronicleEvent(4, 240, "war", [0, 1], month=9),
    ]
    world.pois = [
        POI(kind="capital", x=0, y=0, interior_seed=1, civilized=True, event_ids=[0], founded=100),
        POI(kind="town", x=1, y=0, interior_seed=1, civilized=True, event_ids=[1], founded=150),
        POI(kind="village", x=2, y=0, interior_seed=1, civilized=True, founded=170),
        POI(kind="ruin", x=3, y=0, interior_seed=1, event_ids=[2], founded=20),
        POI(kind="ruin", x=4, y=0, interior_seed=1),
        POI(kind="battlefield", x=5, y=0, interior_seed=1, event_ids=[3], founded=220),
        POI(kind="watchtower", x=6, y=0, interior_seed=1, event_ids=[4], founded=300),
        POI(kind="camp", x=7, y=0, interior_seed=1),
    ]
    return world


def test_a_capital_appears_at_the_founding_of_its_realm(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 0) == (100, 3)


def test_a_settlement_appears_at_its_settling(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 1) == (150, 5)


def test_a_village_with_no_event_appears_in_its_founding_year(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 2) == (170, 1)


def test_a_ruin_appears_when_its_realm_falls_not_when_it_was_founded(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 3) == (200, 7)


def test_an_ancient_ruin_is_always_there(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 4) is None


def test_a_battlefield_appears_at_its_battle(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 5) == (220, 2)


def test_a_watchtower_appears_when_its_war_is_declared(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 6) == (240, 9)


def test_a_camp_with_no_history_is_always_there(cfg: Config) -> None:
    assert poi_appears(_world(), cfg, 7) is None


def test_the_visible_pois_at_a_moment_are_those_that_stand_by_then(cfg: Config) -> None:
    visible = visible_pois(_world(), cfg, (210, 1))
    assert visible.tolist() == [True, True, True, True, True, False, False, True]


def test_before_anything_only_the_ancient_stand(cfg: Config) -> None:
    visible = visible_pois(_world(), cfg, (1, 1))
    assert visible.tolist() == [False, False, False, False, True, False, False, True]
