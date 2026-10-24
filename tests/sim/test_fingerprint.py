"""Tests for the simulation fingerprint: stable, order independent, and sensitive to every part of the state."""

from __future__ import annotations

import copy
from collections.abc import Callable

import numpy as np
import pytest

from biomegen.sim.fingerprint import sim_fingerprint
from biomegen.world.entities import POI, ChronicleEvent, Predecessor, Realm, Relation, Ruler
from biomegen.world.manifest import SiteManifest
from biomegen.world.sim_state import Faction, PlaceState, Schedule, SimState


def _state() -> SimState:
    state = SimState(tick=100, ticks_per_month=30, owners=np.array([[0, -1], [1, 1]], dtype=np.int16))
    state.factions[0] = Faction(
        0,
        ruler_id=1,
        traits={"aggression": 0.25, "greed": 0.5},
        liege=-1,
        seat_poi=2,
        pop=100,
        schedule={"economy": Schedule(130, 1, 100)},
    )
    state.factions[1] = Faction(1, liege=0)
    state.places[2] = PlaceState(owner=0, pop=40, stock={"food": 3})
    state.manifests[2] = SiteManifest("village", 5, 1, False)
    state.relations[(0, 1)] = Relation(0, 1, "war", border_km=12.5, attacker=0)
    state.events.append(ChronicleEvent(0, 1201, "war", [0, 1], month=2, tick=14425))
    return state


def test_a_fingerprint_is_a_hex_digest() -> None:
    assert len(sim_fingerprint(_state())) == 32 and int(sim_fingerprint(_state()), 16) >= 0


def test_the_same_state_has_the_same_fingerprint() -> None:
    assert sim_fingerprint(_state()) == sim_fingerprint(_state())


def test_a_copy_of_a_state_has_its_fingerprint() -> None:
    state = _state()
    assert sim_fingerprint(copy.deepcopy(state)) == sim_fingerprint(state)


def test_the_revision_is_not_part_of_the_fingerprint() -> None:
    # It counts cache invalidations: two runs that reach one state may not have invalidated the same number of times.
    state = _state()
    other = _state()
    other.revision = 9
    assert sim_fingerprint(state) == sim_fingerprint(other)


def test_the_order_a_mapping_was_filled_in_does_not_matter() -> None:
    state, other = _state(), _state()
    other.factions = {1: other.factions[1], 0: other.factions[0]}
    assert sim_fingerprint(state) == sim_fingerprint(other)


def _tick(s: SimState) -> None:
    s.tick += 1


def _month_length(s: SimState) -> None:
    s.ticks_per_month = 12


def _owner(s: SimState) -> None:
    s.owners[0, 1] = 1


def _owner_dtype(s: SimState) -> None:
    s.owners = s.owners.astype(np.int32)


def _owner_shape(s: SimState) -> None:
    s.owners = s.owners.reshape(1, 4)


def _trait(s: SimState) -> None:
    s.factions[0].traits["greed"] = 0.5000001


def _ruler(s: SimState) -> None:
    s.factions[0].ruler_id = 2


def _liege(s: SimState) -> None:
    s.factions[1].liege = -1


def _schedule(s: SimState) -> None:
    s.factions[0].schedule["economy"].next_tick += 1


def _cadence(s: SimState) -> None:
    s.factions[0].schedule["strategy"] = Schedule(200)


def _faction(s: SimState) -> None:
    s.factions[2] = Faction(2)


def _stock(s: SimState) -> None:
    s.places[2].stock["food"] = 4


def _resource(s: SimState) -> None:
    s.places[2].stock["wood"] = 0


def _place_owner(s: SimState) -> None:
    s.places[2].owner = 1


def _place_pop(s: SimState) -> None:
    s.places[2].pop += 1


def _manifest(s: SimState) -> None:
    s.manifests[2] = SiteManifest("village", 6, 1, False)


def _relation_kind(s: SimState) -> None:
    s.relations[(0, 1)].kind = "rivalry"


def _relation_border(s: SimState) -> None:
    s.relations[(0, 1)].border_km = 12.6


def _event(s: SimState) -> None:
    s.events.append(ChronicleEvent(1, 1201, "peace", [0, 1], month=3, tick=14426))


def _event_text(s: SimState) -> None:
    s.events[0].text = "A war began."


def _ruler_made(s: SimState) -> None:
    s.rulers.append(Ruler(5, 0, 1201, None, "x"))


def _predecessor(s: SimState) -> None:
    s.predecessors.append(Predecessor(0, 1, 2))


def _realm(s: SimState) -> None:
    s.realms.append(Realm(id=3, kind="tribal"))


def _poi(s: SimState) -> None:
    s.pois.append(POI(kind="hamlet", x=1, y=2, interior_seed=3))


CHANGES: list[Callable[[SimState], None]] = [
    _tick,
    _month_length,
    _owner,
    _owner_dtype,
    _owner_shape,
    _trait,
    _ruler,
    _liege,
    _schedule,
    _cadence,
    _faction,
    _stock,
    _resource,
    _place_owner,
    _place_pop,
    _manifest,
    _relation_kind,
    _relation_border,
    _event,
    _event_text,
    _ruler_made,
    _predecessor,
    _realm,
    _poi,
]


@pytest.mark.parametrize("change", CHANGES, ids=[change.__name__.strip("_") for change in CHANGES])
def test_every_part_of_the_state_moves_the_fingerprint(change: Callable[[SimState], None]) -> None:
    state = _state()
    before = sim_fingerprint(state)
    change(state)
    assert sim_fingerprint(state) != before


def test_two_names_that_split_differently_are_different() -> None:
    # Text is length prefixed: ("ab", "c") and ("a", "bc") cannot collide.
    first, second = _state(), _state()
    first.factions[0].traits = {"ab": 0.5, "c": 0.5}
    second.factions[0].traits = {"a": 0.5, "bc": 0.5}
    assert sim_fingerprint(first) != sim_fingerprint(second)


def test_a_value_with_no_encoding_is_an_error() -> None:
    state = _state()
    state.places[2].stock["food"] = object()  # type: ignore[assignment]
    with pytest.raises(TypeError, match="object"):
        sim_fingerprint(state)
