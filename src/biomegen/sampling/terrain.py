"""Land and river as a sampler sees them, shared by the layers and the site plans.

The renderer draws water where the sampled biome is water, and rivers where the (smoothed) coverage of river tiles
holds over a land biome. A site plan must agree with that exactly, or a building could stand in a river that is
drawn beside it, so both read these two functions.
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from ..world.tile import BIOME_NAME, WaterType
from ..world.world import World
from .sampler import Sampler


def water_biomes(config: Config) -> np.ndarray:
    """Return a bool lookup by biome value: True where the cover is water (``tables.biomes.*.water``)."""
    return config.table_array("biomes", "water", BIOME_NAME) > 0.5


def land_mask(sampler: Sampler, biome: np.ndarray, water: np.ndarray) -> np.ndarray:
    """Return the cells inside the world whose ``biome`` (per cell) is not water."""
    return sampler.inside & ~water[biome]


def river_mask(sampler: Sampler, world: World, land: np.ndarray, water: np.ndarray) -> np.ndarray:
    """Return the land cells covered by a river: fresh water over a land biome, smoothed at the detail scales."""
    tiles = (world.water_type == int(WaterType.FRESH)) & ~water[world.biome]
    return land & sampler.coverage_mask(tiles)
