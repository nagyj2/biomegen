"""Tests for clean splits: two touching realms that came of one old realm, decided before the rulers are drawn."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story import secession
from biomegen.util.units import grid_scale
from biomegen.world.entities import Realm
from biomegen.world.world import World

SEEDS = (42, 7)


def _eager(**overrides: object) -> Config:
    """Defaults where only splits happen, and every candidate's chance is its score (chance 1, no cap)."""
    config = load_config(None)
    config.data["history"]["secession"].update({"chance": 1.0, "max_per_world": 99, **overrides})
    for form, weight in (("offshoot", 0.0), ("split", 1.0), ("defection", 0.0)):
        config.data["tables"]["secession_forms"][form]["weight"] = weight
    return config


def _some_plans(world: World, config: Config) -> list[secession.SplitPlan]:
    """The plans of the first seed (of 40) that makes any: a candidate pair splits with the chance of its score."""
    return next((plans for seed in range(40) if (plans := secession.plan_splits(world, config, seed))), [])


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest) -> World:
    return pipeline.generate(_eager(), request.param)


def _splits(world: World):
    return [e for e in world.chronicle if e.kind == "secession" and "split" in e.tags]


# --- the adjacency and the plan on a small map ---


def _strip(*ids: int, founded: tuple[int, ...] | None = None) -> World:
    """One row of realm cells ``ids`` (e.g. 0, 0, 1, 2), each realm founded in the given years."""
    world = World(len(ids), 3, 1, grid_scale(len(ids), 3, (100.0 * len(ids), 300.0), 30.0, 0.0))
    world.realm_id[:] = np.array(ids, dtype=np.int16)[None, :]
    count = max(ids) + 1
    years = founded or tuple(200 + 100 * i for i in range(count))
    world.realms = [Realm(id=i, kind="major", area_km2=100_000.0, pop=100_000, founded=years[i]) for i in range(count)]
    return world


def test_realms_that_touch_are_adjacent() -> None:
    assert secession.adjacent_pairs(_strip(0, 0, 1, 1, 2)) == [(0, 1), (1, 2)]


def test_realms_that_do_not_touch_are_not_adjacent() -> None:
    assert secession.adjacent_pairs(_strip(0, -1, 1)) == []


def test_a_realm_touching_the_sea_only_pairs_with_no_one() -> None:
    assert secession.adjacent_pairs(_strip(0, 0, 0)) == []


def test_a_pair_that_touches_is_planned_to_split_in_the_earlier_year() -> None:
    plans = _some_plans(_strip(0, 1, founded=(300, 500)), _eager())
    assert [(p.first, p.second, p.year) for p in plans] == [(0, 1, 300)]


def test_the_old_realm_began_before_the_split_with_room_for_a_gap() -> None:
    config = _eager()
    gap = int(config.get("history.min_gap_years"))
    first_year = int(config.get("history.first_founding_year"))
    (plan,) = _some_plans(_strip(0, 1, founded=(300, 500)), config)
    assert first_year <= plan.founded <= plan.year - gap


def test_a_split_too_near_the_first_founding_year_is_not_planned() -> None:
    first_year = int(_eager().get("history.first_founding_year"))
    assert secession.plan_splits(_strip(0, 1, founded=(first_year + 5, 500)), _eager(), 1) == []


def test_a_tribe_is_never_part_of_a_split() -> None:
    world = _strip(0, 1)
    world.realms[1].kind = "tribal"
    assert secession.plan_splits(world, _eager(), 1) == []


def test_a_realm_is_in_at_most_one_split() -> None:
    world = _strip(0, 1, 2, 3, founded=(300, 400, 500, 600))
    for seed in range(20):
        members = [i for plan in secession.plan_splits(world, _eager(), seed) for i in (plan.first, plan.second)]
        assert len(members) == len(set(members))


def test_no_chance_plans_no_split() -> None:
    assert secession.plan_splits(_strip(0, 1), _eager(chance=0.0), 1) == []


def test_a_split_form_with_no_weight_plans_no_split() -> None:
    config = _eager()
    config.data["tables"]["secession_forms"]["split"]["weight"] = 0.0
    config.data["tables"]["secession_forms"]["offshoot"]["weight"] = 1.0
    assert [secession.plan_splits(_strip(0, 1), config, seed) for seed in range(20)] == [[]] * 20


def test_the_cap_limits_the_splits() -> None:
    world = _strip(0, 1, 2, 3, founded=(300, 400, 500, 600))
    assert all(len(secession.plan_splits(world, _eager(max_per_world=1), seed)) <= 1 for seed in range(20))


def test_the_plan_is_deterministic() -> None:
    world = _strip(0, 1, 2, 3, founded=(300, 400, 500, 600))
    assert secession.plan_splits(world, _eager(), 5) == secession.plan_splits(world, _eager(), 5)


# --- generated worlds ---


def test_an_eager_world_has_a_split(world: World) -> None:
    assert world.predecessors and _splits(world)


def test_a_predecessor_has_two_children_that_name_it(world: World) -> None:
    for predecessor in world.predecessors:
        assert len(predecessor.children) == 2
        assert all(world.realms[c].predecessor == predecessor.id for c in predecessor.children)


def test_both_children_of_a_split_share_its_year_and_are_split_realms(world: World) -> None:
    for predecessor in world.predecessors:
        for child in (world.realms[c] for c in predecessor.children):
            assert (child.founded, child.origin, child.parent) == (predecessor.split_year, "split", -1)


