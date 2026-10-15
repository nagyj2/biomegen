"""The road bed: one rasterisation of the road network for every grid that shows it.

A road is a chain of links between neighbouring road tiles' centres. Where a tile joins exactly two links the corner is
rounded (a quadratic curve from the middle of one link to the middle of the other, steered by the tile's centre), the
way a river is smoothed, so a staircase of tiles reads as a gentle curve and a right angle as a bend; junctions and
road ends stay straight. A grid cell is on the road when its warped position lies within a fixed fraction of a tile of
that line, so the zoom and local views, and a site's plan (which is a grid of its own), draw the same road at their own
resolution and meet exactly at a site's edge. Everything here is a pure function of world position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config.model import Config
from ..world.world import World
from .detail import DetailSampler

# Link directions, by the glyph of the bed they lie on; the last kind is a road tile with no link at all.
KIND_NAMES = ("horizontal", "vertical", "rising", "falling")
KIND_LONE = len(KIND_NAMES)
_FLAT = 0.4142  # tan of 22.5 degrees: a piece this shallow (or steep) is drawn horizontal (or vertical)
_CURVE_STEPS = 5  # straight pieces a rounded corner is flattened into


@dataclass(frozen=True)
class RoadBed:
    """The cells of a grid that lie on a road.

    Attributes:
        bed: Cells within the bed's half width of a road link.
        kind: Per cell, the direction of the nearest link (an index into ``KIND_NAMES``, or ``KIND_LONE``).
        rail: Cells in the band as wide again just outside the bed; a bridge draws its railings there.
    """

    bed: np.ndarray
    kind: np.ndarray
    rail: np.ndarray


def _kind_of(dx: float, dy: float) -> int:
    """Return the glyph kind (an index into ``KIND_NAMES``) of a piece running ``(dx, dy)`` in tiles."""
    ax, ay = abs(dx), abs(dy)
    if ay <= _FLAT * ax:
        return 0
    if ax <= _FLAT * ay:
        return 1
    return 2 if dx * dy < 0 else 3


def _mark_segment(
    sampler: DetailSampler,
    nearest: np.ndarray,
    kind: np.ndarray,
    warped: tuple[np.ndarray, np.ndarray],
    start: tuple[float, float],
    end: tuple[float, float],
    reach: float,
    limit: float,
    link_kind: Optional[int] = None,
) -> None:
    """Claim the cells whose warped position is within ``limit`` tiles of the piece ``start -> end``.

    ``nearest`` holds each cell's distance to its closest piece so far and ``kind`` that piece's direction (given, or
    worked out from the piece), so a cell where pieces meet takes the nearer one.
    """
    if link_kind is None:
        link_kind = _kind_of(end[0] - start[0], end[1] - start[1])
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
    closer = (distance <= limit) & (distance < nearest[window])
    nearest[window] = np.where(closer, distance, nearest[window])
    kind[window] = np.where(closer, link_kind, kind[window])


def bed_half_width(config: Config, sampler: DetailSampler) -> float:
    """Return the bed's half width in tiles: a fixed fraction of a tile, kept within the min and max rows."""
    half = float(config.get("render.road_half_width"))
    if half <= 0:
        return 0.0
    half = min(half, 0.5 * float(config.get("render.road_max_rows")) / sampler.cell_h)
    return max(half, 0.5 * float(config.get("render.road_min_rows")) / sampler.cell_h)


