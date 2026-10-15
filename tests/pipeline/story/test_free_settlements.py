"""Tests for free settlements in the history: their settling events and the remnants of fallen realms."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.entities import POI
from biomegen.world.world import World

SEED = 1337  # seven free settlements, three of them remnants


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


def _settling(world: World, index: int):
    return [e for e in world.chronicle if e.kind == "settling" and e.poi_ids == [index] and "free" in e.tags]


def _remnants(world: World):
    return [(i, e) for e in world.chronicle if "remnant" in e.tags for i in e.poi_ids]


def test_every_free_city_and_town_has_a_free_settling_event(world: World, cfg: Config) -> None:
    kinds = set(cfg.get("history.settle_kinds"))
    free = [i for i, p in enumerate(world.pois) if p.free and p.kind in kinds]
    assert free and all(len(_settling(world, i)) == 1 for i in free)


def test_a_free_village_has_no_settling_event(world: World, cfg: Config) -> None:
    villages = [i for i, p in enumerate(world.pois) if p.free and p.kind not in cfg.get("history.settle_kinds")]
    assert villages and not any(_settling(world, i) for i in villages)


def test_a_free_settling_event_belongs_to_no_realm(world: World) -> None:
    assert all(e.realm_ids == [] for e in world.chronicle if "free" in e.tags)


def test_a_settlement_a_realm_holds_has_no_free_event(world: World) -> None:
    held = {i for i, p in enumerate(world.pois) if p.civilized and not p.free}
    assert not any(set(e.poi_ids) & held for e in world.chronicle if "free" in e.tags)


def test_a_remnant_is_founded_inside_the_life_of_its_fallen_realm(world: World) -> None:
    remnants = _remnants(world)
    assert remnants
    for index, event in remnants:
        fallen = world.fallen_realms[event.fallen_ids[0]]
        assert fallen.founded <= world.pois[index].founded <= fallen.fell


def test_a_remnant_is_marked_by_the_fall_it_outlived(world: World) -> None:
    for index, event in _remnants(world):
        fall = next(e for e in world.chronicle if e.kind == "fall" and e.fallen_ids == event.fallen_ids)
        assert fall.id in world.pois[index].event_ids


def test_a_remnants_text_names_its_fallen_realm(world: World) -> None:
    for _index, event in _remnants(world):
        assert world.fallen_realms[event.fallen_ids[0]].name in event.text


def test_a_remnant_stands_near_the_fallen_realms_site(world: World, cfg: Config) -> None:
    limit = float(cfg.get("history.remnant_km"))
    for index, event in _remnants(world):
        poi, (fx, fy) = world.pois[index], world.fallen_realms[event.fallen_ids[0]].location
        assert world.scale.distance_km(poi.x, poi.y, fx, fy) <= limit


def test_a_free_event_that_is_no_remnant_names_no_fallen_realm(world: World) -> None:
    plain = [e for e in world.chronicle if "free" in e.tags and "remnant" not in e.tags]
    assert plain and all(e.fallen_ids == [] for e in plain)


def test_no_remnant_without_a_remnant_distance(cfg: Config) -> None:
    near_none = load_config(None)
    near_none.data["history"]["remnant_km"] = 0.0
    made = pipeline.generate(near_none, SEED)
    assert not [e for e in made.chronicle if "remnant" in e.tags]


def test_free_events_are_in_the_ledger_order(world: World) -> None:
    assert [e.id for e in world.chronicle] == list(range(len(world.chronicle)))


def test_a_free_settlement_is_named_in_its_event_text(world: World) -> None:
    for event in world.chronicle:
        if "free" in event.tags:
            poi: POI = world.pois[event.poi_ids[0]]
            assert poi.name in event.text
