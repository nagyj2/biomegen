"""The relief layer: hills, mountains, peaks and volcanoes drawn over the terrain."""

from __future__ import annotations

import numpy as np

from ...world.tile import Relief
from ..colors import mix_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("relief")
def relief_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw the relief glyph on land cells that have relief and recolour their fill (``render.relief_tints``)."""
    relief = ctx.relief
    raised = ctx.land & (relief != int(Relief.NONE))
    if not raised.any():
        return
    tints = ctx.config.get("render.relief_tints")
    style = ctx.relief_style
    bg = grid.bg.copy()
    fg = style.fg[relief]

    hills = raised & (relief == int(Relief.HILLS))
    bg = np.where(hills[..., np.newaxis], scale_colors(bg, float(tints["hills"]["scale"])), bg)

    mountain_cfg = tints["mountain"]
    mountain = raised & (relief == int(Relief.MOUNTAIN))
    rocky = mix_colors(bg, mountain_cfg["mix"], float(mountain_cfg["mix_t"]))
    snowy = mountain & (ctx.sampler.nearest(ctx.world.temperature_c) < float(mountain_cfg["snow_below_c"]))
    capped = mix_colors(rocky, mountain_cfg["snow_mix"], float(mountain_cfg["snow_t"]))
    bg = np.where(mountain[..., np.newaxis], np.where(snowy[..., np.newaxis], capped, rocky), bg)
    fg = np.where(snowy[..., np.newaxis], np.asarray(mountain_cfg["snow_fg"], dtype=np.uint8), fg)

    for name, relief_value in (("peak", Relief.PEAK), ("volcano", Relief.VOLCANO)):
        cell = raised & (relief == int(relief_value))
        row = tints[name]
        if "bg" in row:
            bg = np.where(cell[..., np.newaxis], np.asarray(row["bg"], dtype=np.uint8), bg)
        if "fg" in row:
            fg = np.where(cell[..., np.newaxis], np.asarray(row["fg"], dtype=np.uint8), fg)

    grid.put(raised, glyph=style.glyph[relief], fg=fg, bg=bg, bold=False)
