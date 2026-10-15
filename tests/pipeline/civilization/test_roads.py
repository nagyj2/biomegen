"""Tests for road generation (ocean spans, roads over water, A* bounds, determinism)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.util import geometry as geo
from biomegen.world.tile import Biome, WaterType


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    return pipeline.generate(cfg, 9999)


# --------------------------------------------------------------------------- roads over water
_MAX_OCEAN_RUN = 2  # short coastal hops are allowed; longer open-ocean crossings are not


def test_roads_never_cross_long_ocean_spans(cfg):
    for s in (1, 9999, 2024, 55):
        w = pipeline.generate(cfg, s)
        ocean_road = (w.road != 0) & (w.water_type == int(WaterType.SALT))
        if not ocean_road.any():
            continue
        labels, _ = geo.label_by_value(ocean_road.astype(np.uint8), connectivity=4)
        component_sizes = np.bincount(labels.ravel())
        # component 0 is background; check all foreground runs
        max_run = int(component_sizes[1:].max()) if len(component_sizes) > 1 else 0
        assert max_run <= _MAX_OCEAN_RUN, (
            f"seed {s}: ocean road run of {max_run} tiles exceeds limit of {_MAX_OCEAN_RUN}"
        )


def test_a_road_over_water_joins_other_road_tiles(world):
    # A bridge is just road over water: every such tile has a road neighbour, so the span connects to something.
    wet_road = (world.road != 0) & (world.water_type != int(WaterType.NONE))
    road = np.pad(world.road != 0, 1)
    neighbours = sum(
        road[1 + dy : road.shape[0] - 1 + dy, 1 + dx : road.shape[1] - 1 + dx].astype(int)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    )
    assert (neighbours[wet_road] > 0).all()


def test_no_bridge_pois_are_minted(world):
    assert all(p.kind != "bridge" for p in world.pois)


def test_roads_deterministic(cfg):
    assert np.array_equal(pipeline.generate(cfg, 55).road, pipeline.generate(cfg, 55).road)


def test_astar_max_expansions_bails(cfg):
    w, h = 40, 40

    def nbrs(n):
        return geo.neighbors8(n[0], n[1], w, h)

    def cost(a, b):
        return 1.0

    # Uncapped: a path exists.
    assert geo.astar((0, 0), (39, 39), nbrs, cost) is not None
    # Tiny cap: the search bails out and returns None.
    assert geo.astar((0, 0), (39, 39), nbrs, cost, max_expansions=5) is None


# --------------------------------------------------------------------------- tiers and cost tables
def _flat_world(width: int = 20, height: int = 9):
    """An all-grass land strip of 30 km square cells with no rivers."""
    from biomegen.util.units import grid_scale
    from biomegen.world.tile import Biome
    from biomegen.world.world import World

    world = World(width, height, 1, grid_scale(width, height, (width * 30.0, height * 30.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.NONE)
    world.biome[:] = int(Biome.GRASS)
    world.elevation_m[:] = 50.0
    return world


def _add_poi(world, kind: str, x: int, y: int) -> None:
    from biomegen.world.entities import POI

    world.poi_index[y, x] = len(world.pois)
    world.pois.append(POI(kind=kind, x=x, y=y, interior_seed=0, civilized=True))


def test_road_avoids_swamp_when_a_grass_detour_is_cheaper():
    # Swamp's move_cost makes a three-cell swamp band dearer than walking round it, so the road skips the band.
    from biomegen.pipeline.civilization import roads
    from biomegen.world.tile import Biome

    cfg = load_config(None)
    cfg.data["roads"]["meander_strength"] = 0.0
    world = _flat_world()
    world.biome[2:, 8:11] = int(Biome.SWAMP)  # open grass remains on rows 0 and 1
    _add_poi(world, "town", 2, 5)
    _add_poi(world, "town", 16, 5)
    roads.run(world, cfg, 1)
    assert world.road.any() and not (world.road.astype(bool) & (world.biome == int(Biome.SWAMP))).any()


def test_villages_branch_off_the_backbone_as_spurs():
    # Villages are not backbone tiers, so with certain connection a village is a spur node, never a trunk end.
    import random

    from biomegen.pipeline.civilization.roads import _classify_edges

    coords = [(0.0, 0.0), (100.0, 0.0), (50.0, 50.0)]
    trunk, spurs = _classify_edges(coords, [True] * 3, [True, True, False], 3, random.Random(1), (1.0, 1.0, 0.0))
    assert trunk == [(0, 1)] and spurs == [2]


def test_trunk_spans_backbone_nodes_whose_nearest_neighbours_are_villages():
    # Two far-apart backbone towns, each ringed by villages, still get joined: the MST ignores non-backbone nodes.
    import random

    from biomegen.pipeline.civilization.roads import _classify_edges

    coords = [(0.0, 0.0), (1000.0, 0.0)] + [(float(dx), float(dy)) for dx in (10, 20) for dy in (10, 20)] * 2
    flags = [True, True] + [False] * (len(coords) - 2)
    trunk, _spurs = _classify_edges(coords, [True] * len(coords), flags, 5, random.Random(1), (1.0, 1.0, 0.0))
    assert trunk == [(0, 1)]


def test_every_backbone_town_is_joined_into_one_network():
    # Four towns on a flat strip end up connected: the trunk is a spanning tree over the backbone tier.
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    world = _flat_world()
    for x, y in ((1, 1), (17, 1), (1, 7), (17, 7)):
        _add_poi(world, "town", x, y)
    roads.run(world, cfg, 1)
    from scipy import ndimage

    labels, _count = ndimage.label(world.road > 0, structure=np.ones((3, 3)))
    towns = {int(labels[y, x]) for x, y in ((1, 1), (17, 1), (1, 7), (17, 7))}
    assert len(towns) == 1 and 0 not in towns


def test_a_diagonal_crossing_of_a_river_puts_no_road_on_the_river():
    # A one-tile river runs corner to corner between two towns: the road steps across it diagonally and records
    # nothing on the water (the diagonal link is the bridge), so no L of road tiles forms.
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"]["meander_strength"] = 0.0
    world = _flat_world(10, 10)
    for i in range(10):
        world.water_type[9 - i, i] = int(WaterType.FRESH)
    world.biome[world.water_type == int(WaterType.FRESH)] = int(Biome.LAKE)
    _add_poi(world, "town", 2, 2)
    _add_poi(world, "town", 7, 7)
    roads.run(world, cfg, 1)
    assert world.road.any() and not (world.road.astype(bool) & (world.water_type == int(WaterType.FRESH))).any()


def _diagonal_bits(road):
    from biomegen.render.layers.roads import connection_mask8

    return (connection_mask8(road) & (2 | 8 | 32 | 128)) * (road > 0)


def test_cardinal_only_roads_use_no_diagonal_link():
    # Two towns on opposite corners of open grass: the default route cuts diagonals, the cardinal one never does.
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"].update({"meander_strength": 0.0, "cardinal_only": True})
    world = _flat_world(16, 12)
    _add_poi(world, "town", 1, 1)
    _add_poi(world, "town", 14, 10)
    roads.run(world, cfg, 1)
    assert world.road.any() and not _diagonal_bits(world.road).any()


def test_default_roads_may_use_diagonals():
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"]["meander_strength"] = 0.0
    world = _flat_world(16, 12)
    _add_poi(world, "town", 1, 1)
    _add_poi(world, "town", 14, 10)
    roads.run(world, cfg, 1)
    assert _diagonal_bits(world.road).any()


def test_cardinal_only_roads_still_join_every_town():
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"].update({"meander_strength": 0.0, "cardinal_only": True})
    world = _flat_world(16, 12)
    _add_poi(world, "town", 1, 1)
    _add_poi(world, "town", 14, 10)
    roads.run(world, cfg, 1)
    labels, _ = geo.label_by_value(world.road, connectivity=4)
    assert labels[1, 1] == labels[10, 14] and world.road[1, 1] and world.road[10, 14]


def test_cardinal_fallback_is_an_l():
    from biomegen.pipeline.civilization.roads import _l_path

    path = _l_path((1, 1), (4, 3))
    assert path == [(1, 1), (2, 1), (3, 1), (4, 1), (4, 2), (4, 3)]


def test_cardinal_only_whole_world_has_no_diagonal_link(cfg):
    from biomegen.config import load_config as load

    config = load(None)
    config.data["roads"]["cardinal_only"] = True
    world = pipeline.generate(config, 42)
    assert world.road.any() and not _diagonal_bits(world.road).any()


def test_roads_touching_at_a_corner_are_joined_in_a_cardinal_network():
    from biomegen.pipeline.civilization.roads import _close_diagonals

    world = _flat_world(6, 6)
    world.road[2, 2] = world.road[3, 3] = 1
    world.road_tier[2, 2], world.road_tier[3, 3] = 1, 2
    _close_diagonals(world)
    assert not _diagonal_bits(world.road).any() and int(world.road.sum()) == 3


def test_a_corner_across_the_open_sea_is_left_alone():
    from biomegen.pipeline.civilization.roads import _close_diagonals

    world = _flat_world(6, 6)
    world.road[2, 2] = world.road[3, 3] = 1
    world.water_type[2, 3] = world.water_type[3, 2] = int(WaterType.SALT)
    _close_diagonals(world)
    assert int(world.road.sum()) == 2


def test_a_river_corner_is_bridged_when_no_land_corner_exists():
    from biomegen.pipeline.civilization.roads import _close_diagonals

    world = _flat_world(6, 6)
    world.road[2, 2] = world.road[3, 3] = 1
    world.water_type[2, 3] = world.water_type[3, 2] = int(WaterType.FRESH)
    _close_diagonals(world)
    assert int(world.road.sum()) == 3


# --------------------------------------------------------------------------- spurs for the wild and history POIs
def _spur_world(connect: bool = True):
    """Two towns joined by the settlement roads, and a ruin one row off the route, with the ruin's ``connect`` set."""
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"].update({"meander_strength": 0.0, "uncivilized_connect_prob": 1.0})
    world = _flat_world(20, 11)
    _add_poi(world, "town", 1, 2)
    _add_poi(world, "town", 18, 2)
    roads.run(world, cfg, 1)
    _add_poi(world, "ruin", 9, 9)
    world.pois[-1].civilized = False
    world.pois[-1].connect = connect
    return world, cfg, roads


