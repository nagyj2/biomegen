"""Tests for the territory planner: expansions and foundings found by walking back from the present partition."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.world.territory import WILD, fallen_owner, predecessor_owner
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _expansions(world: World):  # the annexations of living realms
    return [event for event in world.chronicle if event.kind == "expansion" and event.realm_ids]


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


def test_with_expansion_off_no_land_is_annexed(cfg: Config) -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = [k for k in config.get("history.kinds") if k != "expansion"]
    world = pipeline.generate(config, 7)
    assert not [e for e in world.chronicle if e.kind == "expansion"]
    assert not [c for c in world.territory if c.kind == "expansion"]


# --- fallen realms ----------------------------------------------------------------------------------------------


def _just_before(world: World, year: int, month: int) -> np.ndarray:
    return world.owners_at(year, month - 1) if month > 1 else world.owners_at(year - 1)


def _falls(world: World):
    return [event for event in world.chronicle if event.kind == "fall"]


def test_a_fallen_realm_holds_land_just_before_it_falls(world: World) -> None:
    held = [int((_just_before(world, e.year, e.month) == fallen_owner(e.fallen_ids[0])).sum()) for e in _falls(world)]
    assert held and all(count >= 3 for count in held)


def test_a_fallen_realm_holds_nothing_once_it_has_fallen(world: World) -> None:
    assert all(not (world.owners_at(e.year, e.month) == fallen_owner(e.fallen_ids[0])).any() for e in _falls(world))


def test_a_fallen_realm_holds_nothing_before_it_is_founded(world: World) -> None:
    for fallen in world.fallen_realms:
        founding = next(e for e in world.chronicle if e.kind == "founding" and e.fallen_ids == [fallen.id])
        assert not (_just_before(world, founding.year, founding.month) == fallen_owner(fallen.id)).any()


def test_a_fallen_realm_holds_its_ruins_before_it_falls(world: World) -> None:
    for event in _falls(world):
        x, y = world.fallen_realms[event.fallen_ids[0]].location
        assert _just_before(world, event.year, event.month)[y, x] == fallen_owner(event.fallen_ids[0])


def test_a_fallen_realms_land_stays_on_the_landmass_of_its_ruins(world: World) -> None:
    for event in _falls(world):
        x, y = world.fallen_realms[event.fallen_ids[0]].location
        owner = fallen_owner(event.fallen_ids[0])
        ys, xs = np.nonzero(_just_before(world, event.year, event.month) == owner)
        assert (world.landmass_id[ys, xs] == world.landmass_id[y, x]).all()


def test_a_fall_hands_the_land_to_the_wild_or_the_victor(world: World) -> None:
    for change in (c for c in world.territory if c.kind == "fall"):
        event = world.chronicle[change.event_id]
        assert change.to_owner == WILD or change.to_owner in event.realm_ids


def test_a_fallen_realms_expansion_takes_wild_land_for_it(world: World) -> None:
    by_event = {c.event_id: c for c in world.territory if c.kind == "expansion"}
    for event in (e for e in world.chronicle if e.kind == "expansion" and e.fallen_ids):
        change = by_event[event.id]
        assert (change.from_owner, change.to_owner) == (WILD, fallen_owner(event.fallen_ids[0]))


def test_a_fallen_realm_expands_only_inside_its_life(world: World) -> None:
    for event in (e for e in world.chronicle if e.kind == "expansion" and e.fallen_ids):
        fallen = world.fallen_realms[event.fallen_ids[0]]
        assert fallen.founded < event.year < fallen.fell


# --- battles, peaces and secessions ------------------------------------------------------------------------------


def _strips(world: World):
    return [c for c in world.territory if c.kind in ("battle", "peace")]


def test_a_strip_passes_from_the_loser_to_the_winner(world: World) -> None:
    for change in _strips(world):
        event = world.chronicle[change.event_id]
        owners = {change.from_owner, change.to_owner}
        assert len(owners) == 2 and owners <= {*event.realm_ids, *(fallen_owner(f) for f in event.fallen_ids)}


def test_a_strip_lies_along_the_losers_land(world: World) -> None:
    # Some cell of the strip is next to (or one cell from) a cell the loser held when the strip changed hands.
    for change in _strips(world):
        before = _just_before(world, change.year, change.month)
        width = world.width
        ys, xs = change.cells // width, change.cells % width
        loser = before == change.from_owner
        near = np.zeros_like(loser)
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                near |= np.roll(np.roll(loser, dy, axis=0), dx, axis=1)
        assert near[ys, xs].any()


def test_a_strip_was_the_winners_just_after_and_the_losers_just_before(world: World) -> None:
    for change in _strips(world):
        width = world.width
        ys, xs = change.cells // width, change.cells % width
        before = _just_before(world, change.year, change.month)
        after = world.owners_at(change.year, change.month)
        assert (before[ys, xs] == change.from_owner).all() and (after[ys, xs] == change.to_owner).all()


def _first_events(world: World):
    """Each living realm with the moment of its first event (founding or the secession that made it)."""
    first = {}
    for event in world.chronicle:
        if event.kind == "founding" and event.realm_ids and not event.fallen_ids:
            first.setdefault(event.realm_ids[0], event)
        elif event.kind == "secession" and "defection" not in event.tags:
            for realm_id in event.realm_ids if event.predecessor_ids else event.realm_ids[:1]:
                first.setdefault(realm_id, event)
    return first


def test_every_realm_holds_no_land_before_its_first_event(world: World) -> None:
    for realm_id, event in _first_events(world).items():
        assert not (_just_before(world, event.year, event.month) == realm_id).any(), realm_id


def test_every_realm_has_a_first_event(world: World) -> None:
    assert set(_first_events(world)) == {realm.id for realm in world.realms}


@pytest.fixture(scope="module")
def offshoot_world(cfg: Config) -> World:
    return pipeline.generate(cfg, 15)


def test_an_offshoot_took_its_first_land_from_its_parent(offshoot_world: World) -> None:
    world = offshoot_world
    child = next(r for r in world.realms if r.origin == "offshoot")
    change = next(c for c in world.territory if c.kind == "secession" and c.to_owner == child.id)
    ys, xs = change.cells // world.width, change.cells % world.width
    before = _just_before(world, change.year, change.month)
    assert change.from_owner == child.parent and (before[ys, xs] == child.parent).all()


@pytest.fixture(scope="module")
def split_world() -> World:
    config = load_config(None)
    config.data["history"]["secession"].update({"chance": 1.0, "max_per_world": 99})
    for form, weight in (("offshoot", 0.0), ("split", 1.0), ("defection", 0.0)):
        config.data["tables"]["secession_forms"][form]["weight"] = weight
    return pipeline.generate(config, 1)


def test_a_split_world_replays_to_its_present(split_world: World) -> None:
    assert np.array_equal(split_world.owners_at(split_world.year), split_world.realm_id)


def test_a_predecessor_held_the_land_of_its_two_children_before_the_split(split_world: World) -> None:
    world = split_world
    for predecessor in world.predecessors:
        event = next(e for e in world.chronicle if e.kind == "secession" and e.predecessor_ids == [predecessor.id])
        before = _just_before(world, event.year, event.month)
        after = world.owners_at(event.year, event.month)
        held = int((before == predecessor_owner(predecessor.id)).sum())
        assert held == sum(int((after == child).sum()) for child in predecessor.children) and held > 0


def test_a_predecessor_holds_nothing_before_it_is_founded_or_after_the_split(split_world: World) -> None:
    world = split_world
    for predecessor in world.predecessors:
        owner = predecessor_owner(predecessor.id)
        founding = next(e for e in world.chronicle if e.kind == "founding" and e.predecessor_ids == [predecessor.id])
        split = next(e for e in world.chronicle if e.kind == "secession" and e.predecessor_ids == [predecessor.id])
        assert not (_just_before(world, founding.year, founding.month) == owner).any()
        assert not (world.owners_at(split.year, split.month) == owner).any()
