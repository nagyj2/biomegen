"""The tint layer: recolours the fill from a data ramp (elevation, temperature, rainfall, ...)."""

from __future__ import annotations

import numpy as np

from ...world.tile import Relief
from ..colors import ramp_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("tint")
def tint_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Replace the fill with the colour of the view's ramp (``render.ramps.<view.tint>``).

    The ramp's options decide the rest: ``shade`` hillshades land, ``water_scale`` / ``water_color``
    restyle water cells, and glyphs are blanked unless ``keep_relief`` keeps the relief glyphs (dimmed
    against the new fill). A view with no tint leaves the grid unchanged.
    """
    if not ctx.view.tint:
        return
    ramp = ctx.config.get(f"render.ramps.{ctx.view.tint}")
    inside = ctx.sampler.inside
    values = ctx.sampler.bilinear(getattr(ctx.world, ramp["field"]).astype(np.float64))
    bg = ramp_colors(ramp["stops"], values)
    water = inside & ~ctx.land
    if ramp.get("shade"):
        bg = np.where(ctx.land[..., np.newaxis], scale_colors(bg, ctx.shade), bg)
    if "water_scale" in ramp:
        bg = np.where(water[..., np.newaxis], scale_colors(bg, float(ramp["water_scale"])), bg)
    if "water_color" in ramp:
        bg = np.where(water[..., np.newaxis], np.asarray(ramp["water_color"], dtype=np.uint8), bg)

    relief_kept = ctx.land & (ctx.relief != int(Relief.NONE)) if ramp.get("keep_relief") else np.zeros_like(inside)
    glyph = np.where(relief_kept, grid.glyph, " ")
    fg = np.where(
        relief_kept[..., np.newaxis], scale_colors(bg, float(ctx.config.get("render.tint_relief_fg"))), grid.fg
    )
    grid.put(inside, glyph=glyph, fg=fg, bg=bg)
