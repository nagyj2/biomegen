"""Tests for the climate stage: latitude and lapse temperature, wind moisture, rain shadow, rainfall."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.physical import climate, terrain
from biomegen.util.units import grid_scale
from biomegen.world.tile import WaterType
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _strip_world(center_lat: float, ridge_col: int = 20) -> World:
    """A thin west-east strip: sea at both ends, flat 100 m land between, a 3000 m ridge at ``ridge_col``."""
    width, height = 40, 4
    world = World(width, height, 1, grid_scale(width, height, (2000.0, 40.0), center_lat, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.water_type[:, 5:35] = int(WaterType.NONE)
    world.elevation_m[:, 5:35] = 100.0
    world.elevation_m[:, ridge_col] = 3000.0
    return world


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    world = World(96, 48, 42, grid_scale(96, 48, (6000.0, 3000.0), 35.0, 0.0))
    terrain.run(world, cfg, 42)
    climate.run(world, cfg, 42)
    return world


def test_sea_level_temperature_falls_toward_the_pole(cfg: Config) -> None:
    # 28 - 0.0079 * lat²: the 60° row is ~25 °C colder than the equator row (noise is +-4 °C).
    equator = World(8, 4, 1, grid_scale(8, 4, (400.0, 40.0), 0.0, 0.0))
    polar = World(8, 4, 1, grid_scale(8, 4, (400.0, 40.0), 60.0, 0.0))
    climate.run(equator, cfg, 1)
    climate.run(polar, cfg, 1)
    assert equator.temperature_c.mean() - polar.temperature_c.mean() > 15.0


def test_lapse_rate_cools_by_height(cfg: Config) -> None:
    # The same cell 2000 m higher is 2 km x 6.5 °C/km = 13 °C colder (the noise is unchanged).
    low = World(8, 4, 1, grid_scale(8, 4, (400.0, 40.0), 30.0, 0.0))
    high = World(8, 4, 1, grid_scale(8, 4, (400.0, 40.0), 30.0, 0.0))
    high.elevation_m[2, 3] = 2000.0
    climate.run(low, cfg, 1)
    climate.run(high, cfg, 1)
    assert low.temperature_c[2, 3] - high.temperature_c[2, 3] == pytest.approx(13.0)


def test_westerlies_leave_a_rain_shadow_east_of_a_ridge(cfg: Config) -> None:
    # At 45° the wind blows from the west: land just east of the ridge is drier than just west of it.
    rain = climate._wind_rain(_strip_world(45.0), cfg)
    assert rain[:, 22].mean() < rain[:, 18].mean()


def test_easterlies_leave_a_rain_shadow_west_of_a_ridge(cfg: Config) -> None:
    # At 10° the trade winds blow from the east: the dry side flips to the west of the ridge.
    rain = climate._wind_rain(_strip_world(10.0), cfg)
    assert rain[:, 18].mean() < rain[:, 22].mean()


def test_upslope_rains_more_than_flat_land(cfg: Config) -> None:
    # Orographic lift: the windward face of the ridge wrings out more rain than the land before it.
    rain = climate._wind_rain(_strip_world(45.0), cfg)
    assert rain[:, 20].mean() > rain[:, 19].mean()


def test_air_dries_with_distance_inland(cfg: Config) -> None:
    # Flat strip, no ridge in the way: rain falls off steadily downwind of the coast.
    rain = climate._wind_rain(_strip_world(45.0, ridge_col=34), cfg)
    assert rain[0, 6] > rain[0, 15] > rain[0, 30]


def test_land_moisture_is_rank_normalised(generated: World) -> None:
    # Land moisture spans exactly 0..1 so the classifier sees an even spread.
    land = generated.water_type == int(WaterType.NONE)
    assert generated.moisture[land].min() == 0.0 and generated.moisture[land].max() == 1.0


def test_moisture_stays_in_unit_range(generated: World) -> None:
    assert generated.moisture.min() >= 0.0 and generated.moisture.max() <= 1.0


def test_rainfall_rises_with_moisture(cfg: Config) -> None:
    moisture = np.linspace(0.0, 1.0, 11)
    rain = climate.rainfall_mm(moisture, np.full(11, 20.0), cfg)
    assert (np.diff(rain) > 0).all()


def test_cold_air_holds_less_rain(cfg: Config) -> None:
    moisture = np.full(2, 0.7)
    warm, cold = climate.rainfall_mm(moisture, np.array([25.0, -15.0]), cfg)
    assert cold < warm


def test_rain_mm_matches_moisture_and_temperature(generated: World, cfg: Config) -> None:
    # rain_mm is the documented function of the stage's own moisture and temperature.
    assert np.array_equal(generated.rain_mm, climate.rainfall_mm(generated.moisture, generated.temperature_c, cfg))


def test_legacy_temperature_is_normalised(generated: World) -> None:
    assert generated.temperature.min() >= 0.0 and generated.temperature.max() <= 1.0


def test_climate_is_deterministic(cfg: Config) -> None:
    def build() -> World:
        world = World(48, 24, 9, grid_scale(48, 24, (3000.0, 1500.0), 40.0, 0.0))
        terrain.run(world, cfg, 9)
        climate.run(world, cfg, 9)
        return world

    assert build().fingerprint() == build().fingerprint()
