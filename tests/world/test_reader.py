"""Tests for the world reader: the base objects themselves until the simulation changes one, then a copy of it."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.sim.hydrate import hydrate
from biomegen.world.entities import POI, ChronicleEvent, Predecessor, Realm, Relation, Ruler
from biomegen.world.manifest import SiteManifest
from biomegen.world.reader import WorldReader
from biomegen.world.sim_state import Faction, PlaceState, SimState
from biomegen.world.world import World


def _world() -> World:
    """A 6x4 world: realm 0 on the left, its vassal 1 on the right, a town, a tower and a vanished watchtower."""
    world = World(6, 4, 1)
    world.realm_id[:, :3] = 0
    world.realm_id[:, 3:] = 1
    world.realms = [
        Realm(id=0, kind="major", seat_poi=0, name="Aria", pop=500, vassals=[1], ruler="King A"),
        Realm(id=1, kind="city_state", name="Bex", pop=200, liege=0, ruler="Mayor B"),
    ]
    world.rulers = [Ruler(0, 0, 0, None, "x", name="King A"), Ruler(1, 1, 0, None, "x", name="Mayor B")]
    world.predecessors = [Predecessor(0, 1, 2)]
    world.pois = [
        POI(kind="town", x=1, y=1, interior_seed=1, civilized=True, realm_id=0, pop=300),
        POI(kind="tower", x=4, y=2, interior_seed=2, realm_id=1),
    ]
    world.poi_index[1, 1], world.poi_index[2, 4] = 0, 1
    world.vanished = [POI(kind="watchtower", x=5, y=0, interior_seed=3)]
    world.relations = [Relation(0, 1, "alliance", border_km=10.0)]
    world.chronicle = [ChronicleEvent(0, 100, "founding", [0], month=1)]
    return world


def _state(world: World) -> SimState:
    """A state equal to the world as generated: the owners, a faction per realm, a place per populated POI."""
    state = SimState(tick=500, ticks_per_month=30, owners=world.realm_id.copy())
    for realm in world.realms:
        state.factions[realm.id] = Faction(
            realm.id, ruler_id=realm.id, liege=realm.liege, seat_poi=realm.seat_poi, pop=realm.pop
        )
    state.places[0] = PlaceState(owner=0, pop=300)
    state.relations[(0, 1)] = Relation(0, 1, "alliance", border_km=10.0)
    return state


# ---------------------------------------------------------------- with no state: the world itself
def test_with_no_state_the_owners_are_the_worlds_realm_grid() -> None:
    world = _world()
    assert WorldReader(world).owners is world.realm_id


def test_with_no_state_the_realms_are_the_worlds_list() -> None:
    world = _world()
    assert WorldReader(world).realms is world.realms


def test_with_no_state_the_relations_are_the_worlds_list() -> None:
    world = _world()
    assert WorldReader(world).relations is world.relations


def test_with_no_state_the_rulers_and_predecessors_are_the_worlds_lists() -> None:
    world = _world()
    reader = WorldReader(world)
    assert (reader.rulers is world.rulers, reader.predecessors is world.predecessors) == (True, True)


def test_with_no_state_the_places_are_the_standing_pois_then_the_vanished() -> None:
    world = _world()
    places = WorldReader(world).places
    assert all(own is base for own, base in zip(places, [*world.pois, *world.vanished], strict=True))


def test_with_no_state_the_poi_index_is_the_worlds() -> None:
    world = _world()
    assert WorldReader(world).poi_index is world.poi_index


def test_the_standing_mask_holds_the_pois_and_not_the_vanished() -> None:
    assert WorldReader(_world()).standing.tolist() == [True, True, False]


def test_a_vanished_poi_is_not_found_at_its_cell() -> None:
    world = _world()
    world.poi_index[0, 5] = 2  # a stray stamp: the vanished POI is not on today's map
    assert WorldReader(world).poi_at(5, 0) is None


def test_the_realm_at_a_cell_is_the_one_that_holds_it() -> None:
    world = _world()
    assert WorldReader(world).realm_at(4, 0) is world.realms[1]


def test_the_realm_at_a_cell_with_no_owner_is_none() -> None:
    world = _world()
    world.realm_id[0, 0] = -1
    assert WorldReader(world).realm_at(0, 0) is None


def test_the_poi_at_a_cell_is_the_one_anchored_there() -> None:
    world = _world()
    assert WorldReader(world).poi_at(1, 1) is world.pois[0]


def test_with_no_state_there_is_no_manifest_and_the_clock_is_zero() -> None:
    reader = WorldReader(_world())
    assert (reader.manifest_of(0), reader.tick, reader.revision) == (None, 0, 0)


def test_the_top_realm_follows_the_lieges() -> None:
    assert WorldReader(_world()).top_realm(1) == 0


def test_the_events_are_the_chronicle() -> None:
    assert len(WorldReader(_world()).events) == 1


# ---------------------------------------------------------------- a state equal to the world: still the world's objects
def test_a_state_that_matches_the_world_returns_the_worlds_realm_list() -> None:
    world = _world()
    assert WorldReader(world, _state(world)).realms is world.realms


def test_a_state_that_matches_the_world_returns_its_places_unchanged() -> None:
    world = _world()
    places = WorldReader(world, _state(world)).places
    assert all(own is base for own, base in zip(places, [*world.pois, *world.vanished], strict=True))


def test_a_state_that_matches_the_world_returns_its_relation_list() -> None:
    world = _world()
    assert WorldReader(world, _state(world)).relations is world.relations


def test_a_state_that_matches_the_world_returns_its_poi_index() -> None:
    world = _world()
    assert WorldReader(world, _state(world)).poi_index is world.poi_index


def test_with_a_state_the_owners_are_the_states_own_grid() -> None:
    world = _world()
    state = _state(world)
    assert WorldReader(world, state).owners is state.owners


def test_the_reader_reports_the_states_tick_and_revision() -> None:
    world = _world()
    state = _state(world)
    state.revision = 4
    reader = WorldReader(world, state)
    assert (reader.tick, reader.revision) == (500, 4)


@pytest.fixture(scope="module")
def generated() -> World:
    return pipeline.generate(load_config(None), 42)


def test_a_hydrated_state_returns_the_generated_worlds_objects(generated: World) -> None:
    # The zero-tick property: nothing the simulation has not changed is copied.
    config = load_config(None)
    reader = WorldReader(generated, hydrate(generated, config, 42))
    assert (
        reader.realms is generated.realms
        and reader.relations is generated.relations
        and reader.poi_index is generated.poi_index
        and all(own is base for own, base in zip(reader.places, [*generated.pois, *generated.vanished], strict=True))
    )


# ---------------------------------------------------------------- what the simulation changed
def test_a_place_that_changed_owner_is_a_copy_with_the_new_owner() -> None:
    world = _world()
    state = _state(world)
    state.places[0].owner = 1
    town = WorldReader(world, state).places[0]
    assert (town.realm_id, town is world.pois[0], world.pois[0].realm_id) == (1, False, 0)


def test_a_place_that_changed_population_is_a_copy_with_the_new_people() -> None:
    world = _world()
    state = _state(world)
    state.places[0].pop = 450
    assert WorldReader(world, state).places[0].pop == 450


def test_a_place_that_changed_hands_is_free_or_held_by_its_new_owner() -> None:
    world = _world()
    state = _state(world)
    state.places[0].owner = -1
    assert WorldReader(world, state).places[0].free


def test_a_cell_that_changed_owner_is_read_from_the_states_grid() -> None:
    world = _world()
    state = _state(world)
    state.owners[0, 0] = 1
    assert WorldReader(world, state).realm_at(0, 0) is world.realms[1]


def test_a_faction_that_changed_people_makes_a_copy_of_its_realm() -> None:
    world = _world()
    state = _state(world)
    state.factions[0].pop = 999
    realm = WorldReader(world, state).realms[0]
    assert (realm.pop, realm is world.realms[0], world.realms[0].pop) == (999, False, 500)


def test_the_realms_that_did_not_change_stay_the_worlds() -> None:
    world = _world()
    state = _state(world)
    state.factions[0].pop = 999
    assert WorldReader(world, state).realms[1] is world.realms[1]


def test_a_vassal_that_broke_free_leaves_its_lieges_vassal_list() -> None:
    world = _world()
    state = _state(world)
    state.factions[1].liege = -1
    realms = WorldReader(world, state).realms
    assert (realms[1].liege, realms[0].vassals) == (-1, [])


def test_a_realm_that_took_a_vassal_lists_it() -> None:
    world = _world()
    world.realms[1].liege = -1
    world.realms[0].vassals = []
    state = _state(world)
    state.factions[1].liege = 0
    assert WorldReader(world, state).realms[0].vassals == [1]


def test_a_new_ruler_names_the_realms_ruler() -> None:
    world = _world()
    state = _state(world)
    state.rulers = [Ruler(2, 0, 1201, None, "x", name="Queen C")]
    state.factions[0].ruler_id = 2
    assert WorldReader(world, state).realms[0].ruler == "Queen C"


def test_a_realm_the_simulation_made_follows_the_generated_ones() -> None:
    world = _world()
    state = _state(world)
    made = Realm(id=2, kind="tribal", name="Cade")
    state.realms = [made]
    reader = WorldReader(world, state)
    assert (reader.realms[2] is made, reader.realm(2).name, len(world.realms)) == (True, "Cade", 2)


def test_the_top_realm_reads_the_simulations_lieges() -> None:
    world = _world()
    state = _state(world)
    state.factions[1].liege = -1
    assert WorldReader(world, state).top_realm(1) == 1


def test_rulers_and_predecessors_continue_after_the_generated_ones() -> None:
    world = _world()
    state = _state(world)
    state.rulers = [Ruler(2, 0, 1201, None, "x")]
    state.predecessors = [Predecessor(1, 5, 6)]
    reader = WorldReader(world, state)
    assert (len(reader.rulers), len(reader.predecessors)) == (3, 2)


def test_a_minted_poi_follows_the_standing_and_the_vanished() -> None:
    world = _world()
    state = _state(world)
    camp = POI(kind="camp", x=2, y=3, interior_seed=9)
    state.pois = [camp]
    reader = WorldReader(world, state)
    assert (reader.places[3] is camp, reader.standing.tolist()) == (True, [True, True, False, True])


def test_a_minted_poi_is_found_at_its_cell() -> None:
    world = _world()
    state = _state(world)
    camp = POI(kind="camp", x=2, y=3, interior_seed=9)
    state.pois = [camp]
    reader = WorldReader(world, state)
    assert (reader.poi_at(2, 3) is camp, int(reader.poi_index[3, 2])) == (True, 3)


def test_a_minted_poi_does_not_replace_the_poi_on_its_tile() -> None:
    world = _world()
    state = _state(world)
    state.pois = [POI(kind="camp", x=1, y=1, interior_seed=9)]
    assert WorldReader(world, state).poi_at(1, 1) is world.pois[0]


def test_a_minted_poi_leaves_the_worlds_poi_index_alone() -> None:
    world = _world()
    state = _state(world)
    state.pois = [POI(kind="camp", x=2, y=3, interior_seed=9)]
    _ = WorldReader(world, state).poi_index
    assert world.poi_index[3, 2] == -1


def test_a_place_of_a_minted_poi_takes_its_own_state() -> None:
    world = _world()
    state = _state(world)
    state.pois = [POI(kind="hamlet", x=2, y=3, interior_seed=9, civilized=True, realm_id=0, pop=20)]
    state.places[3] = PlaceState(owner=1, pop=35)
    hamlet = WorldReader(world, state).places[3]
    assert (hamlet.realm_id, hamlet.pop) == (1, 35)


def test_the_manifest_of_a_settlement_is_the_states() -> None:
    world = _world()
    state = _state(world)
    manifest = SiteManifest("town", 8, 2, True)
    state.manifests[0] = manifest
    reader = WorldReader(world, state)
    assert (reader.manifest_of(0), reader.manifest_of(1)) == (manifest, None)


def test_a_relation_that_changed_is_the_states_copy() -> None:
    world = _world()
    state = _state(world)
    state.relations[(0, 1)].kind = "war"
    reader = WorldReader(world, state)
    assert (reader.relations[0].kind, world.relations[0].kind) == ("war", "alliance")


def test_a_pair_the_simulation_added_follows_the_worlds_relations() -> None:
    world = _world()
    state = _state(world)
    state.relations[(0, 2)] = Relation(0, 2, "trade")
    assert [(r.a, r.b) for r in WorldReader(world, state).relations] == [(0, 1), (0, 2)]


def test_a_pair_the_simulation_ended_has_no_relation() -> None:
    world = _world()
    state = _state(world)
    del state.relations[(0, 1)]
    assert WorldReader(world, state).relations == []


# ---------------------------------------------------------------- caching and events
def test_objects_stay_the_same_within_a_revision() -> None:
    world = _world()
    state = _state(world)
    state.places[0].owner = 1
    reader = WorldReader(world, state)
    assert reader.places is reader.places and reader.places[0] is reader.places[0]


def test_a_new_revision_builds_the_places_again() -> None:
    world = _world()
    state = _state(world)
    reader = WorldReader(world, state)
    _ = reader.places
    state.places[0].owner = 1
    state.revision += 1
    assert reader.places[0].realm_id == 1


def test_without_a_new_revision_the_built_places_are_kept() -> None:
    # The simulation bumps the revision when it changes something; until it does a reader keeps what it built.
    world = _world()
    state = _state(world)
    reader = WorldReader(world, state)
    _ = reader.places
    state.places[0].owner = 1
    assert reader.places[0].realm_id == 0


def test_events_the_reader_appends_join_the_states_list() -> None:
    world = _world()
    state = _state(world)
    WorldReader(world, state).events.append(ChronicleEvent(-1, 200, "treaty", month=3))
    assert [event.id for event in state.events] == [1]


def test_the_events_read_the_chronicle_then_the_states() -> None:
    world = _world()
    state = _state(world)
    state.events.append(ChronicleEvent(-1, 200, "treaty", month=3))
    assert [event.kind for event in WorldReader(world, state).events] == ["founding", "treaty"]


def test_the_owner_grid_is_not_copied() -> None:
    world = _world()
    state = _state(world)
    assert np.shares_memory(WorldReader(world, state).owners, state.owners)
