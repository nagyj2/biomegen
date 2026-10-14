"""The roads layer: road tiles drawn with a glyph that follows their connections."""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...sampling.detail import SCALE_LOCAL, DetailSampler
from ...world.tile import WaterType
from ..colors import scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext

# Bits of the eight-neighbour connection mask, clockwise from north.
_N, _NE, _E, _SE, _S, _SW, _W, _NW = 1, 2, 4, 8, 16, 32, 64, 128
_CARDINAL_INDEX = ((_N, 1), (_E, 2), (_S, 4), (_W, 8))  # mask bit -> bit of the 16-entry cardinal glyph index
_RISING = (_NE, _SW)  # neighbours on a "╱" line; the other two diagonals (_SE, _NW) lie on a "╲" line
_DIAGONALS = (_NE, _SE, _SW, _NW)
# Bed glyph kinds, by the direction of the road link a detail cell lies on; the last is a lone road tile.
_BED_KINDS = ("horizontal", "vertical", "rising", "falling")
_LONE = len(_BED_KINDS)


def connection_mask8(road: np.ndarray) -> np.ndarray:
    """Return, per tile, a bit mask of its road links (N 1, NE 2, E 4, SE 8, S 16, SW 32, W 64, NW 128).

    An orthogonal neighbour counts when it is road. A diagonal neighbour counts only when neither orthogonal tile
    between it and this tile is road: otherwise the two already join through that tile, and the corner would be
    drawn as a spurious diagonal.
    """
    padded = np.pad(road.astype(bool), 1)
    north, east = padded[:-2, 1:-1], padded[1:-1, 2:]
    south, west = padded[2:, 1:-1], padded[1:-1, :-2]
    neighbours = (
        (_N, north),
        (_NE, padded[:-2, 2:] & ~north & ~east),
        (_E, east),
        (_SE, padded[2:, 2:] & ~south & ~east),
        (_S, south),
        (_SW, padded[2:, :-2] & ~south & ~west),
        (_W, west),
        (_NW, padded[:-2, :-2] & ~north & ~west),
    )
    mask = np.zeros(road.shape, dtype=np.uint8)
    for bit, present in neighbours:
        mask |= np.where(present, bit, 0).astype(np.uint8)
    return mask


def road_glyph_table(config: Config, ascii_only: bool) -> np.ndarray:
    """Return the glyph for each of the 256 eight-neighbour masks, so every way two roads can join is drawable.

    No diagonal neighbour: the box-drawing glyph for the cardinal mask (``render.roads.glyphs``), so an orthogonal
    junction is drawn as the matching tee or cross. Any diagonal neighbour: the junction glyph (an asterisk) wherever
    three or more links meet. Fewer than three: ``╱`` or ``╲`` along a line, ``╳`` where two diagonals bend, and the
    slant of the diagonal when a single diagonal link joins an orthogonal one.
    """
    cfg = config.get("render.roads")
    key = "ascii" if ascii_only else "glyphs"
    cardinal = cfg[key]
    rising, falling, crossing = cfg["diagonal"][key]
    junction = cfg["junction"][key]
    table = np.empty(256, dtype="U1")
    for mask in range(256):
        index = sum(value for bit, value in _CARDINAL_INDEX if mask & bit)
        diagonal = [bit for bit in _DIAGONALS if mask & bit]
        slants = {rising if bit in _RISING else falling for bit in diagonal}
        if not diagonal:
            table[mask] = cardinal[index]
        elif bin(mask).count("1") >= 3:
            table[mask] = junction
        elif len(slants) == 1 and (index or len(diagonal) <= 2):
            table[mask] = next(iter(slants))
        else:
            table[mask] = crossing
    return table


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


