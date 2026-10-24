"""Tests for hydrate: the present world becomes a starting state by copies and derivations only."""

from __future__ import annotations

import copy
import os
import subprocess
import sys

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sim import cadence
from biomegen.sim.hydrate import hydrate
from biomegen.sites.manifest import site_manifest
from biomegen.world.sim_state import SimState
from biomegen.world.world import World

SEED = 42


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


@pytest.fixture(scope="module")
def state(world: World, cfg: Config) -> SimState:
    return hydrate(world, cfg, SEED)


def test_the_state_starts_at_the_present_moment(state: SimState, world: World) -> None:
    # The present is the end of the last month of World.year: the first tick advanced opens month 1 of the next year.
    assert state.moment(12) == (world.year + 1, 1)


def test_the_state_takes_its_time_base_from_the_config(state: SimState, cfg: Config) -> None:
    assert state.ticks_per_month == int(cfg.get("sim.ticks_per_month"))


def test_the_state_starts_with_nothing_emitted_and_no_revision(state: SimState) -> None:
    assert (state.revision, state.events, state.rulers, state.predecessors, state.realms, state.pois) == (
        0,
        [],
        [],
        [],
        [],
        [],
    )


def test_the_owner_grid_is_the_worlds_realm_grid(state: SimState, world: World) -> None:
    assert np.array_equal(state.owners, world.realm_id)


def test_the_owner_grid_is_a_copy_the_simulation_may_move(state: SimState, world: World) -> None:
    assert not np.shares_memory(state.owners, world.realm_id)


def test_the_owner_grid_is_int16(state: SimState) -> None:
    assert state.owners.dtype == np.int16


def test_there_is_a_faction_for_every_realm(state: SimState, world: World) -> None:
    assert sorted(state.factions) == [realm.id for realm in world.realms]


def test_a_faction_has_its_present_ruler(state: SimState, world: World) -> None:
    assert [state.factions[realm.id].ruler_id for realm in world.realms] == [
        world.ruler_at(realm.id, world.year).id
        for realm in world.realms  # type: ignore[union-attr]
    ]


def test_a_faction_has_the_traits_of_its_ruler(state: SimState, world: World) -> None:
    assert all(
        state.factions[realm.id].traits == world.ruler_at(realm.id, world.year).traits  # type: ignore[union-attr]
        for realm in world.realms
    )


def test_a_factions_traits_are_a_copy_a_succession_may_redraw(state: SimState, world: World) -> None:
    realm = world.realms[0]
    ruler = world.ruler_at(realm.id, world.year)
    assert ruler is not None and state.factions[realm.id].traits is not ruler.traits


def test_a_faction_has_its_realms_liege_seat_and_people(state: SimState, world: World) -> None:
    assert [(f.liege, f.seat_poi, f.pop) for f in state.factions.values()] == [
        (r.liege, r.seat_poi, r.pop) for r in world.realms
    ]


def test_every_faction_has_the_first_check_of_each_cadence(state: SimState, cfg: Config) -> None:
    assert all(set(f.schedule) == set(cadence.cadence_names(cfg)) for f in state.factions.values())


def test_a_first_check_is_the_start_plus_the_factions_phase(state: SimState, cfg: Config) -> None:
    faction = state.factions[1]
    assert faction.schedule["strategy"].next_tick == state.tick + cadence.phase_ticks(SEED, cfg, 1, "strategy")


def test_a_schedule_starts_with_no_checks_made_since_the_start(state: SimState) -> None:
    assert all((s.count, s.last_tick) == (0, state.tick) for f in state.factions.values() for s in f.schedule.values())


def test_every_populated_poi_is_a_place(state: SimState, world: World) -> None:
    populated = [i for i, p in enumerate(world.pois) if p.civilized or p.kind == "homestead"]
    assert sorted(state.places) == populated


def test_a_place_has_its_pois_owner_and_people_and_no_stock(state: SimState, world: World) -> None:
    assert all(
        (place.owner, place.pop, place.stock) == (world.pois[i].realm_id, world.pois[i].pop, {})
        for i, place in state.places.items()
    )


