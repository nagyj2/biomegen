"""Stage 4: biomes and relief - land cover from °C, mm and metres; high ground; volcanoes.

Ported from the reference generator's ``_biomes`` (``docs/reference/worldgen.py``), vectorised:

1. **Sea.** Sea ice where it is cold enough (with noise so the ice edge is ragged), shallows within
   ``shallow_km`` of land, deep ocean elsewhere. Lakes (marked by hydrology) freeze below ``lake_ice_c``.
2. **Land.** Temperature bands (``biomes.bands``) each with rainfall rules; very wet lowland in the warm
   bands becomes swamp; low, warm land touching the sea becomes beach. River cells are land here: a river
   keeps the biome of the ground it runs through.
3. **Relief.** Each land cell takes the highest relief row whose ``min_elevation_m`` it reaches (hills,
   mountains, peaks); peaks are always ``peak_biome`` (snow).
4. **Volcanoes.** A per-seed number of mountain or peak cells near the coast become volcanoes.

Writes ``biome`` and ``relief``.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import noise, rng
from ...world.tile import BIOME_BY_NAME, RELIEF_BY_NAME, Biome, Relief, WaterType
from ...world.world import World


def _sea(world: World, config: Config, seed: int, sea: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Return the biome of every sea cell (other cells hold DEEP): ice, shallows or deep."""
    b = config.section("biomes")
    stream = rng.derive(seed, "biomes", "ice")
    sampler = noise.get_sampler(str(config.get("terrain.noise_backend")), rng.derive_int(seed, "biomes", "ice"))
    cx, cy = noise.km_grid((world.height, world.width), world.scale, float(b.get("ice_feature_km")))
    ice_noise = noise.fbm(
        sampler,
        cx + stream.uniform(0, 256),
        cy + stream.uniform(0, 256),
        octaves=int(b.get("ice_octaves")),
        persistence=float(config.get("terrain.fbm_gain")),
        lacunarity=float(config.get("terrain.fbm_lacunarity")),
    )
    to_land_km = geo.distance_to(land, backend=config.get("compute.backend"), sampling=world.scale.sampling)
    frozen = world.temperature_c + float(b.get("ice_noise_c")) * ice_noise < float(b.get("sea_ice_c"))
    cover = np.where(to_land_km <= float(b.get("shallow_km")), int(Biome.SHALLOW), int(Biome.DEEP))
    cover = np.where(frozen, int(Biome.SEAICE), cover)
    return np.where(sea, cover, int(Biome.DEEP))


def _land(world: World, config: Config, land: np.ndarray, sea: np.ndarray, river: np.ndarray) -> np.ndarray:
    """Return the biome of every land cell from its temperature band and rainfall (others hold DEEP)."""
    b = config.section("biomes")
    temp, rain, height = world.temperature_c, world.rain_mm, world.elevation_m
    cover = np.full(temp.shape, int(Biome.DEEP), dtype=np.int64)
    pending = land.copy()
    swamp = (rain > float(b.get("swamp_min_rain_mm"))) & (height < float(b.get("swamp_max_elevation_m")))
    for band in b.get("bands"):
        in_band = pending & (temp < float(band["max_temp_c"]))
        choice = np.full(temp.shape, int(BIOME_BY_NAME[band["biome"]]), dtype=np.int64)
        # Apply the rain rules last-to-first so the first matching rule wins.
        for name, max_rain in reversed(band["rain"]):
            choice = np.where(rain < float(max_rain), int(BIOME_BY_NAME[name]), choice)
        if band.get("swamp", False):
            choice = np.where(swamp, int(Biome.SWAMP), choice)
        cover = np.where(in_band, choice, cover)
        pending &= ~in_band
    # Anything hotter than the last band takes that band's default (bands should end high enough).
    if pending.any():
        cover[pending] = int(BIOME_BY_NAME[b.get("bands")[-1]["biome"]])

    coastal = land & _touches(sea)
    beach = (
        coastal
        & (height < float(b.get("beach_max_elevation_m")))
        & (temp > float(b.get("beach_min_temp_c")))
        & (cover != int(Biome.SWAMP))
        & ~river
    )
    return np.where(beach, int(Biome.BEACH), cover)


def _touches(mask: np.ndarray) -> np.ndarray:
    """Return cells with at least one 8-neighbour in ``mask``."""
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    h, w = mask.shape
    out = np.zeros(mask.shape, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                out |= padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    return out


def _relief(world: World, config: Config, land: np.ndarray) -> np.ndarray:
    """Return relief from the height thresholds in the relief rows (highest matching row wins)."""
    rows = config.get("tables.relief")
    relief = np.full(land.shape, int(Relief.NONE), dtype=np.uint8)
    thresholds = sorted((float(row["min_elevation_m"]), name) for name, row in rows.items() if "min_elevation_m" in row)
    for metres, name in thresholds:
        relief[land & (world.elevation_m >= metres)] = int(RELIEF_BY_NAME[name])
    return relief


def _volcanoes(world: World, config: Config, seed: int, land: np.ndarray, sea: np.ndarray) -> None:
    """Turn a per-seed number of (preferably coastal) mountain or peak cells into volcanoes."""
    b = config.section("biomes")
    stream = rng.derive(seed, "biomes", "volcano")
    count = int(stream.choice(list(b.get("volcano_counts"))))
    high = land & np.isin(world.relief, [int(Relief.MOUNTAIN), int(Relief.PEAK)])
    if count <= 0 or not high.any():
        return
    to_sea_km = geo.distance_to(sea, backend=config.get("compute.backend"), sampling=world.scale.sampling)
    coastal = high & (to_sea_km <= float(b.get("volcano_coast_km")))
    pool = coastal if coastal.any() else high
    ys, xs = np.nonzero(pool)  # row-major order: a defined candidate order for the draw
    cells = list(zip(ys.tolist(), xs.tolist(), strict=True))
    for y, x in stream.sample(cells, min(len(cells), count)):
        world.relief[y, x] = int(Relief.VOLCANO)


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``biome`` and ``relief`` in place."""
    sea = world.water_type == int(WaterType.SALT)
    lake = world.biome == int(Biome.LAKE)  # marked by hydrology; rivers are fresh water on land
    land = ~sea & ~lake
    river = land & (world.water_type == int(WaterType.FRESH))

    cover = np.where(sea, _sea(world, config, seed, sea, land), _land(world, config, land, sea, river))
    frozen_lake = lake & (world.temperature_c < float(config.get("biomes.lake_ice_c")))
    cover = np.where(lake, np.where(frozen_lake, int(Biome.SEAICE), int(Biome.LAKE)), cover)

    world.relief = _relief(world, config, land)
    peak = world.relief == int(Relief.PEAK)
    cover = np.where(peak, int(BIOME_BY_NAME[str(config.get("biomes.peak_biome"))]), cover)
    world.biome = cover.astype(np.uint8)
    _volcanoes(world, config, seed, land, sea)
