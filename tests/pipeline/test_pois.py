"""Tests for wild POI placement: counts, km spacing, surfaces, elevation, floors and determinism."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline import pois
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World

WILD = ("tower", "dungeon", "ruin", "camp", "boat")


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, 9999)


def _island(width: int = 60, height: int = 30) -> World:
    """A grass island (30 km cells, 100 m high) ringed by sea, with no settlements."""
    world = World(width, height, 1, grid_scale(width, height, (width * 30.0, height * 30.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.biome[:] = int(Biome.SHALLOW)
    world.dist_to_ocean[:] = 1000.0
    land = (slice(3, height - 3), slice(3, width - 3))
    world.water_type[land] = int(WaterType.NONE)
    world.biome[land] = int(Biome.GRASS)
    world.elevation_m[land] = 100.0
    return world


def _wild_config(**rows: dict) -> Config:
    """Defaults with ``tables.pois`` replaced by the given kinds."""
    config = load_config(None)
    config.data["tables"]["pois"] = rows
    return config


def _camp(**overrides: object) -> dict:
    return {"km2_per_poi": 20000.0, "min_spacing_km": 60.0, "biomes": ["grass"], "floors": 1, **overrides}


# --------------------------------------------------------------------------- generated world
def test_only_wild_kinds_come_from_the_poi_stage(world: World, cfg: Config) -> None:
    # Settlements come from another stage; tables.pois lists the wild kinds.
    assert set(cfg.get("tables.pois")) == set(WILD)


def test_poi_index_refs_are_consistent(world: World) -> None:
    # Every POI's anchor cell points back at it.
    assert all(int(world.poi_index[p.y, p.x]) == i for i, p in enumerate(world.pois))


def test_land_pois_on_land_boats_on_water(world: World) -> None:
    for p in world.pois:
        if p.kind == "boat":
            assert world.water_type[p.y, p.x] != int(WaterType.NONE)
        else:
            assert world.water_type[p.y, p.x] == int(WaterType.NONE)


def test_a_wild_poi_keeps_its_spacing_from_every_earlier_poi(world: World, cfg: Config) -> None:
    # Each wild POI was placed no closer than its kind's min_spacing_km to any POI placed before it.
    types = cfg.get("tables.pois")
    scale = world.scale
    for i, p in enumerate(world.pois):
        if p.kind not in types:
            continue
        spacing = float(types[p.kind]["min_spacing_km"])
        for q in world.pois[:i]:
            km = float(np.hypot((p.x - q.x) * scale.km_per_col, (p.y - q.y) * scale.km_per_row))
            assert km >= spacing - 1e-6


def test_placement_deterministic(cfg: Config) -> None:
    a = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    b = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    assert a == b


def test_pois_respect_their_metre_elevation_limits(world: World, cfg: Config) -> None:
    # Every placed POI anchor sits within its kind's elevation_min_m / elevation_max_m band.
    for p in world.pois:
        rule = cfg.get(f"tables.pois.{p.kind}", {})
        height = float(world.elevation_m[p.y, p.x])
        assert height >= rule.get("elevation_min_m", float("-inf"))
        assert height <= rule.get("elevation_max_m", float("inf"))


def test_dungeons_descend_and_other_kinds_start_at_the_ground(world: World) -> None:
    for p in world.pois:
        if p.kind == "dungeon":
            assert p.lowest_floor == -(p.floor_count - 1)
        elif p.kind in WILD:
            assert p.lowest_floor == 0


# --------------------------------------------------------------------------- synthetic island
def test_count_is_land_area_over_km2_per_poi() -> None:
    # 54 x 24 land cells of 900 km2 hold 1,166,400 km2: one camp per 200,000 km2 asks for six.
    island = _island()
    pois.run(island, _wild_config(camp=_camp(km2_per_poi=200000.0)), 5)
    assert sum(1 for p in island.pois if p.kind == "camp") == 6


def test_density_multiplies_the_count() -> None:
    one, two = _island(), _island()
    pois.run(one, _wild_config(camp=_camp(km2_per_poi=200000.0)), 5)
    config = _wild_config(camp=_camp(km2_per_poi=200000.0))
    config.data["poi"]["density"] = 2.0
    pois.run(two, config, 5)
    assert len(two.pois) == 2 * len(one.pois)


def test_boats_count_sea_area_and_stand_on_water() -> None:
    island = _island()
    boat = _camp(km2_per_poi=500000.0, biomes=["shallow"], on_water=True)
    pois.run(island, _wild_config(boat=boat), 5)
    assert island.pois and all(island.water_type[p.y, p.x] != int(WaterType.NONE) for p in island.pois)


def test_elevation_cap_keeps_a_kind_off_high_ground() -> None:
    island = _island()
    island.elevation_m[:, 30:] = 900.0
    pois.run(island, _wild_config(camp=_camp(elevation_max_m=500.0)), 5)
    assert island.pois and all(p.x < 30 for p in island.pois)


def test_stage_is_deterministic_on_an_island() -> None:
    first, second = _island(), _island()
    config = _wild_config(camp=_camp())
    pois.run(first, config, 5)
    pois.run(second, config, 5)
    assert [(p.x, p.y) for p in first.pois] == [(p.x, p.y) for p in second.pois]


def test_remoteness_pushes_a_kind_away_from_a_settlement() -> None:
    # With no jitter and ties broken row-major, a kind without remoteness would take the north-west corner; with
    # remoteness and a settlement on the west side, its single pick lands in the east half.
    island = _island()
    island.pois.append(POI(kind="village", x=10, y=15, interior_seed=0, civilized=True))
    island.poi_index[15, 10] = 0
    config = _wild_config(camp=_camp(km2_per_poi=2000000.0, remoteness=5.0))
    config.data["poi"]["jitter"] = 0.0
    pois.run(island, config, 5)
    assert island.pois[1].x > 30


def test_footprint_mask_needs_enough_dry_land() -> None:
    # A 3x3 footprint on a 5x5 land patch with one water cell: half the footprint must be land to qualify.
    world = World(5, 5, 1)
    world.water_type[:] = int(WaterType.NONE)
    world.water_type[2, 2] = int(WaterType.SALT)
    assert pois.footprint_land_fraction_mask(world, 3, 3, 0.9)[2, 2] is np.False_
    assert pois.footprint_land_fraction_mask(world, 3, 3, 0.5)[2, 2] is np.True_
