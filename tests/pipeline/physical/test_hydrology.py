"""Tests for the hydrology stage in metres and km: lakes, accumulation, rivers, moisture, rainfall."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.physical import climate, hydrology, terrain
from biomegen.util.units import grid_scale
from biomegen.world.tile import WaterType
from biomegen.world.world import World

# 30 km square cells (900 km²) on a 30 x 12 grid.
WIDTH, HEIGHT = 30, 12


def _slope_world(bowl: bool = False) -> World:
    """Sea on the border and west edge; land rising 20 m per column eastward; optional inland bowl."""
    world = World(WIDTH, HEIGHT, 1, grid_scale(WIDTH, HEIGHT, (900.0, 360.0), 20.0, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.water_type[1:-1, 2:-1] = int(WaterType.NONE)
    cols = np.arange(WIDTH, dtype=np.float64)[None, :]
    world.elevation_m[:] = np.where(world.water_type == int(WaterType.NONE), 20.0 * cols, -100.0)
    if bowl:
        # A 4 x 4 basin 200 m deep: its rim spills westward at the column-15 level (300 m).
        world.elevation_m[4:8, 16:20] = 100.0
    world.moisture[:] = 0.5
    world.temperature_c[:] = 15.0
    return world


def _cfg(**hydrology_keys: object) -> Config:
    cfg = load_config(None)
    cfg.data["hydrology"].update(hydrology_keys)
    return cfg


def test_bowl_becomes_a_fresh_lake() -> None:
    world = _slope_world(bowl=True)
    hydrology.run(world, _cfg(), 1)
    assert len(world.lakes) == 1 and (world.water_type[4:8, 16:20] == int(WaterType.FRESH)).all()


def test_lake_surface_is_flat_at_spill_level() -> None:
    # The lake fills to the lowest rim cell it spills over, and every lake cell sits at that height.
    world = _slope_world(bowl=True)
    hydrology.run(world, _cfg(), 1)
    lake = world.lakes[0]
    surface = {float(world.elevation_m[y, x]) for x, y in lake.tiles}
    assert surface == {lake.surface_m} and lake.surface_m == pytest.approx(300.0)


def test_lake_area_is_reported_in_km2() -> None:
    world = _slope_world(bowl=True)
    hydrology.run(world, _cfg(), 1)
    assert world.lakes[0].area_km2 == pytest.approx(world.lakes[0].area * 900.0)


def test_small_depression_is_not_a_lake() -> None:
    # The 16-cell bowl is 14 400 km²; requiring more leaves it as land.
    world = _slope_world(bowl=True)
    hydrology.run(world, _cfg(min_lake_area_km2=20000.0), 1)
    assert world.lakes == []


def test_shallow_depression_is_not_a_lake() -> None:
    world = _slope_world(bowl=True)
    hydrology.run(world, _cfg(lake_min_depth_m=500.0), 1)
    assert world.lakes == []


def _strip_world() -> World:
    """One row: sea in column 0, land rising 20 m per column eastward (flow can only go west)."""
    world = World(WIDTH, 1, 1, grid_scale(WIDTH, 1, (900.0, 30.0), 20.0, 0.0))
    world.water_type[0, 0] = int(WaterType.SALT)
    world.elevation_m[0, :] = 20.0 * np.arange(WIDTH, dtype=np.float64)
    world.elevation_m[0, 0] = -100.0
    world.moisture[:] = 0.5
    world.temperature_c[:] = 15.0
    return world


def test_accumulation_is_upstream_weighted_area_in_km2() -> None:
    # Each land cell gathers itself and every cell east of it: n cells x 900 km² x (0.2 runoff + 0.5 moisture).
    world = _strip_world()
    hydrology.run(world, _cfg(river_land_share=0.0), 1)
    upstream_cells = WIDTH - np.arange(1, WIDTH)
    assert np.allclose(world.flow_accum[0, 1:], upstream_cells * 900.0 * 0.7)


def test_river_threshold_takes_the_larger_of_quantile_and_floor() -> None:
    accum = np.arange(1.0, 101.0)
    by_quantile = _cfg(river_land_share=0.1, river_min_drainage_km2=0.0).section("hydrology")
    by_floor = _cfg(river_land_share=0.1, river_min_drainage_km2=95.0).section("hydrology")
    assert hydrology._river_threshold(accum, by_quantile) == 91.0
    assert hydrology._river_threshold(accum, by_floor) == 95.0


def test_zero_land_share_means_no_rivers() -> None:
    world = _strip_world()
    hydrology.run(world, _cfg(river_land_share=0.0), 1)
    assert world.rivers == []


@pytest.fixture(scope="module")
def generated() -> World:
    cfg = load_config(None)
    world = World(96, 48, 42, grid_scale(96, 48, (6000.0, 3000.0), 35.0, 0.0))
    terrain.run(world, cfg, 42)
    climate.run(world, cfg, 42)
    hydrology.run(world, cfg, 42)
    return world


def test_rivers_run_from_source_to_mouth(generated: World) -> None:
    assert generated.rivers and all(r.source == r.path[0] for r in generated.rivers)


def test_river_length_km_sums_step_lengths(generated: World) -> None:
    # Every step is at least one column (62.5 km) and at most one diagonal; the length must fit between.
    for river in generated.rivers:
        steps = len(river.path) - 1 + (river.mouth is not None)
        assert steps * generated.km_per_col <= river.length_km <= steps * np.hypot(62.5, 62.5) + 1e-9


def test_river_cells_are_fresh_water(generated: World) -> None:
    assert all(generated.water_type[y, x] == int(WaterType.FRESH) for r in generated.rivers for x, y in r.path)


def test_rain_mm_follows_the_boosted_moisture(generated: World) -> None:
    # Hydrology recomputes rainfall after its fresh-water moisture bonus.
    cfg = load_config(None)
    expected = climate.rainfall_mm(generated.moisture, generated.temperature_c, cfg)
    assert np.array_equal(generated.rain_mm, expected)


def test_fresh_water_raises_nearby_moisture() -> None:
    world = _slope_world(bowl=True)
    before = world.moisture.copy()
    hydrology.run(world, _cfg(), 1)
    assert world.moisture[5, 15] > before[5, 15]
