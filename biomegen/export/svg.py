"""Render an export *grid* to a standalone SVG document (no third-party dependency).

The grid is the renderer-agnostic intermediate the export facade produces from a view :class:`Frame`
(see :mod:`biomegen.export`): a 2-D list of :data:`Cell` tuples ``(fill_rgb, glyph, glyph_rgb,
bold)``. Each cell becomes a filled ``<rect>`` (the map colour) with the glyph centred on top as
``<text>`` - so the export reads as a coloured cartographic map whose glyphs (terrain, POI markers,
interior walls) stay legible. ``fill_rgb`` of ``None`` is transparent (the page background shows
through, e.g. out-of-bounds cells). The output is deterministic for a given grid: cells are emitted
in fixed row-major order with fixed numeric formatting, so a fixed seed always yields byte-identical
SVG (the golden-export test relies on this).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

RGB = Tuple[int, int, int]
# (fill colour or None=transparent, glyph, glyph colour, bold). A space glyph draws no text.
Cell = Tuple[Optional[RGB], str, RGB, bool]

# Monospace stack; the glyph is centred in its cell so any available mono face lines up on the grid.
_FONT_FAMILY = "'DejaVu Sans Mono','Consolas','Courier New',monospace"

_XML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _esc(text: str) -> str:
    """Escape the five XML-sensitive characters in glyph text."""
    return "".join(_XML_ESCAPE.get(ch, ch) for ch in text)


def _hex(rgb: RGB) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def grid_to_svg(grid: List[List[Cell]], cell_px: int, background: RGB) -> str:
    """Return a complete SVG document string for ``grid`` at ``cell_px`` pixels per cell.

    Horizontal runs of identical fill colour are merged into one ``<rect>`` to keep the file compact;
    glyphs are emitted as individual centred ``<text>`` elements (spaces are skipped).
    """
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    width = cols * cell_px
    height = rows * cell_px
    font_size = max(1, round(cell_px * 0.82))

    out: List[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" ')
    out.append(f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges">')
    out.append(f'<rect width="{width}" height="{height}" fill="{_hex(background)}"/>')

    # Pass 1: filled rectangles, merging same-colour horizontal runs per row.
    out.append("<g>")
    for ry, row in enumerate(grid):
        y = ry * cell_px
        cx = 0
        while cx < cols:
            fill = row[cx][0]
            if fill is None:
                cx += 1
                continue
            run = cx + 1
            while run < cols and row[run][0] == fill:
                run += 1
            out.append(
                f'<rect x="{cx * cell_px}" y="{y}" width="{(run - cx) * cell_px}" '
                f'height="{cell_px}" fill="{_hex(fill)}"/>'
            )
            cx = run
    out.append("</g>")

    # Pass 2: centred glyphs (skip spaces / empties).
    out.append(
        f'<g font-family="{_FONT_FAMILY}" font-size="{font_size}" text-anchor="middle" dominant-baseline="central">'
    )
    half = cell_px / 2
    for ry, row in enumerate(grid):
        ty = round(ry * cell_px + half)
        for cx, (_fill, glyph, glyph_rgb, bold) in enumerate(row):
            if not glyph or glyph == " ":
                continue
            tx = round(cx * cell_px + half)
            weight = ' font-weight="bold"' if bold else ""
            out.append(f'<text x="{tx}" y="{ty}" fill="{_hex(glyph_rgb)}"{weight}>{_esc(glyph)}</text>')
    out.append("</g>")

    out.append("</svg>")
    return "\n".join(out)
