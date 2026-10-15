"""The sites layer: each POI's plan drawn over the terrain where its site lies.

A plan has two faces. Seen from **outside** (the zoom and local scales) buildings are roofs, walls are solid and
streets show; the plan is scaled to the block of cells its extent covers, and where it is finer than the view the cell
of highest priority wins, so a one-cell wall survives. Seen from **inside** (the site scale) every cell is drawn one for
one, and thin walls join into box-drawing lines. Void cells are skipped, so the terrain shows round an organic outline.
The world map draws no plan: a POI there is its one-tile marker (the markers layer).
Outside views show the surface; the inside view shows the chosen floor, with runtime edits from the overlay. A floor
above the ground of a settlement also carries its ground-level streets, trees and walls (``SitePlan.ground``), drawn
first and dimmed by ``render.ground_dim`` so the floor's own cells stand out over them.
"""

from __future__ import annotations

import numpy as np

from ...sampling.detail import SCALE_SITE, DetailSampler
from ...sites import NO_WALL, OUTSIDE_PRIORITY, SiteGeometry, site_plan, site_pois, wall_index
from ...sites.blit import sample_rect
from ...world.entities import POI
from ...world.tile import Cell
from ..colors import scale_colors, wall_glyph_table
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


def _plan_of(
    ctx: LayerContext, poi: POI, floor: int, inside: bool
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None] | None:
    """Return ``poi``'s plan cells, their wall line index and the dimmed ground under them, for ``floor``.

    ``None`` when the POI has no plan. Inside, the overlay's edits are applied and the walls and the ground (``None``
    on most floors) come with it; outside is the surface and ignores the floor, the overlay and the ground.
    """
    plan = site_plan(poi, floor, ctx.config, ctx.world)
    if plan is None:
        return None
    if not inside:
        return plan.outside, None, None
    cells = plan.cells
    if ctx.overlay is not None:
        cells = ctx.overlay.apply_interior(cells, poi.interior_seed, plan.floor)
    return cells, wall_index(cells), plan.ground


def _stamp(
    ctx: LayerContext,
    grid: CellGrid,
    rows: slice,
    cols: slice,
    cells: np.ndarray,
    draw: np.ndarray,
    walls: np.ndarray | None = None,
    dim: float | None = None,
) -> None:
    """Paint ``cells`` where ``draw`` holds; with ``dim`` their colours are scaled by it and they are not recorded."""
    style = ctx.interior_style
    if dim is None:
        _record(ctx, grid, rows, cols, cells, draw)
    glyph = style.glyph[cells]
    if walls is not None:
        lines = wall_glyph_table(ctx.config, ctx.ascii_only)
        glyph = np.where(walls != NO_WALL, lines[np.minimum(walls, 15)], glyph)
    fg, bg = style.fg[cells], style.bg[cells]
    if dim is not None:
        fg, bg = scale_colors(fg, dim), scale_colors(bg, dim)
    grid.glyph[rows, cols][draw] = glyph[draw]
    grid.fg[rows, cols][draw] = fg[draw]
    grid.bg[rows, cols][draw] = bg[draw]
    grid.bold[rows, cols][draw] = False


def _extent_cells(sampler: DetailSampler, geometry: SiteGeometry) -> tuple[int, int, int, int]:
    """Return ``(row0, col0, rows, cols)``: the cells of a detail grid that the site's extent covers."""
    left, top, right, bottom = geometry.extent
    col0 = round((left - (sampler.cam_x - 0.5)) * sampler.cell_w)
    col1 = round((right - (sampler.cam_x - 0.5)) * sampler.cell_w)
    row0 = round((top - (sampler.cam_y - 0.5)) * sampler.cell_h)
    row1 = round((bottom - (sampler.cam_y - 0.5)) * sampler.cell_h)
    return row0 - sampler.row0, col0 - sampler.col0, row1 - row0, col1 - col0


def _stamp_ground(
    ctx: LayerContext, grid: CellGrid, ground: np.ndarray, extent: tuple[int, int, int, int], sampler: DetailSampler
) -> None:
    """Draw an upper floor's ground-level features dimmed, before the floor's own cells are stamped over them."""
    row0, col0, span_rows, span_cols = extent
    sampled = sample_rect(ground, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols)
    if sampled is None:
        return
    rows, cols, values = sampled
    *_, lines = sample_rect(wall_index(ground), row0, col0, span_rows, span_cols, sampler.rows, sampler.cols)  # type: ignore[misc]
    draw = (values != _VOID) & sampler.inside[rows, cols]
    _stamp(ctx, grid, rows, cols, values, draw, lines, float(ctx.config.get("render.ground_dim")))


@LAYERS.register("sites")
def sites_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw every site: its outside at the zoom and local scales, its inside (``ctx.floor``) at the site scale."""
    sampler = ctx.sampler
    if not isinstance(sampler, DetailSampler):
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
        cells, walls, ground = found
        priority = None if inside else OUTSIDE_PRIORITY
        sampled = sample_rect(cells, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols, priority)
        if sampled is None:
            continue
        rows, cols, values = sampled
        if ground is not None:
            _stamp_ground(ctx, grid, ground, (row0, col0, span_rows, span_cols), sampler)
        sampled_walls = None
        if walls is not None:
            *_, sampled_walls = sample_rect(walls, row0, col0, span_rows, span_cols, sampler.rows, sampler.cols)  # type: ignore[misc]
        draw = (values != _VOID) & sampler.inside[rows, cols]
        _stamp(ctx, grid, rows, cols, values, draw, sampled_walls)
