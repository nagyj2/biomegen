"""Shared, vectorised suitability fields for POI placement.

Three distance-derived fields are reused across POI kinds:
  * **freshwater closeness** - prefer tiles near lakes/rivers (settlements need water).
  * **coastal closeness** - prefer tiles near the ocean (ports/trade).
  * **remoteness** - distance from already-placed settlements (dungeons/ruin hide far from towns).

Distances come from :func:`biomegen.util.geometry.distance_to` (scipy EDT by default); the closeness
weights map them into [0, 1] with an exponential falloff so the bonus decays smoothly with distance.
The remoteness field is rebuilt as civilized POIs are placed, so later (uncivilized) kinds see an
up-to-date "how far from civilization" surface.
"""

from __future__ import annotations

import numpy as np

from ..util import geometry as geo
from ..world.tile import WaterType
from ..world.world import World


def freshwater_distance(world: World, backend: str) -> np.ndarray:
    """EDT distance (tiles) from every cell to the nearest freshwater (lake/river) tile."""
    fresh = world.water_type == int(WaterType.FRESH)
    return geo.distance_to(fresh, backend=backend, metric="euclidean").astype(np.float32)


def coast_distance(world: World) -> np.ndarray:
    """Distance to the nearest ocean tile - already computed by island_mask as ``dist_to_ocean``."""
    return world.dist_to_ocean.astype(np.float32)


def remoteness_distance(world: World, civ_points: list[tuple[int, int]], backend: str) -> np.ndarray:
    """EDT distance from every cell to the nearest civilized POI anchor (inf if none placed yet)."""
    if not civ_points:
        return np.full((world.height, world.width), np.inf, dtype=np.float32)
    mask = np.zeros((world.height, world.width), dtype=bool)
    for x, y in civ_points:
        mask[y, x] = True
    return geo.distance_to(mask, backend=backend, metric="euclidean").astype(np.float32)


def closeness_weight(dist: np.ndarray, scale: float) -> np.ndarray:
    """Map a distance field to a [0, 1] *closeness* weight (near -> 1) via ``exp(-dist/scale)``.

    ``exp(-inf)`` is 0.0, so a missing target (all-inf distance) cleanly yields zero weight.
    """
    scale = max(1e-6, float(scale))
    with np.errstate(over="ignore"):
        return np.exp(-dist / scale).astype(np.float64)


def remoteness_weight(dist: np.ndarray, scale: float) -> np.ndarray:
    """Map a distance-to-civilization field to a [0, 1] *remoteness* weight (far -> 1).

    ``1 - exp(-dist/scale)``; an infinite distance (no settlements yet) saturates to 1.
    """
    scale = max(1e-6, float(scale))
    finite = np.isfinite(dist)
    out = np.ones(dist.shape, dtype=np.float64)
    with np.errstate(over="ignore"):
        out[finite] = 1.0 - np.exp(-dist[finite] / scale)
    return out
