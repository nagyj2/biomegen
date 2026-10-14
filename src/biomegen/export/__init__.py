"""SVG (and optional PNG) export of the island - the Phase 6 layer.

Two public facades mirror the two in-game export keys (and the ``--export`` CLI flag):

* :func:`export_world` - the whole island at full 1:1 resolution (one ``export.cell_px`` square per
  world tile), region-coloured, with roads, POI markers and interior outlines. Bound to ``E``.
* :func:`export_view` - exactly the frame currently on screen (biome / zoom / local at the current
  camera), so you can grab a close-up of a dungeon just as you see it. Bound to ``e``.

Both reuse the **pure** frame builders the curses renderer uses (:func:`build_biome_frame` /
:func:`build_detail_frame`) and the curses-free :class:`~biomegen.export.colors.ExportPalette`, so the
exported image matches the TUI's layout and colours without re-implementing either. A frame is first
flattened into a renderer-agnostic *grid* of :data:`~biomegen.export.svg.Cell` tuples, which both the
SVG and PNG back-ends consume - guaranteeing the two formats are pixel-faithful to each other.

Output goes to ``export.dir`` (created on demand). The SVG is always written; the PNG is written only
when ``export.png`` is set *and* Pillow is installed - otherwise the SVG alone is produced and the
returned path list simply omits the PNG, so the caller can tell the user what happened.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from ..config.model import Config
from ..render.glyphs import Glyphs
from ..render.map_view import Frame, build_biome_frame
from ..render.state import ViewState
from ..render.zoom_view import ZoomFrame, build_detail_frame, detail_cell_size
from ..world.overlay import Overlay
from ..world.world import World
from . import png, svg
from .colors import BACKGROUND, ExportPalette, contrast_rgb

RGB = Tuple[int, int, int]
GridCell = svg.Cell  # (fill_rgb|None, glyph, glyph_rgb, bold)


# --------------------------------------------------------------------------- frame -> grid


def _biome_frame_to_grid(
    world: World,
    config: Config,
    frame: Frame,
    overlay: Optional[Overlay],
    pal: ExportPalette,
    glyphs: Glyphs,
) -> List[List[GridCell]]:
    """Flatten a biome-map :class:`Frame` into a colour/glyph grid (terrain < marker < interior stamp).

    Mirrors ``render.app._draw_biome``: an interior stamp wins over the terrain tile; a tile with a POI
    or road draws its marker glyph in bold. The transient cursor highlight is intentionally omitted.
    """
    grid: List[List[GridCell]] = []
    overrides = frame.overrides
    for ry in range(frame.rows):
        row: List[GridCell] = []
        for rx in range(frame.cols):
            coord = frame.tiles[ry][rx]
            stamp = overrides[ry][rx] if overrides is not None else None
            if stamp is not None:
                glyph, color_id = stamp
                fill = pal.zoom_rgb(color_id)
                if fill is not None:
                    row.append((fill, glyph, contrast_rgb(fill), False))
                    continue  # interior outline wins over the terrain underneath
            if coord is None:
                row.append((None, " ", BACKGROUND, False))  # out of bounds -> page background
                continue
            wx, wy = coord
            fill = pal.tile_rgb(world, wx, wy)
            glyph = _biome_glyph(world, glyphs, overlay, wx, wy)
            marker = int(world.poi_index[wy, wx]) >= 0 or bool(world.road[wy, wx])
            row.append((fill, glyph, contrast_rgb(fill), marker))
        grid.append(row)
    return grid


def _detail_frame_to_grid(frame: ZoomFrame, pal: ExportPalette) -> List[List[GridCell]]:
    """Flatten a magnified :class:`ZoomFrame` into a colour/glyph grid (mirrors ``app._draw_zoom``)."""
    grid: List[List[GridCell]] = []
    for row_cells in frame.cells:
        row: List[GridCell] = []
        for glyph, color_id in row_cells:
            fill = pal.zoom_rgb(color_id)
            glyph_rgb = contrast_rgb(fill) if fill is not None else BACKGROUND
            row.append((fill, glyph, glyph_rgb, False))
        grid.append(row)
    return grid


def _biome_glyph(world: World, glyphs: Glyphs, overlay: Optional[Overlay], x: int, y: int) -> str:
    """Glyph for a biome-map tile: overlay edit > POI marker > road marker > biome glyph.

    A standalone copy of ``render.app._tile_glyph`` so the exporter never imports the curses app.
    """
    if overlay is not None:
        edit = overlay.get_surface(x, y)
        if edit and "glyph" in edit:
            return edit["glyph"]
    i = int(world.poi_index[y, x])
    if 0 <= i < len(world.pois):
        return glyphs.marker(world.pois[i].kind, "?")
    if world.road[y, x]:
        return glyphs.marker("road", "+")
    return glyphs.biome_glyph(int(world.biome[y, x]))


# --------------------------------------------------------------------------- filenames + writing


def _sanitize(text: str) -> str:
    """Make ``text`` safe for a filename: keep word chars, turn runs of others into single ``_``."""
    out = []
    prev_us = False
    for ch in text:
        if ch.isalnum() or ch in "-.":
            out.append(ch)
            prev_us = False
        elif not prev_us:
            out.append("_")
            prev_us = True
    return "".join(out).strip("_") or "island"


def _base_name(config: Config, world: World, view: str) -> str:
    """Resolve ``export.filename_pattern`` for this world + view into a sanitized basename (no ext)."""
    pattern = config.get("export.filename_pattern", "{name}_{seed}_{view}")
    name = _sanitize(world.island_name or "island")
    raw = pattern.format(name=name, seed=world.seed, view=view)
    return _sanitize(raw)


def _write(grid: List[List[GridCell]], config: Config, world: World, view: str) -> List[str]:
    """Write ``grid`` as SVG (always) and PNG (if enabled and Pillow present); return written paths."""
    out_dir = config.get("export.dir", "./images")
    os.makedirs(out_dir, exist_ok=True)
    cell_px = max(1, int(config.get("export.cell_px", 12)))
    base = os.path.join(out_dir, _base_name(config, world, view))

    written: List[str] = []
    svg_path = base + ".svg"
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(svg.grid_to_svg(grid, cell_px, BACKGROUND))
    written.append(svg_path)

    if config.get("export.png", True):
        png_path = base + ".png"
        if png.grid_to_png(grid, cell_px, BACKGROUND, png_path):
            written.append(png_path)
    return written


# --------------------------------------------------------------------------- public facades


def export_world(world: World, config: Config, overlay: Optional[Overlay] = None) -> List[str]:
    """Export the whole island at full 1:1 resolution (one cell per world tile). Return written paths."""
    pal = ExportPalette(config, world)
    glyphs = Glyphs(config)
    vs = ViewState(cx=0, cy=0, mode="onetoone", cam_x=0, cam_y=0)
    frame = build_biome_frame(world, vs, world.width, world.height, config, overlay)
    grid = _biome_frame_to_grid(world, config, frame, overlay, pal, glyphs)
    return _write(grid, config, world, "world")


def export_view(
    world: World,
    config: Config,
    vs: ViewState,
    overlay: Optional[Overlay] = None,
    area_w: int = 160,
    area_h: int = 48,
) -> List[str]:
    """Export exactly the frame currently on screen (biome / zoom / local). Return written paths.

    ``vs`` carries the active scale, view mode and camera (already edge-panned by the app); ``area_w``
    / ``area_h`` are the on-screen map dimensions in terminal cells (defaults suit a headless call).
    """
    pal = ExportPalette(config, world)
    if vs.is_detail:
        cell_w, cell_h = detail_cell_size(vs.scale, config, area_w, area_h)
        frame = build_detail_frame(world, config, vs, area_w, area_h, cell_w, cell_h, overlay)
        grid = _detail_frame_to_grid(frame, pal)
        return _write(grid, config, world, vs.scale)
    glyphs = Glyphs(config)
    biome_frame = build_biome_frame(world, vs, area_w, area_h, config, overlay)
    grid = _biome_frame_to_grid(world, config, biome_frame, overlay, pal, glyphs)
    return _write(grid, config, world, "biome")
