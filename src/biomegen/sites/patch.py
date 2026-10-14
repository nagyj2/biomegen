"""The terrain a site plan is laid out on, and where roads reach it.

The patch is read through the same detail sampler the renderer uses (:mod:`biomegen.sampling`), over the site window,
so a plan agrees exactly with the land, rivers and shore the renderer draws around it. It is cropped to the extent box:
the cells a layout may build on.

Roads are not stored on the site. A road tile just outside the extent becomes a **gate**: the point where the line from
the anchor to that tile crosses the extent's edge. Gates are what make a door or a street face the road that arrives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..config.model import Config
from ..sampling.detail import SCALE_SITE, DetailSampler
from ..sampling.terrain import land_mask, river_mask, water_biomes
from ..world.entities import POI
from ..world.world import World
from .geometry import SiteGeometry

_SECTORS = 8  # distinct directions a road can arrive from; one gate per sector at most


@dataclass(frozen=True)
class Gate:
    """A road's arrival point on the extent's edge, in box cells.

    Attributes:
        col: Column of the gate cell on the box perimeter.
        row: Row of the gate cell on the box perimeter.
        dx: Outward step across the edge, ``-1``, ``0`` or ``1``.
        dy: Outward step down across the edge.
    """

    col: int
    row: int
    dx: int
    dy: int


@dataclass(frozen=True)
class SitePatch:
    """The terrain under the extent, in box cells (``rows x cols``).

    Attributes:
        dry: Dry ground inside the world: where a structure can stand.
        water: Water of any kind (sea, lake or river): where a bridge or a hull goes.
        elevation_m: Height above sea level, bilinear.
        gates: Where roads arrive, nearest first.
    """

    dry: np.ndarray
    water: np.ndarray
    elevation_m: np.ndarray
    gates: tuple[Gate, ...]

    @property
    def rows(self) -> int:
        return int(self.dry.shape[0])

    @property
    def cols(self) -> int:
        return int(self.dry.shape[1])


def window_sampler(
    world: World,
    config: Config,
    geometry: SiteGeometry,
    origin: tuple[int, int] = (0, 0),
    shape: tuple[int, int] | None = None,
) -> DetailSampler:
    """Return the detail sampler over ``geometry``'s window (one sampler cell per plan cell).

    ``origin`` and ``shape`` (``(col, row)`` and ``(rows, cols)``) restrict it to a rectangle of the window's cells.
    """
    return DetailSampler(
        world,
        config,
        geometry.cell_w,
        geometry.cell_h,
        geometry.cam_x,
        geometry.cam_y,
        geometry.tiles_w,
        geometry.tiles_h,
        SCALE_SITE,
        origin,
        shape,
    )


def _crossing(
    inner: tuple[int, int], outer: tuple[int, int], rect: tuple[float, float, float, float]
) -> tuple[float, float, bool]:
    """Return where the link from ``inner`` (inside ``rect``) to ``outer`` leaves it, and whether by a side edge."""
    left, top, right, bottom = rect
    dx, dy = outer[0] - inner[0], outer[1] - inner[1]
    to_side = ((right if dx > 0 else left) - inner[0]) / dx if dx else math.inf
    to_edge = ((bottom if dy > 0 else top) - inner[1]) / dy if dy else math.inf
    t = max(0.0, min(to_side, to_edge))
    return inner[0] + dx * t, inner[1] + dy * t, to_side <= to_edge


def _find_gates(poi: POI, geometry: SiteGeometry, world: World, max_gates: int) -> tuple[Gate, ...]:
    """Return up to ``max_gates`` gates: where road links cross the extent's edge, one per direction, nearest first.

    A road is a chain of links between neighbouring road tiles' centres, and the renderer draws its bed along them, so a
    gate at the crossing point meets the drawn road exactly. The anchor counts as road (roads end there).
    """
    left, top, right, bottom = geometry.extent
    rect = (left, top, right, bottom)
    reach = max((right - left) / 2.0, (bottom - top) / 2.0) + 1.5
    x0, x1 = max(0, math.floor(poi.x - reach)), min(world.width, math.ceil(poi.x + reach) + 1)
    y0, y1 = max(0, math.floor(poi.y - reach)), min(world.height, math.ceil(poi.y + reach) + 1)
    road = {(x0 + col, y0 + row) for row, col in np.argwhere(world.road[y0:y1, x0:x1] > 0).tolist()}
    road.add((poi.x, poi.y))

    def inside(tile: tuple[int, int]) -> bool:
        return left <= tile[0] <= right and top <= tile[1] <= bottom

    nearest: dict[int, tuple[float, float, float, bool]] = {}
    for tile in sorted(road):
        for step_x, step_y in ((1, 0), (0, 1), (1, 1), (1, -1)):
            other = (tile[0] + step_x, tile[1] + step_y)
            if other not in road or inside(tile) == inside(other):
                continue
            inner, outer = (tile, other) if inside(tile) else (other, tile)
            x, y, through_side = _crossing(inner, outer, rect)
            sector = int(((math.atan2(y - poi.y, x - poi.x) / (2.0 * math.pi) * _SECTORS) + 0.5) % _SECTORS)
            distance = math.hypot(x - poi.x, y - poi.y)
            if sector not in nearest or (distance, x, y) < nearest[sector][:3]:
                nearest[sector] = (distance, x, y, through_side)
    gates = []
    for _distance, x, y, through_side in sorted(nearest.values())[:max_gates]:
        col, row = geometry.cell_at(x, y)
        col0, row0, col1, row1 = geometry.box
        col = min(max(col, col0), col1 - 1) - col0
        row = min(max(row, row0), row1 - 1) - row0
        if through_side:
            gates.append(Gate(col, row, 1 if x > poi.x else -1, 0))
        else:
            gates.append(Gate(col, row, 0, 1 if y > poi.y else -1))
    return tuple(gates)


def read_patch(poi: POI, geometry: SiteGeometry, world: World, config: Config) -> SitePatch:
    """Read the terrain under ``poi``'s extent and find the gates where roads reach it."""
    sampler = window_sampler(world, config, geometry)
    water_biome = water_biomes(config)
    land = land_mask(sampler, sampler.biome(), water_biome)
    river = river_mask(sampler, world, land, water_biome)
    col0, row0, col1, row1 = geometry.box
    box = (slice(row0, row1), slice(col0, col1))
    dry = (land & ~river)[box]
    water = (sampler.inside & ~(land & ~river))[box]
    elevation = sampler.bilinear(world.elevation_m)[box].astype(np.float32)
    return SitePatch(dry, water, elevation, _find_gates(poi, geometry, world, int(config.get("sites.max_gates"))))
