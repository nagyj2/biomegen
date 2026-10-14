"""The compass layer: a small rose stamped in the first map corner that is open sea."""

from __future__ import annotations

from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("compass")
def compass_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Stamp ``render.furniture.compass`` into a corner whose block is all water and has no other text."""
    cfg = ctx.config.get("render.furniture")
    rose = cfg["compass"]["ascii" if ctx.ascii_only else "unicode"]
    height, width = len(rose), len(rose[0])
    rows, cols = grid.rows, grid.cols
    corners = [(cols - width - 3, 1), (2, 1), (cols - width - 3, rows - height - 1), (2, rows - height - 1)]
    for x0, y0 in corners:
        if x0 < 0 or y0 < 0 or x0 + width > cols or y0 + height > rows:
            continue
        block = (slice(y0, y0 + height), slice(x0, x0 + width))
        in_open_sea = (ctx.sampler.inside[block] & ~ctx.land[block]).all()
        if in_open_sea and not grid.bold[block].any():  # bold cells are labels or markers
            for dy, line in enumerate(rose):
                for dx, char in enumerate(line):
                    if char != " ":
                        grid.glyph[y0 + dy, x0 + dx] = char
                        grid.fg[y0 + dy, x0 + dx] = cfg["compass_fg"]
                        grid.bold[y0 + dy, x0 + dx] = True
            return
