"""Stage 2: island mask + ocean classification + distance-to-ocean.

Given the heightmap, this stage decides what is water and, crucially, what is *ocean* (saltwater
connected to the map edge) versus interior water (provisional freshwater, refined by hydrology). It
also publishes ``dist_to_ocean`` - a field reused by climate (coastal moisture), biomes (beaches ring
the ocean, not lakes) and hydrology - computed exactly once here.

Ownership note: the radial falloff already happened in the heightmap stage; this stage is pure
threshold-and-classify and never re-applies a falloff.
"""

from __future__ import annotations

import numpy as np

from ..config.model import Config
from ..util import geometry as geo
from ..world.tile import Biome, WaterType
from ..world.world import World


def _edge_connected_water(water: np.ndarray, backend: str) -> np.ndarray:
    """Return a boolean mask of water tiles connected (4-way) to the map border = the open ocean.

    Interior water (lakes inside the island) is *not* edge-connected and is excluded, so it can be
    classified as freshwater by hydrology.
    """
    labels, _ = geo.label_by_value(water.astype(np.uint8), connectivity=4, backend=backend)
    # Collect the labels of water cells lying on any border row/column.
    border_labels: set[int] = set()
    h, w = water.shape
    for x in range(w):
        if water[0, x]:
            border_labels.add(int(labels[0, x]))
        if water[h - 1, x]:
            border_labels.add(int(labels[h - 1, x]))
    for y in range(h):
        if water[y, 0]:
            border_labels.add(int(labels[y, 0]))
        if water[y, w - 1]:
            border_labels.add(int(labels[y, w - 1]))
    if not border_labels:
        return np.zeros_like(water, dtype=bool)
    return water & np.isin(labels, list(border_labels))


def run(world: World, config: Config, seed: int) -> None:
    """Classify ocean / interior water / land and fill ``dist_to_ocean``."""
    backend = config.get("compute.backend")
    sea_level = float(config.get("world.sea_level"))

    water = world.elevation < sea_level
    ocean = _edge_connected_water(water, backend)
    interior_water = water & ~ocean
    land = ~water

    # 1. Classify ocean as saltwater.
    world.biome[ocean] = int(Biome.OCEAN)
    world.water_type[ocean] = int(WaterType.SALT)

    # 2. Provisionally classify interior water as freshwater (hydrology refines lakes/rivers later).
    world.biome[interior_water] = int(Biome.LAKE)
    world.water_type[interior_water] = int(WaterType.FRESH)

    # 3. Land tiles get a neutral placeholder biome; the biomes stage classifies them properly.
    world.biome[land] = int(Biome.GRASSLAND)
    world.water_type[land] = int(WaterType.NONE)

    # 4. Compute the distance field every downstream stage reads (climate, biomes, POI placement).
    world.dist_to_ocean = geo.distance_to(ocean, backend=backend, metric="euclidean")


def land_fraction(world: World) -> float:
    """Return the fraction of tiles that are land (used by the pipeline's land-exists sanity gate)."""
    return float(np.mean(world.water_type == int(WaterType.NONE)))
