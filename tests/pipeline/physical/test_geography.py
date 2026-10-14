"""Tests for the geography stage: landmass ids, ranges and peaks, lakes, seas and named rivers."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.physical import geography
from biomegen.util.units import grid_scale
from biomegen.world.entities import Lake, River
from biomegen.world.tile import Biome, Relief, WaterType
from biomegen.world.world import World

# 30 km square cells (900 km²) on a 24 x 12 grid.
WIDTH, HEIGHT = 24, 12


def _cfg(**geography_keys: object) -> Config:
    cfg = load_config(None)
    cfg.data["geography"].update(
        {"min_landmass_km2": 9000.0, "min_range_km2": 2700.0, "min_named_lake_km2": 1800.0, "min_river_km": 50.0}
    )
    cfg.data["geography"].update(geography_keys)
    return cfg


def _world() -> World:
    """Sea everywhere; a big island (x 2..11, y 2..9) with a range, a lake and a river; a small island."""
    world = World(WIDTH, HEIGHT, 1, grid_scale(WIDTH, HEIGHT, (720.0, 360.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.elevation_m[:] = -1000.0
    world.elevation_m[0, 23] = -3000.0  # the deepest sea cell, in the far corner
    world.biome[:] = int(Biome.DEEP)
    big = (slice(2, 10), slice(2, 12))
    small = (slice(4, 7), slice(17, 20))
    for area in (big, small):
        world.water_type[area] = int(WaterType.NONE)
        world.biome[area] = int(Biome.GRASS)
        world.elevation_m[area] = 100.0
    # A 2 x 3 range with its summit at (5, 4).
    world.relief[3:5, 4:7] = int(Relief.MOUNTAIN)
    world.elevation_m[3:5, 4:7] = 2000.0
    world.elevation_m[4, 5] = 2600.0
    # A 2 x 2 lake at x 8..9, y 6..7.
    lake_tiles = [(x, y) for y in (6, 7) for x in (8, 9)]
    for x, y in lake_tiles:
        world.biome[y, x] = int(Biome.LAKE)
        world.water_type[y, x] = int(WaterType.FRESH)
    world.lakes = [Lake(id=0, tiles=lake_tiles, area=4, area_km2=3600.0)]
    # A river running east from (3, 7) into the lake at (8, 7), and a short one draining to the sea.
    path = [(x, 7) for x in range(3, 8)]
    for x, y in path:
        world.water_type[y, x] = int(WaterType.FRESH)
    world.flow_accum[7, 7] = 5000.0
    world.rivers = [
        River(id=0, path=path, length=5, mouth=(8, 7), source=path[0], length_km=150.0),
        River(id=1, path=[(11, 3)], length=1, mouth=(12, 3), source=(11, 3), length_km=30.0),
    ]
    return world


@pytest.fixture(scope="module")
def built() -> World:
    world = _world()
    geography.run(world, _cfg(), 1)
    return world


def _kind(world: World, kind: str) -> list:
    return [f for f in world.features if f.kind == kind]


def test_landmass_ids_rank_largest_first(built: World) -> None:
    assert (int(built.landmass_id[5, 3]), int(built.landmass_id[5, 18])) == (0, 1)


def test_sea_and_lake_cells_have_no_landmass(built: World) -> None:
    assert built.landmass_id[0, 0] == -1 and built.landmass_id[6, 8] == -1


def test_river_cells_belong_to_their_landmass(built: World) -> None:
    assert int(built.landmass_id[7, 4]) == 0


def test_only_large_landmasses_become_features(built: World) -> None:
    # The small island (9 cells, 8100 km²) is under min_landmass_km2 = 9000.
    assert [f.ref for f in _kind(built, "landmass")] == [0]


def test_range_summit_is_its_highest_cell(built: World) -> None:
    ranges = _kind(built, "range")
    assert len(ranges) == 1 and ranges[0].anchor == (5, 4) and ranges[0].elevation_m == 2600.0


def test_shared_summit_is_one_peak(built: World) -> None:
    # The big island's highest point is the range summit, so both point at the same peak feature.
    landmass, mountain = _kind(built, "landmass")[0], _kind(built, "range")[0]
    assert landmass.summit == mountain.summit and len(_kind(built, "peak")) == 1


def test_small_ranges_are_ignored() -> None:
    world = _world()
    geography.run(world, _cfg(min_range_km2=9000.0), 1)
    assert _kind(world, "range") == []


def test_lake_feature_points_at_hydrology_lake(built: World) -> None:
    lakes = _kind(built, "lake")
    assert [(f.ref, f.area_km2) for f in lakes] == [(0, 3600.0)]


def test_seas_respect_count_and_spacing(built: World) -> None:
    seas = _kind(built, "sea")
    spacing = load_config(None).get("geography.sea_spacing_km")
    anchors = [s.anchor for s in seas]
    assert len(seas) <= 3 and all(
        built.scale.distance_km(*a, *b) > spacing for i, a in enumerate(anchors) for b in anchors[i + 1 :]
    )


def test_sea_depth_is_the_deepest_cell_in_radius() -> None:
    world = _world()
    geography.run(world, _cfg(max_seas=1, sea_min_offshore_km=0.0, sea_depth_radius_km=5000.0), 1)
    assert _kind(world, "sea")[0].elevation_m == -3000.0


def test_named_river_flows_into_its_lake(built: World) -> None:
    rivers = _kind(built, "river")
    lake_id = _kind(built, "lake")[0].id
    assert [(f.ref, f.into, f.length_km) for f in rivers] == [(0, lake_id, 150.0)]


def test_river_into_the_sea_takes_the_nearest_sea() -> None:
    world = _world()
    geography.run(world, _cfg(min_river_km=10.0), 1)
    to_sea = next(f for f in _kind(world, "river") if f.ref == 1)
    assert to_sea.into in {s.id for s in _kind(world, "sea")}


def test_feature_ids_index_the_feature_list(built: World) -> None:
    assert [f.id for f in built.features] == list(range(len(built.features)))


def test_labelling_backend_does_not_change_landmasses_or_ranges() -> None:
    # Components are re-ranked by size and first cell, so the labelling backend cannot reorder them.
    # (Sea anchors use distance_to, whose non-scipy backend is an approximation, so they may differ.)
    results = []
    for backend in ("scipy", "pure"):
        cfg = _cfg()
        cfg.data["compute"]["backend"] = backend
        world = _world()
        geography.run(world, cfg, 1)
        areas = [(f.kind, f.anchor, f.area_km2) for f in world.features if f.kind in ("landmass", "range")]
        results.append((world.landmass_id.copy(), areas))
    assert np.array_equal(results[0][0], results[1][0]) and results[0][1] == results[1][1]
