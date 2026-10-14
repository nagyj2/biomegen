"""The interiors layer: each visible POI's building, camp or boat stamped over its footprint at the detail scales."""

from __future__ import annotations

import numpy as np

from ...interiors import INTERIOR_BUILDERS, ZOOM_VISIBLE, build_interior, footprint_origin, sample_rect_array
from ...world.tile import Cell, WaterType
from ..detail import SCALE_ZOOM, DetailSampler
from ..grid import CellGrid
from . import LAYERS, LayerContext

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_BRIDGE_CELLS = np.array([int(Cell.BRIDGE), int(Cell.BRIDGE_WALL)])
_ZOOM_VISIBLE = np.array(sorted(ZOOM_VISIBLE))


@LAYERS.register("interiors")
def interiors_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Stamp every POI that has an interior builder onto the cells of its footprint, for ``ctx.floor``.

    The interior is one canonical-resolution grid, sampled by nearest neighbour into the footprint's block of
    cells, so zoom and local are coarse and fine views of the same plan. At zoom only the building shell is drawn
    (:data:`~biomegen.interiors.ZOOM_VISIBLE`) and furniture shows as bare floor; at local every cell is. ``VOID``
    cells are skipped so the terrain shows around an organic outline. Nothing is laid over water except a boat's
    hull and bridge cells. Runtime edits come from the overlay. At the map scale nothing is drawn.
    """
    sampler = ctx.sampler
    if not isinstance(sampler, DetailSampler):
        return
    world = ctx.world
    style = ctx.interior_style
    shell_only = sampler.scale == SCALE_ZOOM
    for poi in world.pois:
        if not INTERIOR_BUILDERS.has(poi.kind):
            continue
        width, height = poi.footprint
        if width <= 0 or height <= 0:
            continue
        left, top = footprint_origin(poi)
        if (
            left + width <= sampler.cam_x
            or left >= sampler.cam_x + sampler.tiles_w
            or top + height <= sampler.cam_y
            or top >= sampler.cam_y + sampler.tiles_h
        ):
            continue
        floor = max(poi.lowest_floor, min(int(ctx.floor), poi.lowest_floor + poi.floor_count - 1))
        plan = build_interior(poi, floor, ctx.config, world)
        if plan is None:
            continue
        if ctx.overlay is not None:
            plan = ctx.overlay.apply_interior(plan, poi.interior_seed, floor)
        sampled = sample_rect_array(
            plan,
            (top - sampler.cam_y) * sampler.cell_h,
            (left - sampler.cam_x) * sampler.cell_w,
            height * sampler.cell_h,
            width * sampler.cell_w,
            sampler.rows,
            sampler.cols,
        )
        if sampled is None:
            continue
        rows, cols, cells = sampled
        draw = (cells != _VOID) & sampler.inside[rows, cols]
        if poi.kind != "boat":  # boats float; everything else forms around water, and this is the backstop
            wet = world.water_type[sampler.tile_y[rows, cols], sampler.tile_x[rows, cols]] != int(WaterType.NONE)
            draw &= ~(wet & ~np.isin(cells, _BRIDGE_CELLS))
        if shell_only:  # furniture stands on a floor: draw that floor, not the terrain under it
            cells = np.where(np.isin(cells, _ZOOM_VISIBLE), cells, _FLOOR)
        grid.glyph[rows, cols][draw] = style.glyph[cells][draw]
        grid.fg[rows, cols][draw] = style.fg[cells][draw]
        grid.bg[rows, cols][draw] = style.bg[cells][draw]
        grid.bold[rows, cols][draw] = False
