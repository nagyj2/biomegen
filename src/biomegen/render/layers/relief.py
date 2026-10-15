"""The relief layer: hills, mountains, peaks and volcanoes drawn over the terrain."""

from __future__ import annotations

import numpy as np

from ...world.tile import Relief
from ..colors import mix_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("relief")
def relief_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw the relief glyph on land cells that have relief and recolour their fill (``render.relief_tints``).

    At the detail scales a tile is many cells, so the glyph is not repeated across the block: the terrain layer's
    rocky floor stands in for it and this layer only recolours.
    """
    relief = ctx.relief
    raised = ctx.land & (relief != int(Relief.NONE))
    if not raised.any():
        return
    tints = ctx.config.get("render.relief_tints")
    style = ctx.relief_style
    bg = grid.bg.copy()
    fg = style.fg[relief]

    # Each tint is worked out on its own cells only; the per-cell arithmetic is the same as over the whole grid.
    hills = raised & (relief == int(Relief.HILLS))
    bg[hills] = scale_colors(bg[hills], float(tints["hills"]["scale"]))

    mountain_cfg = tints["mountain"]
    mountain = raised & (relief == int(Relief.MOUNTAIN))
    if mountain.any():
        snowy = mountain & (ctx.sampler.nearest(ctx.world.temperature_c) < float(mountain_cfg["snow_below_c"]))
        rocky = mix_colors(bg[mountain], mountain_cfg["mix"], float(mountain_cfg["mix_t"]))
        capped = snowy[mountain]
        rocky[capped] = mix_colors(rocky[capped], mountain_cfg["snow_mix"], float(mountain_cfg["snow_t"]))
        bg[mountain] = rocky
        fg[snowy] = np.asarray(mountain_cfg["snow_fg"], dtype=np.uint8)

    for name, relief_value in (("peak", Relief.PEAK), ("volcano", Relief.VOLCANO)):
        cell = raised & (relief == int(relief_value))
        row = tints[name]
        if "bg" in row:
            bg[cell] = np.asarray(row["bg"], dtype=np.uint8)
        if "fg" in row:
            fg[cell] = np.asarray(row["fg"], dtype=np.uint8)

    if ctx.sampler.detailed:  # the rocky floor from the terrain layer stays; only the colours change
        grid.put(raised, fg=fg, bg=bg, bold=False)
        return
    grid.put(raised, glyph=style.glyph[relief], fg=fg, bg=bg, bold=False)
