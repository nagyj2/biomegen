"""Tests for the simulation state's shape and its id rules."""

from __future__ import annotations

from biomegen.world.entities import POI, Predecessor, Ruler
from biomegen.world.sim_state import SimState
from biomegen.world.world import World


def _poi() -> POI:
    return POI(kind="hamlet", x=0, y=0, interior_seed=1)


def test_a_new_state_is_empty() -> None:
    state = SimState()
    assert (
        state.tick,
        state.revision,
        state.events,
        state.rulers,
        state.predecessors,
        state.pois,
        state.manifests,
    ) == (
        0,
        0,
        [],
        [],
        [],
        [],
        {},
    )


def test_two_states_do_not_share_their_lists() -> None:
    first, second = SimState(), SimState()
    first.pois.append(_poi())
    assert second.pois == []


def test_a_new_ruler_id_continues_after_the_generated_rulers() -> None:
    world = World(4, 4, 1)
    world.rulers = [Ruler(0, 0, 0, None, "x"), Ruler(1, 0, 10, None, "x")]
    state = SimState(rulers=[Ruler(2, 0, 20, None, "x")])
    assert state.next_ruler_id(world) == 3


def test_a_new_predecessor_id_continues_after_the_generated_ones() -> None:
    world = World(4, 4, 1)
    world.predecessors = [Predecessor(0, 1, 2)]
    assert SimState().next_predecessor_id(world) == 1


def test_a_new_poi_index_continues_after_the_standing_and_the_vanished() -> None:
    # World.place numbers the vanished POIs after the standing ones, so a minted POI comes after both.
    world = World(4, 4, 1)
    world.pois = [_poi(), _poi()]
    world.vanished = [_poi()]
    state = SimState(pois=[_poi()])
    assert state.next_poi_index(world) == 4
