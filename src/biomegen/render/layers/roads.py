"""The roads layer: road tiles drawn with a glyph that follows their connections."""

from __future__ import annotations

import numpy as np

from ...world.tile import WaterType
from ..colors import scale_colors
from ..detail import SCALE_LOCAL, DetailSampler
from ..grid import CellGrid
from . import LAYERS, LayerContext

_NORTH, _EAST, _SOUTH, _WEST = 1, 2, 4, 8


def connection_mask(road: np.ndarray) -> np.ndarray:
    """Return, per tile, a 0..15 bit mask of which of its four neighbours are also road."""
    padded = np.pad(road.astype(bool), 1)
    mask = np.zeros(road.shape, dtype=np.uint8)
    mask |= np.where(padded[:-2, 1:-1], _NORTH, 0).astype(np.uint8)
    mask |= np.where(padded[1:-1, 2:], _EAST, 0).astype(np.uint8)
    mask |= np.where(padded[2:, 1:-1], _SOUTH, 0).astype(np.uint8)
    mask |= np.where(padded[1:-1, :-2], _WEST, 0).astype(np.uint8)
    return mask


def _mark_segment(
    sampler: DetailSampler,
    is_road: np.ndarray,
    warped: tuple[np.ndarray, np.ndarray],
    start: tuple[int, int],
    end: tuple[int, int],
    reach: float,
    half: float,
) -> None:
    """Set ``is_road`` on the cells whose warped position is within ``half`` tiles of the segment ``start -> end``."""
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
    is_road[window] |= distance <= half


def _detail_roads(ctx: LayerContext, grid: CellGrid, sampler: DetailSampler) -> None:
    """Draw the road network as a thin meandering bed: cells within ``render.road_half_width`` tiles of a road link.

    A link joins two neighbouring land-road tile centres (eight directions). The distance is measured at the
    road-warped position (``render.road_warp``), a pure function of world position, so zoom and local show the
    same bed at different scales. Water and river cells are left to bridges; the bed carries clutter glyphs
    (``render.road_clutter``, plus ``road_clutter_local`` at the local scale).
    """
    cfg = ctx.config
    half = float(cfg.get("render.road_half_width"))
    if half <= 0:
        return
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
    is_road = np.zeros(sampler.fx.shape, dtype=bool)
    # Each link once: the four "forward" directions; a tile with no link is a disc at its centre.
    forward = ((1, 0), (0, 1), (1, 1), (1, -1))
    for row, col in zip(tile_rows.tolist(), tile_cols.tolist(), strict=True):
        tx, ty = x_lo + col, y_lo + row
        _mark_segment(sampler, is_road, warped, (tx, ty), (tx, ty), reach, half)
        for step_x, step_y in forward:
            nx, ny = tx + step_x, ty + step_y
            if 0 <= nx < world.width and 0 <= ny < world.height and land_road[ny, nx]:
                _mark_segment(sampler, is_road, warped, (tx, ty), (nx, ny), reach, half)

    bed = is_road & ctx.land & ~ctx.river
    if not bed.any():
        return
    glyph = np.full(is_road.shape, str(cfg.get("render.road_glyph")), dtype="U1")
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
    """Draw road tiles with the glyph for their connection mask (``render.roads``); the fill is kept.

    At the detail scales roads are a thin bed instead (see :func:`_detail_roads`).
    """
    if isinstance(ctx.sampler, DetailSampler):
        _detail_roads(ctx, grid, ctx.sampler)
        return
    cfg = ctx.config.get("render.roads")
    road = ctx.sampler.inside & (ctx.sampler.nearest(ctx.world.road) > 0)
    if not road.any():
        return
    glyphs = np.array(cfg["ascii" if ctx.ascii_only else "glyphs"], dtype="U1")
    grid.put(road, glyph=glyphs[ctx.sampler.nearest(connection_mask(ctx.world.road))], fg=tuple(cfg["fg"]))