def test_the_old_realm_lived_before_the_split(world: World) -> None:
    gap = int(load_config(None).get("history.min_gap_years"))
    assert all(p.founded <= p.split_year - gap for p in world.predecessors)


def test_one_secession_event_replaces_both_foundings(world: World) -> None:
    for predecessor in world.predecessors:
        events = [e for e in _splits(world) if e.predecessor_ids == [predecessor.id]]
        assert (
            len(events) == 1
            and events[0].realm_ids == predecessor.children
            and events[0].year == predecessor.split_year
        )
        assert not [e for e in world.chronicle if e.kind == "founding" and set(e.realm_ids) & set(predecessor.children)]


def test_a_split_event_is_the_first_of_each_child(world: World) -> None:
    for predecessor in world.predecessors:
        for child in predecessor.children:
            assert world.events_of(child)[0].kind == "secession"


def test_a_split_text_names_the_old_realm_and_both_new_ones(world: World) -> None:
    for event in _splits(world):
        text = event.text.lower()
        assert world.predecessors[event.predecessor_ids[0]].name.lower() in text
        assert all(
            world.realms[r].short.lower() in text or world.realms[r].name.lower() in text for r in event.realm_ids
        )


def test_a_split_marks_the_old_realm_as_a_predecessor(world: World) -> None:
    for event in _splits(world):
        assert ("predecessor", event.predecessor_ids[0]) in [(kind, ident) for *_, kind, ident in event.refs]


def test_a_split_is_worded_by_the_relation_between_the_halves(world: World) -> None:
    config = load_config(None)
    for event in _splits(world):
        first, second = (world.realms[r] for r in event.realm_ids)
        assert secession.relation_tag(world, config, first, second) in event.tags


def test_the_seats_of_a_split_are_marked_and_dated_by_it(world: World) -> None:
    for event in _splits(world):
        for realm_id in event.realm_ids:
            seat = world.realms[realm_id].seat_poi
            if seat >= 0:
                assert event.id in world.pois[seat].event_ids and world.pois[seat].founded == event.year


def test_each_child_has_its_own_founder_from_the_split_year(world: World) -> None:
    for predecessor in world.predecessors:
        for child in predecessor.children:
            assert world.rulers_of(child)[0].from_year == predecessor.split_year


def test_a_predecessor_is_named_and_has_its_own_colour(world: World) -> None:
    colours = [r.color for r in world.realms] + [f.color for f in world.fallen_realms]
    for predecessor in world.predecessors:
        assert predecessor.name and predecessor.culture and predecessor.color not in colours
        colours.append(predecessor.color)


def test_a_realm_is_in_one_secession_only(world: World) -> None:
    seceded = [r for r in world.realms if r.origin]
    assert all((r.origin == "split") != (r.parent >= 0) for r in seceded)


def test_the_partition_is_untouched_by_a_split(world: World) -> None:
    plain = pipeline.generate(load_config(None), world.seed)
    assert np.array_equal(world.realm_id, plain.realm_id)


def test_the_cap_is_shared_by_splits_and_offshoots() -> None:
    config = _eager(max_per_world=2)
    config.data["tables"]["secession_forms"]["offshoot"]["weight"] = 1.0
    made = pipeline.generate(config, 42)
    assert len([e for e in made.chronicle if e.kind == "secession"]) <= 2


def test_a_switched_off_secession_kind_makes_no_split() -> None:
    config = _eager()
    config.data["history"]["kinds"] = [k for k in config.data["history"]["kinds"] if k != "secession"]
    made = pipeline.generate(config, 42)
    assert made.predecessors == [] and not [r for r in made.realms if r.origin]


def test_the_world_is_deterministic() -> None:
    first, second = pipeline.generate(_eager(), 42), pipeline.generate(_eager(), 42)
    assert [(p.founded, p.split_year, p.children, p.name) for p in first.predecessors] == [
        (p.founded, p.split_year, p.children, p.name) for p in second.predecessors
    ]


def _founding_of(world: World, predecessor_id: int):
    return [e for e in world.chronicle if e.kind == "founding" and e.predecessor_ids == [predecessor_id]]


def test_the_old_realm_has_a_founding_event(world: World) -> None:
    # The split names a realm the chronicle must also have founded.
    assert world.predecessors and all(len(_founding_of(world, p.id)) == 1 for p in world.predecessors)


def test_the_old_realms_founding_is_dated_by_the_predecessor_and_comes_first(world: World) -> None:
    for predecessor in world.predecessors:
        founding = _founding_of(world, predecessor.id)[0]
        split = next(e for e in _splits(world) if e.predecessor_ids == [predecessor.id])
        assert founding.year == predecessor.founded < split.year and founding.id < split.id


def test_the_old_realms_founding_names_it_as_a_predecessor(world: World) -> None:
    for predecessor in world.predecessors:
        founding = _founding_of(world, predecessor.id)[0]
        assert predecessor.name.lower() in founding.text.lower()
        assert ("predecessor", predecessor.id) in [(kind, ident) for *_, kind, ident in founding.refs]


def test_the_old_realms_founding_belongs_to_no_living_realm(world: World) -> None:
    assert all(e.realm_ids == [] for p in world.predecessors for e in _founding_of(world, p.id))


def test_a_realm_the_chronicle_names_in_a_split_was_founded_in_it(world: World) -> None:
    # The report behind this: a split named a Sultanate that no event had founded.
    for event in _splits(world):
        name = world.predecessors[event.predecessor_ids[0]].name
        assert any(e.kind == "founding" and name.lower() in e.text.lower() and e.id < event.id for e in world.chronicle)
