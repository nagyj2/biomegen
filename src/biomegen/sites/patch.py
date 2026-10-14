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


def window_sampler(world: World, config: Config, geometry: SiteGeometry) -> DetailSampler:
    """Return the detail sampler over ``geometry``'s whole window (one sampler cell per plan cell)."""
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
    )


def _find_gates(poi: POI, geometry: SiteGeometry, world: World, max_gates: int) -> tuple[Gate, ...]:
    """Return up to ``max_gates`` gates, one per direction the roads arrive from, nearest road first."""
    left, top, right, bottom = geometry.extent
    half_w, half_h = (right - left) / 2.0, (bottom - top) / 2.0
    reach = max(half_w, half_h) + 1.5
    x0, x1 = max(0, math.floor(poi.x - reach)), min(world.width, math.ceil(poi.x + reach) + 1)
    y0, y1 = max(0, math.floor(poi.y - reach)), min(world.height, math.ceil(poi.y + reach) + 1)
    nearest: dict[int, tuple[float, int, int]] = {}
    for row, col in np.argwhere(world.road[y0:y1, x0:x1] > 0).tolist():
        tx, ty = x0 + col, y0 + row
        if geometry.covers_tile(tx, ty):
            continue
        dx, dy = tx - poi.x, ty - poi.y
        sector = int(((math.atan2(dy, dx) / (2.0 * math.pi) * _SECTORS) + 0.5) % _SECTORS)
        distance = math.hypot(dx, dy)
        if sector not in nearest or (distance, tx, ty) < nearest[sector]:
            nearest[sector] = (distance, tx, ty)
    gates = []
    for _distance, tx, ty in sorted(nearest.values())[:max_gates]:
        gates.append(_gate(poi, geometry, tx - poi.x, ty - poi.y, half_w, half_h))
    return tuple(gates)


def _gate(poi: POI, geometry: SiteGeometry, dx: float, dy: float, half_w: float, half_h: float) -> Gate:
    """Return the gate where the ray from the anchor along ``(dx, dy)`` leaves the extent."""
    to_side = half_w / abs(dx) if dx else math.inf
    to_edge = half_h / abs(dy) if dy else math.inf
    through_side = to_side <= to_edge
    t = min(to_side, to_edge)
    col, row = geometry.cell_at(poi.x + dx * t, poi.y + dy * t)
    col0, row0, col1, row1 = geometry.box
    col = min(max(col, col0), col1 - 1) - col0
    row = min(max(row, row0), row1 - 1) - row0
    if through_side:
        return Gate(col, row, int(math.copysign(1, dx)), 0)
    return Gate(col, row, 0, int(math.copysign(1, dy)))


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