def test_every_settlement_has_the_manifest_its_plan_would_read(state: SimState, world: World, cfg: Config) -> None:
    # The plan reads the manifest by tier and population: the hydrated one is exactly that, so no plan changes.
    assert all(state.manifests[i] == site_manifest(cfg, p) for i, p in enumerate(world.pois) if p.civilized)


def test_only_settlements_have_a_manifest(state: SimState, world: World) -> None:
    assert sorted(state.manifests) == [i for i, p in enumerate(world.pois) if p.civilized]


def test_relations_are_copies_of_todays_by_pair(state: SimState, world: World) -> None:
    assert state.relations == {(r.a, r.b): r for r in world.relations}


def test_a_relation_copy_is_independent_of_the_worlds(state: SimState, world: World) -> None:
    relation = world.relations[0]
    assert state.relations[(relation.a, relation.b)] is not relation


def _same(first: SimState, second: SimState) -> bool:
    return (
        first.tick == second.tick
        and np.array_equal(first.owners, second.owners)
        and first.factions == second.factions
        and first.places == second.places
        and first.manifests == second.manifests
        and first.relations == second.relations
    )


def test_hydrate_is_deterministic(world: World, cfg: Config, state: SimState) -> None:
    assert _same(state, hydrate(world, cfg, SEED))


def test_a_different_seed_moves_only_the_schedules(world: World, cfg: Config, state: SimState) -> None:
    other = hydrate(world, cfg, SEED + 1)
    assert (
        np.array_equal(other.owners, state.owners)
        and other.places == state.places
        and other.factions != (state.factions)
    )


def test_hydrate_leaves_the_world_unchanged(cfg: Config) -> None:
    fresh = pipeline.generate(cfg, SEED)
    before = (
        fresh.fingerprint(),
        copy.deepcopy(fresh.pois),
        copy.deepcopy(fresh.realms),
        copy.deepcopy(fresh.relations),
    )
    hydrate(fresh, cfg, SEED)
    assert (fresh.fingerprint(), fresh.pois, fresh.realms, fresh.relations) == before


def test_hydrate_is_independent_of_pythonhashseed() -> None:
    # The state's digest is the same in processes with different hash salts: nothing leaks set order or hash().
    code = (
        "import hashlib;"
        "from biomegen import pipeline;"
        "from biomegen.config import load_config;"
        "from biomegen.sim.hydrate import hydrate;"
        "cfg = load_config(None); w = pipeline.generate(cfg, 42); s = hydrate(w, cfg, 42);"
        "print(hashlib.blake2b(repr((s.tick, s.owners.tobytes(), sorted(s.factions.items()),"
        " sorted(s.places.items()), sorted(s.manifests.items()))).encode()).hexdigest())"
    )
    digests = set()
    for hashseed in ("0", "1", "98765"):
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=hashseed)
        )
        assert result.returncode == 0, result.stderr
        digests.add(result.stdout.strip())
    assert len(digests) == 1


@pytest.mark.parametrize("seed", [11, 15])
def test_worlds_with_a_defection_or_an_offshoot_hydrate_a_faction_per_realm(cfg: Config, seed: int) -> None:
    # Seeds 11 and 15 hold a defection and an offshoot (the secession fixtures): their realms all become factions.
    fixture = pipeline.generate(cfg, seed)
    assert sorted(hydrate(fixture, cfg, seed).factions) == [realm.id for realm in fixture.realms]


def test_a_dawn_world_hydrates_to_a_state_with_no_factions_or_places() -> None:
    config = load_config(None)
    config.data["history"]["start"] = "dawn"
    dawn = pipeline.generate(config, SEED)
    dawn_state = hydrate(dawn, config, SEED)
    assert (dawn_state.factions, dawn_state.places, dawn_state.manifests, dawn_state.relations) == ({}, {}, {}, {})


def test_a_dawn_state_still_has_a_clock() -> None:
    config = load_config(None)
    config.data["history"]["start"] = "dawn"
    dawn = pipeline.generate(config, SEED)
    assert hydrate(dawn, config, SEED).moment(12) == (dawn.year + 1, 1)
