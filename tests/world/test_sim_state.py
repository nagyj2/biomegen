"""Tests for the simulation state's shape, its time base and its id rules."""

from __future__ import annotations

import numpy as np

from biomegen.world.entities import POI, ChronicleEvent, Predecessor, Realm, Ruler, month_tick
from biomegen.world.sim_state import Faction, PlaceState, Schedule, SimState, present_tick
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
        state.realms,
        state.pois,
        state.manifests,
        state.factions,
        state.places,
        state.relations,
    ) == (0, 0, [], [], [], [], [], {}, {}, {}, {})


def test_a_new_state_has_an_empty_owner_grid() -> None:
    assert SimState().owners.shape == (0, 0)


def test_two_states_do_not_share_their_lists() -> None:
    first, second = SimState(), SimState()
    first.pois.append(_poi())
    assert second.pois == []


def test_two_states_do_not_share_their_maps() -> None:
    first, second = SimState(), SimState()
    first.factions[0] = Faction(realm_id=0)
    assert second.factions == {}


def test_a_new_ruler_id_continues_after_the_generated_rulers() -> None:
    # The state's own rulers follow the world's, so an id means the same thing to every reader.
    world = World(4, 4, 1)
    world.rulers = [Ruler(0, 0, 0, None, "x"), Ruler(1, 0, 10, None, "x")]
    state = SimState(rulers=[Ruler(2, 0, 20, None, "x")])
    assert state.next_ruler_id(world) == 3


def test_a_new_predecessor_id_continues_after_the_generated_ones() -> None:
    world = World(4, 4, 1)
    world.predecessors = [Predecessor(0, 1, 2)]
    assert SimState().next_predecessor_id(world) == 1


def test_a_new_realm_id_continues_after_the_generated_realms() -> None:
    world = World(4, 4, 1)
    world.realms = [Realm(id=0, kind="major"), Realm(id=1, kind="tribal")]
    state = SimState(realms=[Realm(id=2, kind="city_state")])
    assert state.next_realm_id(world) == 3


def test_a_new_poi_index_continues_after_the_standing_and_the_vanished() -> None:
    # World.place numbers the vanished POIs after the standing ones, so a minted POI comes after both.
    world = World(4, 4, 1)
    world.pois = [_poi(), _poi()]
    world.vanished = [_poi()]
    state = SimState(pois=[_poi()])
    assert state.next_poi_index(world) == 4


def test_the_month_is_the_tick_over_the_ticks_per_month() -> None:
    assert SimState(tick=95, ticks_per_month=30).month() == 3


def test_the_moment_is_a_year_and_a_month_counted_from_one() -> None:
    # Absolute month 14 with twelve months a year is year 1, month 3.
    assert SimState(tick=14 * 30 + 7, ticks_per_month=30).moment(12) == (1, 3)


def test_the_moment_agrees_with_how_an_event_counts_its_month() -> None:
    # A chronicle event's tick is month_tick(year, month); a state at that month reads the same year and month.
    state = SimState(tick=month_tick(1203, 7, 12) * 30, ticks_per_month=30)
    assert state.moment(12) == (1203, 7)


def test_the_start_tick_opens_month_one_of_the_next_year() -> None:
    # The present is the end of the last month of World.year; the first tick advanced opens the next year's first month.
    state = SimState(tick=present_tick(1200, 12, 30), ticks_per_month=30)
    assert state.moment(12) == (1201, 1)


def test_the_start_tick_is_on_a_month_boundary() -> None:
    assert present_tick(1200, 12, 30) % 30 == 0


def test_a_schedule_starts_with_no_checks_made() -> None:
    assert (Schedule(next_tick=5).count, Schedule(next_tick=5).last_tick) == (0, 0)


def test_a_faction_defaults_to_no_ruler_no_liege_and_no_schedule() -> None:
    faction = Faction(realm_id=3)
    assert (faction.ruler_id, faction.liege, faction.seat_poi, faction.schedule) == (-1, -1, -1, {})


def test_a_place_starts_with_an_empty_stock() -> None:
    assert PlaceState(owner=1, pop=40).stock == {}


def test_the_event_log_shares_the_states_event_list() -> None:
    # Appending to the log adds to the state's own list: one store for the continuation.
    world = World(4, 4, 1)
    state = SimState()
    state.event_log(world).append(ChronicleEvent(-1, 5, "treaty", month=2))
    assert [event.id for event in state.events] == [0]


def test_the_owner_grid_keeps_its_dtype() -> None:
    state = SimState(owners=np.full((2, 3), -1, dtype=np.int16))
    assert state.owners.dtype == np.int16