def road_bed(sampler: DetailSampler, world: World, config: Config) -> Optional[RoadBed]:
    """Return the road bed over ``sampler``'s grid, or None when no road is near it.

    The bed is the cells within ``render.road_half_width`` tiles (at least ``render.road_min_rows`` rows) of a link
    between two neighbouring road tiles (eight directions), measured at the road-warped position
    (``render.road_warp``). A diagonal link is left out when either orthogonal tile between the two is road, since the
    two already join through it and the link would cut the corner (the same rule as the map scale's glyph mask). A
    road tile with no link is a disc at its centre. Road tiles over water are road too:
    where the bed lies over water a caller draws a bridge.
    """
    half = bed_half_width(config, sampler)
    if half <= 0:
        return None
    road = world.road > 0
    warp = max(float(config.get("render.road_warp")), 0.0)
    rail_half = 2.0 * half
    reach = rail_half + warp
    x_lo = max(0, int(np.floor(sampler.cam_x - reach)))
    x_hi = min(world.width, int(np.ceil(sampler.cam_x + sampler.tiles_w + reach)))
    y_lo = max(0, int(np.floor(sampler.cam_y - reach)))
    y_hi = min(world.height, int(np.ceil(sampler.cam_y + sampler.tiles_h + reach)))
    if x_hi <= x_lo or y_hi <= y_lo:
        return None
    tile_rows, tile_cols = np.nonzero(road[y_lo:y_hi, x_lo:x_hi])
    if len(tile_cols) == 0:
        return None
    warped = sampler.warped(warp)
    nearest = np.full(sampler.fx.shape, np.inf)
    kind = np.full(sampler.fx.shape, KIND_LONE, dtype=np.int8)
    smooth = min(max(float(config.get("render.road_smooth")), 0.0), 1.0)
    for row, col in zip(tile_rows.tolist(), tile_cols.tolist(), strict=True):
        tx, ty = x_lo + col, y_lo + row
        links = _links(road, tx, ty)
        if not links:
            _mark_segment(sampler, nearest, kind, warped, (tx, ty), (tx, ty), reach, rail_half, KIND_LONE)
            continue
        ends = [((tx + nx) / 2.0, (ty + ny) / 2.0) for nx, ny in links]  # the middle of each link
        if len(links) == 2 and smooth > 0.0:
            _mark_corner(sampler, nearest, kind, warped, (tx, ty), ends[0], ends[1], smooth, reach, rail_half)
            continue
        for (
            end
        ) in ends:  # a junction, a road end, or no rounding: straight from the tile's centre to each link's middle
            _mark_segment(sampler, nearest, kind, warped, (tx, ty), end, reach, rail_half)
    bed = nearest <= half
    return RoadBed(bed, kind, (nearest > half) & (nearest <= rail_half)) if bed.any() else None


def _links(road: np.ndarray, x: int, y: int) -> list[tuple[int, int]]:
    """Return the road tiles linked to ``(x, y)``: its road neighbours in the eight directions, in a fixed order.

    A diagonal neighbour is left out when either orthogonal tile between the two is road: they already join through
    it and the link would cut the corner (the same rule as the map scale's glyph mask).
    """
    height, width = road.shape
    found = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nx, ny = x + dx, y + dy
            if (dx or dy) and 0 <= nx < width and 0 <= ny < height and road[ny, nx]:
                if dx and dy and (road[y, nx] or road[ny, x]):
                    continue
                found.append((nx, ny))
    return found


def _mark_corner(
    sampler: DetailSampler,
    nearest: np.ndarray,
    kind: np.ndarray,
    warped: tuple[np.ndarray, np.ndarray],
    centre: tuple[int, int],
    first: tuple[float, float],
    second: tuple[float, float],
    smooth: float,
    reach: float,
    limit: float,
) -> None:
    """Claim the cells near a tile's rounded corner: a quadratic curve from ``first`` to ``second``.

    ``first`` and ``second`` are the middles of the tile's two links. The curve's control point is the tile's centre
    taken ``smooth`` of the way from the chord's middle (1 is the full rounding, 0 the chord). It leaves each middle
    along its link, so it meets the neighbouring tile's curve there without a kink. A straight run stays straight.
    """
    mid = ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
    control = (mid[0] + smooth * (centre[0] - mid[0]), mid[1] + smooth * (centre[1] - mid[1]))
    if abs(control[0] - mid[0]) < 1e-9 and abs(control[1] - mid[1]) < 1e-9:
        _mark_segment(sampler, nearest, kind, warped, first, second, reach, limit)
        return
    previous = first
    for step in range(1, _CURVE_STEPS + 1):
        t = step / _CURVE_STEPS
        a, b, c = (1.0 - t) ** 2, 2.0 * (1.0 - t) * t, t * t
        point = (a * first[0] + b * control[0] + c * second[0], a * first[1] + b * control[1] + c * second[1])
        _mark_segment(sampler, nearest, kind, warped, previous, point, reach, limit)
        previous = point
