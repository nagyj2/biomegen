"""Tests for the territory planner: expansions and foundings found by walking back from the present partition."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.territory import WILD
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _expansions(world: World):
    return [event for event in world.chronicle if event.kind == "expansion"]


def test_a_world_has_expansions(world: World) -> None:
    assert _expansions(world)


def test_changes_are_ordered_by_moment(world: World) -> None:
    moments = [change.moment for change in world.territory]
    assert moments == sorted(moments)


def test_every_change_has_the_month_and_id_of_its_event(world: World) -> None:
    assert all(
        world.chronicle[c.event_id].month == c.month and world.chronicle[c.event_id].year == c.year
        for c in world.territory
    )


def test_every_expansion_took_wild_land_for_its_realm(world: World) -> None:
    by_event = {c.event_id: c for c in world.territory if c.kind == "expansion"}
    assert all(
        by_event[e.id].from_owner == WILD and [by_event[e.id].to_owner] == e.realm_ids for e in _expansions(world)
    )


def test_replaying_every_change_gives_the_present_partition(world: World) -> None:
    assert np.array_equal(world.owners_at(world.year), world.realm_id)


def test_an_expanding_realm_holds_less_before_each_annexation(world: World) -> None:
    for change in (c for c in world.territory if c.kind == "expansion"):
        before = world.owners_at(change.year, change.month - 1 if change.month > 1 else None)
        if change.month == 1:
            before = world.owners_at(change.year - 1)
        width = world.width
        assert (before[change.cells // width, change.cells % width] == WILD).all()


def test_a_realm_holds_no_land_before_its_founding(world: World) -> None:
    founding = {e.realm_ids[0]: e for e in world.chronicle if e.kind == "founding" and not e.fallen_ids}
    for realm_id, event in founding.items():
        before = world.owners_at(event.year, event.month - 1) if event.month > 1 else world.owners_at(event.year - 1)
        assert not (before == realm_id).any(), realm_id


def test_a_realm_starts_with_at_least_its_core_share(world: World, cfg: Config) -> None:
    share = cfg.get("history.territory.core_share")
    for event in (e for e in world.chronicle if e.kind == "founding" and not e.fallen_ids):
        realm_id = event.realm_ids[0]
        final = int((world.realm_id == realm_id).sum())
        start = int((world.owners_at(event.year, event.month) == realm_id).sum())
        assert start >= min(final, int(share * final)), realm_id


def test_an_expansion_comes_after_the_founding_and_the_gap(world: World, cfg: Config) -> None:
    gap = cfg.get("history.min_gap_years")
    for event in _expansions(world):
        assert event.year >= world.realms[event.realm_ids[0]].founded + gap and event.year <= world.year


def test_the_territory_is_deterministic(cfg: Config) -> None:
    first, second = pipeline.generate(cfg, 7), pipeline.generate(cfg, 7)
    assert [(c.year, c.month, c.kind, c.from_owner, c.to_owner, c.cells.tolist()) for c in first.territory] == [
        (c.year, c.month, c.kind, c.from_owner, c.to_owner, c.cells.tolist()) for c in second.territory
    ]


def test_with_expansion_off_a_realm_is_founded_whole(cfg: Config) -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = [k for k in config.get("history.kinds") if k != "expansion"]
    world = pipeline.generate(config, 7)
    founding = [c for c in world.territory if c.kind == "founding"]
    assert not _expansions(world) and all(len(c.cells) == int((world.realm_id == c.to_owner).sum()) for c in founding)
