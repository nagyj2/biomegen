"""Output back-ends: turn a finished grid or document into bytes. They do no drawing of their own."""

from __future__ import annotations

from typing import Optional

from ..grid import CellGrid

RGB = tuple[int, int, int]
# (fill colour or None=transparent, glyph, glyph colour, bold). A space glyph draws no text.
Cell = tuple[Optional[RGB], str, RGB, bool]


def cells_from_grid(grid: CellGrid) -> list[list[Cell]]:
    """Flatten a grid into the row-major cell tuples the SVG and PNG writers draw."""
    fills = grid.bg.tolist()
    glyph_colors = grid.fg.tolist()
    rows: list[list[Cell]] = []
    for row in range(grid.rows):
        cells: list[Cell] = []
        for col in range(grid.cols):
            fill_r, fill_g, fill_b = fills[row][col]
            glyph_r, glyph_g, glyph_b = glyph_colors[row][col]
            glyph = str(grid.glyph[row, col])
            cells.append(((fill_r, fill_g, fill_b), glyph, (glyph_r, glyph_g, glyph_b), bool(grid.bold[row, col])))
        rows.append(cells)
    return rows
