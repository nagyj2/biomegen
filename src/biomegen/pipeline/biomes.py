"""Stage 5: biome classification.

Each land tile is classified with a Whittaker-style model: biome is a function of temperature and
moisture (a 2-D lookup matrix), bracketed by elevation/coast overrides applied in a strict priority
order. This mirrors real ecology (Whittaker's biome diagram: rainfall + temperature explain most
biome distribution) and is the de-facto standard for natural-looking worldgen. A final majority-vote
smoothing pass removes the salt-and-pepper speckle that independent per-tile thresholding produces at
band edges.

Only land tiles (``water_type == NONE``) are classified here; ocean/lake/river tiles keep the biome
set by the mask and hydrology stages.
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from ..world.tile import Biome, WaterType, biome_from_name
from ..world.world import World

# Direction offsets used by the smoothing filter (orthogonal + diagonal).
_OFFSETS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def _matrix_int(config: Config) -> np.ndarray:
    """Convert the configured Whittaker name-matrix into a 2-D array of Biome ints."""
    matrix = config.get("biomes.matrix")
    return np.array([[int(biome_from_name(name)) for name in row] for row in matrix], dtype=np.uint8)


def _majority_filter(biome: np.ndarray, land: np.ndarray) -> np.ndarray:
    """Replace each land tile with the most common biome in its 3x3 neighbourhood (incl. itself).

    Vectorised: for each biome value present on land, count its occurrences in the neighbourhood via
    padded shifts, and keep, per cell, the value with the highest count. Water tiles are untouched.
    Ties resolve to the lower biome id (``np.unique`` is sorted), keeping the result deterministic.
    """
    h, w = biome.shape
    best = biome.copy()
    best_count = np.zeros((h, w), dtype=np.int16)
    for value in np.unique(biome[land]).tolist():
        m = (biome == value).astype(np.int16)
        padded = np.pad(m, 1, mode="constant", constant_values=0)
        count = m.copy()  # include the cell itself
        for dx, dy in _OFFSETS8:
            count += padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
        update = land & (count > best_count)
        best[update] = value
        best_count[update] = count[update]
    return np.where(land, best, biome).astype(np.uint8)


def run(world: World, config: Config, seed: int) -> None:
    """Classify land biomes in place."""
    b = config.section("biomes")
    land = world.water_type == int(WaterType.NONE)
    elev = world.elevation
    temp = world.temperature
    moist = world.moisture

    # 1. Whittaker lookup: bucket temperature/moisture into bands, index the matrix.
    matrix = _matrix_int(config)
    ti = np.digitize(temp, b.get("temp_bands"))  # 0 .. len(temp_bands)
    mi = np.digitize(moist, b.get("moisture_bands"))  # 0 .. len(moisture_bands)
    ti = np.clip(ti, 0, matrix.shape[0] - 1)
    mi = np.clip(mi, 0, matrix.shape[1] - 1)
    classified = matrix[ti, mi]

    biome = world.biome.copy()
    biome[land] = classified[land]

    # 2. Elevation and coast overrides; later assignment wins (priority: snow > mountain > beach > matrix).
    #    Apply beach first, then mountain, then snow — so the highest-priority class is written last.
    beach_max = float(b.get("beach_max"))
    beach_dist = float(b.get("beach_dist"))
    mountain_min = float(b.get("mountain_min"))
    snow_min = float(b.get("snow_min"))
    snow_temp = float(b.get("snow_temp"))

    beach = land & (elev <= beach_max) & (world.dist_to_ocean <= beach_dist)
    biome[beach] = int(Biome.BEACH)

    mountain = land & (elev >= mountain_min) & (elev < snow_min)
    biome[mountain] = int(Biome.MOUNTAIN)

    snow = land & (elev >= snow_min)
    biome[snow] = int(Biome.SNOW)

    # Cold and fairly high → permanent snow even below the strict elevation threshold.
    cold_high = land & (temp <= snow_temp) & (elev >= mountain_min * 0.85)
    biome[cold_high] = int(Biome.SNOW)

    world.biome = biome

    # 3. De-speckle: majority-vote smoothing removes salt-and-pepper noise at biome-band edges.
    for _ in range(int(b.get("smooth_passes"))):
        world.biome = _majority_filter(world.biome, land)
