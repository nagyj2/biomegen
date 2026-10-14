"""The sites layer: each POI's plan drawn over the terrain where its site lies.

A plan is one grid of cells, sampled by nearest neighbour into the block of cells its extent covers, so every scale
shows the same plan at its own resolution. At the map scale only the structural outline (walls, doors, stairs) is
drawn, as a small image of the wall plan. At zoom the building shell is drawn (furniture shows as bare floor), a
low-poly silhouette that need not line up with the finer scales. At the local and site scales every cell is drawn.
Void cells are skipped, so the terrain shows round an organic outline. Runtime edits come from the overlay.
"""

from __future__ import annotations

import math

import numpy as np

from ...sampling.detail import SCALE_ZOOM, DetailSampler
from ...sites import SHELL, STRUCTURAL, SiteGeometry, site_plan, site_pois
from ...sites.blit import sample_rect
from ...world.entities import POI
from ...world.tile import Cell
from ..grid import CellGrid
from . import LAYERS, LayerContext

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_CELLS = max(int(cell) for cell in Cell) + 1


def _lookup(members: frozenset[int]) -> np.ndarray:
    table = np.zeros(_CELLS, dtype=bool)
    table[sorted(members)] = True
    return table


_SHELL = _lookup(SHELL)
_STRUCTURAL = _lookup(STRUCTURAL)


def _record(ctx: LayerContext, grid: CellGrid, rows: slice, cols: slice, cells: np.ndarray, draw: np.ndarray) -> None:
    """Note which plan cells were drawn: the set, and the cell under each grid cell."""
    if not draw.any():
        return
    ctx.seen.cells.update(np.flatnonzero(np.bincount(cells[draw], minlength=_CELLS)).tolist())
    if ctx.seen.cell_map is None:
        ctx.seen.cell_map = np.full(grid.glyph.shape, -1, dtype=np.int16)
    ctx.seen.cell_map[rows, cols][draw] = cells[draw]


def _cells_of(ctx: LayerContext, poi: POI, floor: int) -> np.ndarray | None:
    """Return ``poi``'s plan cells for ``floor`` with the overlay's edits applied, or None if it has no plan."""
    plan = site_plan(poi, floor, ctx.config, ctx.world)
    if plan is None:
        return None
    if ctx.overlay is not None:
        return ctx.overlay.apply_interior(plan.cells, poi.interior_seed, plan.floor)
    return plan.cells


def _stamp(ctx: LayerContext, grid: CellGrid, rows: slice, cols: slice, cells: np.ndarray, draw: np.ndarray) -> None:
    style = ctx.interior_style
    _record(ctx, grid, rows, cols, cells, draw)
    grid.glyph[rows, cols][draw] = style.glyph[cells][draw]
    grid.fg[rows, cols][draw] = style.fg[cells][draw]
    grid.bg[rows, cols][draw] = style.bg[cells][draw]
    grid.bold[rows, cols][draw] = False


def _map_outlines(ctx: LayerContext, grid: CellGrid) -> None:
    """Stamp the structural outline of each site's top floor onto the map cells its tiles cover.

    Everything that is not structural is left alone so terrain shows through the gaps, and the cell holding the POI's
    marker stays clear so the marker always wins.
    """
    sampler = ctx.sampler
    for poi, geometry in site_pois(ctx.world, ctx.config):
        left, top, right, bottom = geometry.extent
        first = sampler.cell_coords(math.floor(left - 0.5) + 1, math.floor(top - 0.5) + 1)
        last = sampler.cell_coords(math.ceil(right + 0.5) - 1, math.ceil(bottom + 0.5) - 1)
        if first is None or last is None:
            continue
        cells = _cells_of(ctx, poi, poi.lowest_floor + poi.floor_count - 1)
        if cells is None:
            continue
        sampled = sample_rect(
            cells, first[1], first[0], last[1] - first[1] + 1, last[0] - first[0] + 1, *grid.glyph.shape
        )
        if sampled is None:
            continue
        rows, cols, values = sampled
        draw = _STRUCTURAL[values]
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
    """Draw every site's plan for ``ctx.floor`` (clamped to its floors); at the map scale, its outline."""
    sampler = ctx.sampler
    if not isinstance(sampler, DetailSampler):
        _map_outlines(ctx, grid)
        return
    shell_only = sampler.scale == SCALE_ZOOM
    for poi, geometry in site_pois(ctx.world, ctx.config):
        row0, col0, span_rows, span_cols = _extent_cells(sampler, geometry)
        if row0 >= sampler.rows or col0 >= sampler.cols or row0 + span_rows <= 0 or col0 + span_cols <= 0:
            continue
        floor = max(poi.lowest_floor, min(int(ctx.floor), poi.lowest_floor + poi.floor_count - 1))
        cells = _cells_of(ctx, poi, floor)
        if cells is None:
            continue
        sampled = sample_rect(cells, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols)
        if sampled is None:
            continue
        rows, cols, values = sampled
        draw = (values != _VOID) & sampler.inside[rows, cols]
        if shell_only:  # furniture stands on a floor: draw that floor, not the terrain under it
            values = np.where(_SHELL[values], values, _FLOOR)
        _stamp(ctx, grid, rows, cols, values, draw)