def _detail_roads(ctx: LayerContext, grid: CellGrid, sampler: DetailSampler) -> None:
    """Draw the road network as a thin meandering bed: cells within ``render.road_half_width`` tiles of a road link.

    The width is a fixed fraction of a tile, so it grows with the magnification, but never under
    ``render.road_min_rows`` rows thick.

    A link joins two neighbouring land-road tile centres (eight directions). The distance is measured at the
    road-warped position (``render.road_warp``), a pure function of world position, so zoom and local show the
    same bed at different scales. Water and river cells are left to bridges; the bed carries clutter glyphs
    (``render.road_clutter``, plus ``road_clutter_local`` at the local scale).
    """
    cfg = ctx.config
    half = float(cfg.get("render.road_half_width"))
    if half <= 0:
        return
    half = max(half, 0.5 * float(cfg.get("render.road_min_rows")) / sampler.cell_h)
    world = ctx.world
    land_road = (world.road > 0) & (world.water_type == int(WaterType.NONE))
    warp = max(float(cfg.get("render.road_warp")), 0.0)
    reach = half + warp
    x_lo, x_hi = (
        max(0, int(np.floor(sampler.cam_x - reach))),
        min(world.width, int(np.ceil(sampler.cam_x + sampler.tiles_w + reach))),
    )
    y_lo, y_hi = (
        max(0, int(np.floor(sampler.cam_y - reach))),
        min(world.height, int(np.ceil(sampler.cam_y + sampler.tiles_h + reach))),
    )
    if x_hi <= x_lo or y_hi <= y_lo:
        return
    tile_rows, tile_cols = np.nonzero(land_road[y_lo:y_hi, x_lo:x_hi])
    if len(tile_cols) == 0:
        return
    warped = sampler.warped(warp)
    nearest = np.full(sampler.fx.shape, np.inf)
    kind = np.full(sampler.fx.shape, _LONE, dtype=np.int8)
    # Each link once: the four "forward" directions, each with its bed glyph kind (a detail tile is a physical
    # square, so a one-tile diagonal step is a true 45 degree line); a tile with no link is a disc at its centre.
    forward = (((1, 0), 0), ((0, 1), 1), ((1, -1), 2), ((1, 1), 3))
    linked = connection_mask8(land_road) != 0
    for row, col in zip(tile_rows.tolist(), tile_cols.tolist(), strict=True):
        tx, ty = x_lo + col, y_lo + row
        if not linked[ty, tx]:
            _mark_segment(sampler, nearest, kind, warped, (tx, ty), (tx, ty), reach, half, _LONE)
        for (step_x, step_y), link_kind in forward:
            nx, ny = tx + step_x, ty + step_y
            if 0 <= nx < world.width and 0 <= ny < world.height and land_road[ny, nx]:
                _mark_segment(sampler, nearest, kind, warped, (tx, ty), (nx, ny), reach, half, link_kind)

    bed = np.isfinite(nearest) & ctx.land & ~ctx.river & ~ctx.site_mask
    if not bed.any():
        return
    key = "ascii" if ctx.ascii_only else "glyphs"
    bed_glyphs = cfg.get("render.road_bed")[key]
    lone = cfg.get("render.roads")[key][0]
    glyph = np.array([bed_glyphs[name] for name in _BED_KINDS] + [lone], dtype="U1")[kind]
    chance = ctx.scatter("road")
    choice = ctx.scatter("road", "glyph")
    clutter = cfg.get("render.road_clutter") or {}
    local = cfg.get("render.road_clutter_local") or {}
    clutter_glyphs = list(clutter.get("glyphs") or [])
    clutter_density = float(clutter.get("density", 0.0)) if clutter_glyphs else 0.0
    if clutter_glyphs:
        pick = np.minimum((choice * len(clutter_glyphs)).astype(np.int64), len(clutter_glyphs) - 1)
        glyph = np.where(chance < clutter_density, np.array(clutter_glyphs, dtype="U1")[pick], glyph)
    local_glyphs = list(local.get("glyphs") or [])
    if sampler.scale == SCALE_LOCAL and local_glyphs:
        pick = np.minimum((choice * len(local_glyphs)).astype(np.int64), len(local_glyphs) - 1)
        extra = (chance >= clutter_density) & (chance < clutter_density + float(local.get("density", 0.0)))
        glyph = np.where(extra, np.array(local_glyphs, dtype="U1")[pick], glyph)
    colors = cfg.get("render.detail_colors")
    grid.put(bed, glyph=glyph, fg=tuple(colors["road_fg"]), bg=scale_colors(colors["road_bg"], ctx.shade))


@LAYERS.register("roads")
def roads_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw road tiles with the glyph for their eight-neighbour mask (:func:`road_glyph_table`); the fill is kept.

    At the detail scales roads are a thin bed instead (see :func:`_detail_roads`).
    """
    if isinstance(ctx.sampler, DetailSampler):
        _detail_roads(ctx, grid, ctx.sampler)
        return
    cfg = ctx.config.get("render.roads")
    road = ctx.sampler.inside & (ctx.sampler.nearest(ctx.world.road) > 0)
    if not road.any():
        return
    glyphs = road_glyph_table(ctx.config, ctx.ascii_only)
    grid.put(road, glyph=glyphs[ctx.sampler.nearest(connection_mask8(ctx.world.road))], fg=tuple(cfg["fg"]))
