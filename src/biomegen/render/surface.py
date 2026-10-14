"""What the old renderer draws for a cell's cover: the biome, with rivers shown as lake water.

Rivers stopped being a biome in phase 3 (a river cell keeps its land biome and is fresh water in
``water_type``). The curses-era views and exporters only know how to draw biomes, so they read the cover
through here, which shows river cells as :attr:`~biomegen.world.tile.Biome.LAKE`. Phase 4's layered
renderer draws rivers as their own water layer and replaces this module.
"""

from __future__ import annotations

import numpy as np

from ..world.tile import WATER_BIOMES, Biome, WaterType
from ..world.world import World

_WATER = np.array(sorted(WATER_BIOMES), dtype=np.int64)


def river_mask(world: World) -> np.ndarray:
    """Return the river cells: fresh water over a land biome."""
    return (world.water_type == int(WaterType.FRESH)) & ~np.isin(world.biome, _WATER)


def display_biome(world: World) -> np.ndarray:
    """Return the biome array to draw, with river cells shown as lake water."""
    return np.where(river_mask(world), int(Biome.LAKE), world.biome).astype(world.biome.dtype)


def display_biome_at(world: World, x: int, y: int) -> int:
    """Return the biome to draw at ``(x, y)`` (a river cell draws as lake water)."""
    biome = int(world.biome[y, x])
    if world.water_type[y, x] == int(WaterType.FRESH) and biome not in WATER_BIOMES:
        return int(Biome.LAKE)
    return biome
