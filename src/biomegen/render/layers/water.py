"""The water layer: fresh water over a land biome (rivers) as a tinted glyph."""

from __future__ import annotations

from ...world.tile import WaterType
from ..colors import mix_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("water")
def water_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw river cells: land cells whose ``water_type`` is fresh get a water glyph and a blue-tinted fill."""
    river = ctx.land & (ctx.sampler.nearest(ctx.world.water_type) == int(WaterType.FRESH))
    if not river.any():
        return
    cfg = ctx.config.get("render.water")
    strength = float(cfg["river_mix_t_tinted" if ctx.view.tint else "river_mix_t"])
    bg = mix_colors(grid.bg, cfg["river_mix"], strength)
    grid.put(river, glyph=cfg["river_ascii" if ctx.ascii_only else "river_glyph"], fg=tuple(cfg["river_fg"]), bg=bg)
