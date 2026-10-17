"""Tests for what a power was like at a moment (``world/powers.py``)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.entities import POI, ChronicleEvent, FallenRealm, Realm, Ruler
from biomegen.world.powers import power_profile
from biomegen.world.territory import WILD, TerritoryChange, fallen_owner
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _cells(*columns: int) -> np.ndarray:
    return np.array(sorted(y * 8 + x for y in range(2) for x in columns), dtype=np.int32)


def _world() -> World:
    """Realm 0 (columns 0-3, a capital founded 100 and a town 200) and realm 1 (columns 4-5, a vassal of 0 from 400);
    a fallen realm held column 6-7 until 300. Realm 0 has two rulers; the two realms are at war from 350 to 380."""
    world = World(8, 2, 1)
    world.realms = [
        Realm(id=0, kind="major", name="Kingdom of Aldor", short="Aldor", seat_poi=0, founded=100, color=(200, 0, 0)),
        Realm(id=1, kind="city_state", name="Wend", short="Wend", founded=150, liege=0, color=(0, 0, 200)),
    ]
    world.realm_id[:, :4], world.realm_id[:, 4:6] = 0, 1
    world.fallen_realms = [FallenRealm(id=0, location=(6, 0), founded=50, fell=300, name="Old Hork", color=(9, 9, 9))]
    world.pois = [
        POI(kind="capital", x=1, y=0, interior_seed=1, name="Aldburg", civilized=True, pop=50000, event_ids=[0]),
        POI(kind="town", x=3, y=1, interior_seed=1, name="Wendham", civilized=True, pop=3000, event_ids=[1]),
    ]
    world.rulers = [
        Ruler(id=0, realm_id=0, from_year=100, to_year=300, style="martial", name="King Bran"),
        Ruler(id=1, realm_id=0, from_year=300, to_year=None, style="gentle", name="Queen Ede"),
    ]
    world.chronicle = [
        ChronicleEvent(0, 100, "founding", [0], [0], month=1),
        ChronicleEvent(1, 200, "settling", [0], [1], month=1),
        ChronicleEvent(2, 350, "war", [0, 1], tags=("ended",), month=1),
        ChronicleEvent(3, 380, "peace", [0, 1], month=1),
        ChronicleEvent(4, 400, "conquest", [1, 0], tags=("vassalage",), month=1),
        ChronicleEvent(5, 120, "rivalry", [0, 1], tags=("rivalry",), month=1),
    ]
    world.territory = [
        TerritoryChange(50, 1, "founding", _cells(6, 7), WILD, fallen_owner(0)),
        TerritoryChange(100, 1, "founding", _cells(0, 1, 2, 3), WILD, 0),
        TerritoryChange(150, 1, "founding", _cells(4, 5), WILD, 1),
        TerritoryChange(300, 1, "fall", _cells(6, 7), fallen_owner(0), WILD),
    ]
    return world


def test_a_realm_has_its_ruler_and_style_of_the_moment(cfg: Config) -> None:
    early, late = power_profile(_world(), cfg, 0, (250, 1)), power_profile(_world(), cfg, 0, (320, 1))
    assert (early.ruler, late.ruler, late.ruler_since) == ("King Bran", "Queen Ede", 300)
    assert early.style != late.style


def test_a_realm_has_only_the_settlements_that_stood_then(cfg: Config) -> None:
    before, after = power_profile(_world(), cfg, 0, (150, 1)), power_profile(_world(), cfg, 0, (250, 1))
    assert before.settlements == [("Capital", 1)] and after.settlements == [("Capital", 1), ("Town", 1)]
    assert (before.people, after.people) == (50000, 53000)


def test_the_land_and_its_share_are_those_of_the_moment(cfg: Config) -> None:
    profile = power_profile(_world(), cfg, 0, (250, 1))
    assert profile.cells == 8 and 0.0 < profile.share < 1.0


def test_a_bigger_power_is_stronger(cfg: Config) -> None:
    world = _world()
    assert power_profile(world, cfg, 0, (250, 1)).strength > power_profile(world, cfg, 1, (250, 1)).strength


def test_a_war_is_a_tie_while_it_lasts_and_not_after(cfg: Config) -> None:
    world = _world()
    during = [t for t in power_profile(world, cfg, 0, (360, 1)).ties if t[0] == "war"]
    after = [t for t in power_profile(world, cfg, 0, (390, 1)).ties if t[0] == "war"]
    assert during == [("war", "Wend", 350)] and after == []


def test_a_rivalry_is_a_tie_from_its_year(cfg: Config) -> None:
    world = _world()
    assert ("rivalry", "Wend", 120) in power_profile(world, cfg, 0, (130, 1)).ties
    assert not power_profile(world, cfg, 0, (110, 1)).ties


def test_a_vassal_names_its_liege_only_after_the_conquest(cfg: Config) -> None:
    world = _world()
    assert (
        power_profile(world, cfg, 1, (390, 1)).liege == "" and power_profile(world, cfg, 1, (410, 1)).liege == "Aldor"
    )
    assert power_profile(world, cfg, 0, (410, 1)).vassals == ["Wend"]


def test_a_realm_does_not_exist_before_it_is_founded(cfg: Config) -> None:
    assert not power_profile(_world(), cfg, 0, (50, 1)).exists and power_profile(_world(), cfg, 0, (150, 1)).exists


def test_a_fallen_realm_exists_only_in_its_life(cfg: Config) -> None:
    world = _world()
    alive, dead = (
        power_profile(world, cfg, fallen_owner(0), (200, 1)),
        power_profile(world, cfg, fallen_owner(0), (310, 1)),
    )
    assert (alive.exists, alive.kind, alive.cells, dead.exists, dead.cells) == (True, "fallen realm", 4, False, 0)
