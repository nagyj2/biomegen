"""The sites layer: each POI's plan drawn over the terrain where its site lies.

A plan has two faces. Seen from **outside** (the map, zoom and local scales) buildings are roofs, walls are solid and
streets show; the plan is scaled to the block of cells its extent covers, and where it is finer than the view the cell
of highest priority wins, so a one-cell wall survives. Seen from **inside** (the site scale) every cell is drawn one for
one, and thin walls join into box-drawing lines. Void cells are skipped, so the terrain shows round an organic outline.
Outside views show the surface; the inside view shows the chosen floor, with runtime edits from the overlay.
"""

from __future__ import annotations

import math

import numpy as np

from ...sampling.detail import SCALE_SITE, DetailSampler
from ...sites import NO_WALL, OUTSIDE_PRIORITY, SiteGeometry, site_plan, site_pois, wall_index
from ...sites.blit import sample_rect
from ...world.entities import POI
from ...world.tile import Cell
from ..colors import wall_glyph_table
from ..grid import CellGrid
from . import LAYERS, LayerContext

_VOID = int(Cell.VOID)
_CELLS = max(int(cell) for cell in Cell) + 1


def _record(ctx: LayerContext, grid: CellGrid, rows: slice, cols: slice, cells: np.ndarray, draw: np.ndarray) -> None:
    """Note which plan cells were drawn: the set, and the cell under each grid cell."""
    if not draw.any():
        return
    ctx.seen.cells.update(np.flatnonzero(np.bincount(cells[draw], minlength=_CELLS)).tolist())
    if ctx.seen.cell_map is None:
        ctx.seen.cell_map = np.full(grid.glyph.shape, -1, dtype=np.int16)
    ctx.seen.cell_map[rows, cols][draw] = cells[draw]


def _plan_of(ctx: LayerContext, poi: POI, floor: int, inside: bool) -> tuple[np.ndarray, np.ndarray | None] | None:
    """Return ``poi``'s plan cells (and, inside, the wall line index of each) for ``floor``, or None if it has no plan.

    Inside, the overlay's edits are applied; outside is the surface and ignores both the floor and the overlay.
    """
    plan = site_plan(poi, floor, ctx.config, ctx.world)
    if plan is None:
        return None
    if not inside:
        return plan.outside, None
    cells = plan.cells
    if ctx.overlay is not None:
        cells = ctx.overlay.apply_interior(cells, poi.interior_seed, plan.floor)
    return cells, wall_index(cells)


def _stamp(
    ctx: LayerContext,
    grid: CellGrid,
    rows: slice,
    cols: slice,
    cells: np.ndarray,
    draw: np.ndarray,
    walls: np.ndarray | None = None,
) -> None:
    style = ctx.interior_style
    _record(ctx, grid, rows, cols, cells, draw)
    glyph = style.glyph[cells]
    if walls is not None:
        lines = wall_glyph_table(ctx.config, ctx.ascii_only)
        glyph = np.where(walls != NO_WALL, lines[np.minimum(walls, 15)], glyph)
    grid.glyph[rows, cols][draw] = glyph[draw]
    grid.fg[rows, cols][draw] = style.fg[cells][draw]
    grid.bg[rows, cols][draw] = style.bg[cells][draw]
    grid.bold[rows, cols][draw] = False


def _map_outlines(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw each site's outside view onto the map cells its tiles cover, leaving the POI's marker cell clear."""
    sampler = ctx.sampler
    rows_total, cols_total = grid.glyph.shape
    for poi, geometry in site_pois(ctx.world, ctx.config):
        left, top, right, bottom = geometry.extent
        first = sampler.cell_coords(math.floor(left - 0.5) + 1, math.floor(top - 0.5) + 1)
        last = sampler.cell_coords(math.ceil(right + 0.5) - 1, math.ceil(bottom + 0.5) - 1)
        if first is None or last is None:
            continue
        if first[1] >= rows_total or first[0] >= cols_total or last[1] < 0 or last[0] < 0:
            continue
        found = _plan_of(ctx, poi, 0, False)
        if found is None:
            continue
        sampled = sample_rect(
            found[0],
            first[1],
            first[0],
            last[1] - first[1] + 1,
            last[0] - first[0] + 1,
            rows_total,
            cols_total,
            OUTSIDE_PRIORITY,
        )
        if sampled is None:
            continue
        rows, cols, values = sampled
        draw = values != _VOID
        marker = sampler.cell_coords(poi.x, poi.y)
        if marker is not None and rows.start <= marker[1] < rows.stop and cols.start <= marker[0] < cols.stop:
            draw[marker[1] - rows.start, marker[0] - cols.start] = False
        _stamp(ctx, grid, rows, cols, values, draw)


def _extent_cells(sampler: DetailSampler, geometry: SiteGeometry) -> tuple[int, int, int, int]:
    """Return ``(row0, col0, rows, cols)``: the cells of a detail grid that the site's extent covers."""
    left, top, right, bottom = geometry.extent
    col0 = round((left - (sampler.cam_x - 0.5)) * sampler.cell_w)
    col1 = round((right - (sampler.cam_x - 0.5)) * sampler.cell_w)
    row0 = round((top - (sampler.cam_y - 0.5)) * sampler.cell_h)
    row1 = round((bottom - (sampler.cam_y - 0.5)) * sampler.cell_h)
    return row0 - sampler.row0, col0 - sampler.col0, row1 - row0, col1 - col0


@LAYERS.register("sites")
def sites_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw every site: its outside at the map, zoom and local scales, its inside (``ctx.floor``) at the site scale."""
    sampler = ctx.sampler
    if not isinstance(sampler, DetailSampler):
        _map_outlines(ctx, grid)
        return
    inside = sampler.scale == SCALE_SITE
    for poi, geometry in site_pois(ctx.world, ctx.config):
        row0, col0, span_rows, span_cols = _extent_cells(sampler, geometry)
        if row0 >= sampler.rows or col0 >= sampler.cols or row0 + span_rows <= 0 or col0 + span_cols <= 0:
            continue
        floor = max(poi.lowest_floor, min(int(ctx.floor), poi.lowest_floor + poi.floor_count - 1)) if inside else 0
        found = _plan_of(ctx, poi, floor, inside)
        if found is None:
            continue
        cells, walls = found
        priority = None if inside else OUTSIDE_PRIORITY
        sampled = sample_rect(cells, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols, priority)
        if sampled is None:
            continue
        rows, cols, values = sampled
        sampled_walls = None
        if walls is not None:
            *_, sampled_walls = sample_rect(walls, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols)  # type: ignore[misc]
        draw = (values != _VOID) & sampler.inside[rows, cols]
        _stamp(ctx, grid, rows, cols, values, draw, sampled_walls)
