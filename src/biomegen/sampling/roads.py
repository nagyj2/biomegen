"""The road bed: one rasterisation of the road network for every grid that shows it.

A road is a chain of links between neighbouring road tiles' centres. A grid cell is on the road when its warped
position lies within a fixed fraction of a tile of a link, so the zoom and local views, and a site's plan (which is
a grid of its own), draw the same road at their own resolution and meet exactly at a site's edge. Everything here is
a pure function of world position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config.model import Config
from ..world.tile import WaterType
from ..world.world import World
from .detail import DetailSampler

# Link directions, by the glyph of the bed they lie on; the last kind is a road tile with no link at all.
KIND_NAMES = ("horizontal", "vertical", "rising", "falling")
KIND_LONE = len(KIND_NAMES)
_FORWARD = (((1, 0), 0), ((0, 1), 1), ((1, -1), 2), ((1, 1), 3))  # the four "forward" neighbours of a tile


@dataclass(frozen=True)
class RoadBed:
    """The cells of a grid that lie on a road.

    Attributes:
        bed: Cells within the bed's half width of a road link.
        kind: Per cell, the direction of the nearest link (an index into ``KIND_NAMES``, or ``KIND_LONE``).
    """

    bed: np.ndarray
    kind: np.ndarray


def _mark_segment(
    sampler: DetailSampler,
    nearest: np.ndarray,
    kind: np.ndarray,
    warped: tuple[np.ndarray, np.ndarray],
    start: tuple[int, int],
    end: tuple[int, int],
    reach: float,
    half: float,
    link_kind: int,
) -> None:
    """Claim the cells whose warped position is within ``half`` tiles of the link ``start -> end``.

    ``nearest`` holds each cell's distance to its closest link so far and ``kind`` that link's direction, so a cell
    where links meet takes the nearer one.
    """
    ax, ay = start
    bx, by = end
    window = sampler.cell_window(min(ax, bx) - reach, max(ax, bx) + reach, min(ay, by) - reach, max(ay, by) + reach)
    if window is None:
        return
    x = warped[0][window]
    y = warped[1][window]
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        distance = np.hypot(x - ax, y - ay)
    else:
        t = np.clip(((x - ax) * dx + (y - ay) * dy) / length2, 0.0, 1.0)
        distance = np.hypot(x - (ax + t * dx), y - (ay + t * dy))
    closer = (distance <= half) & (distance < nearest[window])
    nearest[window] = np.where(closer, distance, nearest[window])
    kind[window] = np.where(closer, link_kind, kind[window])


def bed_half_width(config: Config, sampler: DetailSampler) -> float:
    """Return the bed's half width in tiles: a fixed fraction of a tile, but never under ``render.road_min_rows``."""
    half = float(config.get("render.road_half_width"))
    if half <= 0:
        return 0.0
    return max(half, 0.5 * float(config.get("render.road_min_rows")) / sampler.cell_h)


def road_bed(sampler: DetailSampler, world: World, config: Config) -> Optional[RoadBed]:
    """Return the road bed over ``sampler``'s grid, or None when no road is near it.

    The bed is the cells within ``render.road_half_width`` tiles (at least ``render.road_min_rows`` rows) of a link
    between two neighbouring road tiles (eight directions), measured at the road-warped position
    (``render.road_warp``). A road tile with no link is a disc at its centre.
    """
    half = bed_half_width(config, sampler)
    if half <= 0:
        return None
    land_road = (world.road > 0) & (world.water_type == int(WaterType.NONE))
    warp = max(float(config.get("render.road_warp")), 0.0)
    reach = half + warp
    x_lo = max(0, int(np.floor(sampler.cam_x - reach)))
    x_hi = min(world.width, int(np.ceil(sampler.cam_x + sampler.tiles_w + reach)))
    y_lo = max(0, int(np.floor(sampler.cam_y - reach)))
    y_hi = min(world.height, int(np.ceil(sampler.cam_y + sampler.tiles_h + reach)))
    if x_hi <= x_lo or y_hi <= y_lo:
        return None
    tile_rows, tile_cols = np.nonzero(land_road[y_lo:y_hi, x_lo:x_hi])
    if len(tile_cols) == 0:
        return None
    warped = sampler.warped(warp)
    nearest = np.full(sampler.fx.shape, np.inf)
    kind = np.full(sampler.fx.shape, KIND_LONE, dtype=np.int8)
    linked = _linked(land_road)
    for row, col in zip(tile_rows.tolist(), tile_cols.tolist(), strict=True):
        tx, ty = x_lo + col, y_lo + row
        if not linked[ty, tx]:
            _mark_segment(sampler, nearest, kind, warped, (tx, ty), (tx, ty), reach, half, KIND_LONE)
        for (step_x, step_y), link_kind in _FORWARD:
            nx, ny = tx + step_x, ty + step_y
            if 0 <= nx < world.width and 0 <= ny < world.height and land_road[ny, nx]:
                _mark_segment(sampler, nearest, kind, warped, (tx, ty), (nx, ny), reach, half, link_kind)
    bed = np.isfinite(nearest)
    return RoadBed(bed, kind) if bed.any() else None


def _linked(road: np.ndarray) -> np.ndarray:
    """Return which road tiles have at least one road neighbour (any of the eight)."""
    padded = np.pad(road, 1)
    count = sum(
        padded[1 + dy : padded.shape[0] - 1 + dy, 1 + dx : padded.shape[1] - 1 + dx].astype(np.int8)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    )
    return road & (count > 0)
