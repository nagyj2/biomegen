"""Stage 2: climate - temperature in °C, wind-borne moisture with rain shadows, rainfall in mm.

Ported from the reference generator's ``_climate`` (``docs/reference/worldgen.py``), vectorised over rows:

1. **Temperature.** Sea-level temperature falls with the square of latitude (each row's latitude comes
   from ``world.scale``), plus regional noise, minus a lapse rate per km of height.
2. **Wind moisture.** Each row has a prevailing wind: westerlies in the mid latitudes, easterlies
   elsewhere. Air crossing sea recharges; over land it rains out a share of its moisture (more where the
   ground rises, the orographic effect) and dries with distance, losing extra moisture behind every rise
   (the rain shadow), so the lee of a range is dry.
3. **Moisture.** Wind-borne rain, regional noise and nearness to the coast are mixed, then rank-normalised
   over land to an even 0..1 spread.
4. **Rainfall.** Moisture maps to annual mm, reduced in cold air (:func:`rainfall_mm`).

Writes ``temperature_c``, ``moisture`` and ``rain_mm``. Hydrology later adds a fresh-water moisture bonus
and recomputes ``rain_mm``.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import noise, rng
from ...world.tile import WaterType
from ...world.world import World


def _row_latitudes(world: World) -> np.ndarray:
    """Return the latitude in degrees at the centre of every row, as an ``(height, 1)`` column."""
    return np.array([world.scale.lat_of_row(y) for y in range(world.height)], dtype=np.float64)[:, None]


def _temperature(world: World, config: Config, seed: int) -> np.ndarray:
    """Return mean annual temperature in °C: latitude, regional noise and lapse rate."""
    c = config.section("climate")
    stream = rng.derive(seed, "climate", "temperature")
    lat = _row_latitudes(world)
    sea_level = float(c.get("equator_c")) - float(c.get("lat_coefficient")) * lat * lat + float(c.get("offset_c"))
    sampler = noise.get_sampler(
        str(config.get("terrain.noise_backend")), rng.derive_int(seed, "climate", "temperature")
    )
    cx, cy = noise.km_grid((world.height, world.width), world.scale, float(c.get("temperature_feature_km")))
    field = noise.fbm(
        sampler,
        cx + stream.uniform(0, 256),
        cy + stream.uniform(0, 256),
        octaves=int(c.get("temperature_octaves")),
        persistence=float(config.get("terrain.fbm_gain")),
        lacunarity=float(config.get("terrain.fbm_lacunarity")),
    )
    lapse = float(c.get("lapse_c_per_km")) * np.maximum(world.elevation_m, 0.0) / 1000.0
    return sea_level + float(c.get("temperature_noise_c")) * field - lapse


def _wind_rain(world: World, config: Config) -> np.ndarray:
    """Return the wind-borne rain share per cell (0..1) by carrying moisture along each row."""
    c = config.section("climate")
    lo, hi = (float(v) for v in c.get("westerly_band_deg"))
    step_km = world.km_per_col
    recharge = step_km / float(c.get("recharge_km"))
    decay = float(np.exp(-step_km / float(c.get("decay_km"))))
    rise_full = float(c.get("orographic_rise_m"))
    base = float(c.get("orographic_base"))
    shadow_rise = float(c.get("shadow_rise_m"))
    max_shadow = float(c.get("max_shadow_loss"))
    min_keep = float(c.get("min_keep"))

    lat = np.abs(_row_latitudes(world)[:, 0])
    westerly = (lat >= lo) & (lat < hi)
    # Walk every row downwind at once: easterly rows are flipped so the wind always blows left to right.
    land = world.water_type == int(WaterType.NONE)
    height = np.where(land, world.elevation_m, 0.0)
    land_w = np.where(westerly[:, None], land, land[:, ::-1])
    height_w = np.where(westerly[:, None], height, height[:, ::-1])

    air = np.ones(world.height, dtype=np.float64)
    previous = np.zeros(world.height, dtype=np.float64)
    rain = np.zeros(land.shape, dtype=np.float64)
    for x in range(world.width):
        on_land = land_w[:, x]
        rise = np.maximum(0.0, height_w[:, x] - previous)
        sea_air = np.minimum(1.0, air + recharge)
        land_rain = air * (base + (1.0 - base) * np.minimum(1.0, rise / rise_full))
        land_air = air * np.maximum(min_keep, decay - np.minimum(max_shadow, rise / shadow_rise))
        rain[:, x] = np.where(on_land, land_rain, sea_air)
        air = np.where(on_land, land_air, sea_air)
        previous = np.where(on_land, height_w[:, x], 0.0)
    return np.where(westerly[:, None], rain, rain[:, ::-1])


def _moisture(world: World, config: Config, seed: int, rain: np.ndarray) -> np.ndarray:
    """Mix rain, regional noise and coast nearness, rank-normalised over land to [0, 1]."""
    c = config.section("climate")
    stream = rng.derive(seed, "climate", "moisture")
    sampler = noise.get_sampler(str(config.get("terrain.noise_backend")), rng.derive_int(seed, "climate", "moisture"))
    cx, cy = noise.km_grid((world.height, world.width), world.scale, float(c.get("moisture_feature_km")))
    field = 0.5 + noise.fbm(
        sampler,
        cx + stream.uniform(0, 256),
        cy + stream.uniform(0, 256),
        octaves=int(c.get("moisture_octaves")),
        persistence=float(config.get("terrain.fbm_gain")),
        lacunarity=float(config.get("terrain.fbm_lacunarity")),
    )
    land = world.water_type == int(WaterType.NONE)
    coast_km = geo.distance_to(~land, backend=config.get("compute.backend"), sampling=world.scale.sampling)
    moist = (
        float(c.get("rain_weight")) * rain
        + float(c.get("noise_weight")) * field
        + float(c.get("coast_weight")) * np.exp(-coast_km.astype(np.float64) / float(c.get("coast_km")))
    )
    values = moist[land]
    if values.size:
        order = np.argsort(values, kind="stable")
        ranks = np.empty(values.size, dtype=np.float64)
        ranks[order] = np.arange(values.size) / max(1, values.size - 1)
        moist[land] = ranks
    return np.clip(moist, 0.0, 1.0)


def rainfall_mm(moisture: np.ndarray, temperature_c: np.ndarray, config: Config) -> np.ndarray:
    """Return annual rainfall in mm from moisture (0..1) and temperature (cold air holds less water)."""
    c = config.section("climate")
    floor = float(c.get("cold_floor"))
    cold = np.clip(floor + (temperature_c + float(c.get("cold_offset_c"))) / float(c.get("cold_span_c")), floor, 1.0)
    wet = float(c.get("rain_min_mm")) + float(c.get("rain_span_mm")) * np.clip(moisture, 0.0, 1.0) ** float(
        c.get("rain_exponent")
    )
    return wet * cold


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``temperature_c``, ``moisture`` and ``rain_mm`` in place."""
    world.temperature_c = _temperature(world, config, seed)
    world.moisture = _moisture(world, config, seed, _wind_rain(world, config))
    world.rain_mm = rainfall_mm(world.moisture, world.temperature_c, config)