def test_a_ruin_that_may_connect_gets_a_spur_to_the_road():
    world, cfg, roads = _spur_world(connect=True)
    roads.spurs(world, cfg, 1)
    assert world.road[9, 9]


def test_a_ruin_that_may_not_connect_gets_no_road():
    world, cfg, roads = _spur_world(connect=False)
    roads.spurs(world, cfg, 1)
    assert not world.road[9, 9]


def test_the_settlement_pass_leaves_a_poi_that_may_not_connect_alone():
    # Even a POI that exists at roads time is skipped by the settlement roads when its connect is false.
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    cfg.data["roads"]["meander_strength"] = 0.0
    world = _flat_world(20, 11)
    _add_poi(world, "town", 1, 2)
    _add_poi(world, "town", 18, 2)
    _add_poi(world, "hamlet", 9, 9)
    world.pois[-1].connect = False
    roads.run(world, cfg, 1)
    assert not world.road[9, 9]


def test_a_spur_changes_no_tile_of_the_settlement_roads():
    # Spurs only add road: every tile of the settlement network is still there afterwards.
    world, cfg, roads = _spur_world()
    before = world.road.copy()
    roads.spurs(world, cfg, 1)
    assert (world.road[before > 0] > 0).all()


def test_spurs_on_a_landmass_with_no_road_do_nothing():
    from biomegen.pipeline.civilization import roads

    cfg = load_config(None)
    world = _flat_world(20, 11)
    _add_poi(world, "ruin", 9, 9)
    roads.spurs(world, cfg, 1)
    assert not world.road.any()


def test_the_stages_run_in_the_documented_order(cfg):
    timings: dict[str, float] = {}
    pipeline.generate(cfg, 42, timings)
    names = list(timings)
    assert names[names.index("settlements") :] == [
        "settlements",
        "roads",
        "realms",
        "diplomacy",
        "history",
        "pois",
        "spurs",
        "naming",
    ]


def test_generated_pois_take_their_realm_from_the_map(world):
    assert all(p.realm_id == int(world.realm_id[p.y, p.x]) for p in world.pois)
