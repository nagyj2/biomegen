"""Tests for which cells and tiles a site covers."""

from __future__ import annotations

from biomegen.config.model import Config
from biomegen.sim.hydrate import hydrate
from biomegen.sites import site_at, site_places, site_pois
from biomegen.world.entities import POI
from biomegen.world.reader import WorldReader
from biomegen.world.sim_state import SimState
from biomegen.world.world import World
from tests.sites.conftest import add_poi, flat_world


def test_site_pois_lists_only_kinds_with_a_site(config: Config) -> None:
    world = flat_world()
    add_poi(world, "village", 4, 4, pop=500)
    add_poi(world, "bridge", 8, 4)
    assert [poi.kind for poi, _geometry in site_pois(world, config)] == ["village"]


def test_site_at_finds_the_poi_under_a_tile(config: Config) -> None:
    world = flat_world()
    poi = add_poi(world, "capital", 7, 5, pop=50000)
    assert site_at(world, config, 8, 5) is poi


def test_site_at_is_none_away_from_every_site(config: Config) -> None:
    world = flat_world()
    add_poi(world, "tower", 7, 5)
    assert site_at(world, config, 2, 2) is None


def test_the_nearest_anchor_wins_an_overlap(config: Config) -> None:
    world = flat_world()
    add_poi(world, "capital", 5, 5, pop=50000)
    near = add_poi(world, "tower", 7, 5)
    assert site_at(world, config, 7, 5) is near


def _state(world: World, config: Config) -> SimState:
    return hydrate(world, config, 1)


def test_site_places_gives_each_sites_index_poi_and_geometry(config: Config) -> None:
    world = flat_world()
    add_poi(world, "bridge", 2, 2)
    village = add_poi(world, "village", 4, 4, pop=500)
    assert [(i, poi) for i, poi, _g in site_places(WorldReader(world), config)] == [(1, village)]


def test_site_places_leaves_out_a_vanished_poi(config: Config) -> None:
    world = flat_world()
    add_poi(world, "tower", 4, 4)
    world.vanished = [POI(kind="watchtower", x=8, y=4, interior_seed=3)]
    assert [poi.kind for _i, poi, _g in site_places(WorldReader(world), config)] == ["tower"]


def test_site_places_includes_a_poi_the_simulation_minted(config: Config) -> None:
    # It is numbered after the standing and the vanished POIs (``World.place``).
    world = flat_world()
    add_poi(world, "tower", 4, 4)
    world.vanished = [POI(kind="watchtower", x=8, y=4, interior_seed=3)]
    state = _state(world, config)
    state.pois = [POI(kind="tower", x=10, y=7, interior_seed=9)]
    assert [i for i, _p, _g in site_places(WorldReader(world, state), config)] == [0, 2]


def test_site_at_finds_a_minted_poi_through_the_reader(config: Config) -> None:
    world = flat_world()
    state = _state(world, config)
    camp = POI(kind="tower", x=7, y=5, interior_seed=9)
    state.pois = [camp]
    assert site_at(world, config, 7, 5, WorldReader(world, state)) is camp


def test_site_at_does_not_find_a_minted_poi_without_the_reader(config: Config) -> None:
    world = flat_world()
    state = _state(world, config)
    state.pois = [POI(kind="tower", x=7, y=5, interior_seed=9)]
    assert site_at(world, config, 7, 5) is None


def test_site_places_follows_the_revision(config: Config) -> None:
    # A place that changed hands is a copy, so the cached list must be rebuilt when the revision moves.
    world = flat_world()
    add_poi(world, "village", 4, 4, pop=500, civilized=True, realm_id=0)
    state = _state(world, config)
    reader = WorldReader(world, state)
    site_places(reader, config)
    state.places[0].owner = 1
    state.revision += 1
    assert site_places(reader, config)[0][1].realm_id == 1
