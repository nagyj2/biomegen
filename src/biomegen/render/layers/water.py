"""The water layer: fresh water over a land biome (rivers) as a tinted glyph."""

from __future__ import annotations

from ..colors import mix_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("water")
def water_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw river cells: land cells whose ``water_type`` is fresh get a water glyph and a blue-tinted fill.

    At the detail scales the river is the sampler's smoothed coverage of the river tiles, so a river running
    diagonally stays one stream instead of a staircase of blocks.
    """
    river = ctx.river
    if not river.any():
        return
    cfg = ctx.config.get("render.water")
    strength = float(cfg["river_mix_t_tinted" if ctx.view.tint else "river_mix_t"])
    grid.put(river, glyph=cfg["river_ascii" if ctx.ascii_only else "river_glyph"], fg=tuple(cfg["river_fg"]))
    grid.bg[river] = mix_colors(grid.bg[river], cfg["river_mix"], strength)
