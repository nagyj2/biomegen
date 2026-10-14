"""Tests for the biomes stage: temperature bands, rainfall rules, swamp, beach, sea, relief, volcanoes."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.model import Config
from biomegen.config.validate import ConfigError, validate
from biomegen.pipeline.physical import biomes, climate, hydrology, terrain
from biomegen.util.units import grid_scale
from biomegen.world.tile import Biome, Relief, WaterType
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _land_world(width: int = 6, height: int = 4) -> World:
    """All dry land at 50 m, 15 °C and 1000 mm (forest) unless a test changes a cell."""
    world = World(width, height, 1, grid_scale(width, height, (width * 30.0, height * 30.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.NONE)
    world.elevation_m[:] = 50.0
    world.temperature_c[:] = 15.0
    world.rain_mm[:] = 1000.0
    return world


@pytest.mark.parametrize(
    ("temp_c", "rain_mm", "height_m", "expected"),
    [
        (-12.0, 500.0, 50.0, Biome.SNOW),
        (-5.0, 400.0, 50.0, Biome.TUNDRA),
        (-5.0, 900.0, 50.0, Biome.TAIGA),
        (0.0, 200.0, 50.0, Biome.TUNDRA),
        (0.0, 400.0, 50.0, Biome.TAIGA),
        (10.0, 100.0, 50.0, Biome.DESERT),
        (10.0, 500.0, 50.0, Biome.GRASS),
        (10.0, 1500.0, 50.0, Biome.FOREST),
        (10.0, 3500.0, 100.0, Biome.SWAMP),
        (10.0, 3500.0, 500.0, Biome.FOREST),
        (25.0, 300.0, 50.0, Biome.DESERT),
        (25.0, 700.0, 50.0, Biome.SAVANNA),
        (25.0, 1200.0, 50.0, Biome.GRASS),
        (25.0, 2000.0, 50.0, Biome.JUNGLE),
    ],
)
def test_land_band_rules(cfg: Config, temp_c: float, rain_mm: float, height_m: float, expected: Biome) -> None:
    # The reference decision tree: temperature band first, then rainfall, swamp only on wet lowland.
    world = _land_world()
    world.temperature_c[1, 2], world.rain_mm[1, 2], world.elevation_m[1, 2] = temp_c, rain_mm, height_m
    biomes.run(world, cfg, 1)
    assert Biome(int(world.biome[1, 2])) == expected


def _coast_world() -> World:
    """Sea in the left two columns, warm low land to the right."""
    world = _land_world(8, 4)
    world.water_type[:, :2] = int(WaterType.SALT)
    world.elevation_m[:, :2] = -200.0
    return world


def test_warm_low_coast_is_beach(cfg: Config) -> None:
    world = _coast_world()
    biomes.run(world, cfg, 1)
    assert (world.biome[:, 2] == int(Biome.BEACH)).all() and (world.biome[:, 4] == int(Biome.FOREST)).all()


def test_cold_coast_is_not_beach(cfg: Config) -> None:
    world = _coast_world()
    world.temperature_c[:] = 2.0
    biomes.run(world, cfg, 1)
    assert not (world.biome == int(Biome.BEACH)).any()


def test_river_mouth_is_not_beach(cfg: Config) -> None:
    # A river cell keeps its land biome, but never becomes beach.
    world = _coast_world()
    world.water_type[1, 2] = int(WaterType.FRESH)
    biomes.run(world, cfg, 1)
    assert int(world.biome[1, 2]) == int(Biome.FOREST)


def test_sea_is_shallow_near_land_and_deep_far_out(cfg: Config) -> None:
    # 30 km cells, shallow_km = 75: two cells off the coast are shallow, the far edge is deep.
    world = _land_world(12, 3)
    world.water_type[:, :10] = int(WaterType.SALT)
    world.elevation_m[:, :10] = -500.0
    biomes.run(world, cfg, 1)
    assert (world.biome[:, 8] == int(Biome.SHALLOW)).all() and (world.biome[:, 0] == int(Biome.DEEP)).all()


def test_cold_sea_freezes(cfg: Config) -> None:
    # -30 °C is far below sea_ice_c even with the +-3 °C ice noise.
    world = _land_world()
    world.water_type[:] = int(WaterType.SALT)
    world.temperature_c[:] = -30.0
    biomes.run(world, cfg, 1)
    assert (world.biome == int(Biome.SEAICE)).all()


def test_lake_stays_lake_unless_frozen(cfg: Config) -> None:
    world = _land_world()
    for x in (1, 4):
        world.biome[1, x] = int(Biome.LAKE)
        world.water_type[1, x] = int(WaterType.FRESH)
    world.temperature_c[1, 4] = -8.0
    biomes.run(world, cfg, 1)
    assert (int(world.biome[1, 1]), int(world.biome[1, 4])) == (int(Biome.LAKE), int(Biome.SEAICE))


@pytest.mark.parametrize(
    ("height_m", "expected"),
    [(500.0, Relief.NONE), (900.0, Relief.HILLS), (2000.0, Relief.MOUNTAIN), (3500.0, Relief.PEAK)],
)
def test_relief_follows_min_elevation_m(cfg: Config, height_m: float, expected: Relief) -> None:
    world = _land_world()
    world.elevation_m[2, 3] = height_m
    no_volcano = load_config(None)
    no_volcano.data["biomes"]["volcano_counts"] = [0]
    biomes.run(world, no_volcano, 1)
    assert Relief(int(world.relief[2, 3])) == expected


def test_peaks_are_snow(cfg: Config) -> None:
    world = _land_world()
    world.elevation_m[2, 3] = 4000.0
    biomes.run(world, cfg, 1)
    assert int(world.biome[2, 3]) == int(Biome.SNOW)


def test_volcano_count_comes_from_volcano_counts(cfg: Config) -> None:
    # Every cell is mountain; with a single allowed count of 2, exactly two become volcanoes.
    world = _land_world()
    world.elevation_m[:] = 2000.0
    two = load_config(None)
    two.data["biomes"]["volcano_counts"] = [2]
    biomes.run(world, two, 1)
    assert int((world.relief == int(Relief.VOLCANO)).sum()) == 2


def test_volcanoes_only_replace_mountains(cfg: Config) -> None:
    world = World(96, 48, 42, grid_scale(96, 48, (6000.0, 3000.0), 35.0, 0.0))
    for stage in (terrain, climate, hydrology, biomes):
        stage.run(world, cfg, 42)
    volcano = world.relief == int(Relief.VOLCANO)
    assert (world.elevation_m[volcano] >= cfg.get("tables.relief.mountain.min_elevation_m")).all()


def test_unordered_bands_are_rejected() -> None:
    bad = get_defaults()
    bad["biomes"]["bands"][0], bad["biomes"]["bands"][1] = bad["biomes"]["bands"][1], bad["biomes"]["bands"][0]
    with pytest.raises(ConfigError, match="ascending"):
        validate(bad)


def test_biomes_stage_is_deterministic(cfg: Config) -> None:
    def build() -> World:
        world = World(48, 24, 3, grid_scale(48, 24, (3000.0, 1500.0), 40.0, 0.0))
        for stage in (terrain, climate, hydrology, biomes):
            stage.run(world, cfg, 3)
        return world

    a, b = build(), build()
    assert np.array_equal(a.biome, b.biome) and np.array_equal(a.relief, b.relief)
