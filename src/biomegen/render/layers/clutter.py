"""The clutter layer: biome-appropriate scatter (trees, scree, grass tufts) over the detail-scale floor."""

from __future__ import annotations

import numpy as np

from ..grid import CellGrid
from . import LAYERS, LayerContext


def _clutter_factor(ctx: LayerContext, factor: np.ndarray) -> np.ndarray:
    """Return the per-cell density multiplier for each row's factor code (``render.clutter_factors``)."""
    cfg = ctx.config.get("render.clutter_factors")
    moisture = cfg["moisture"]
    elevation = cfg["elevation"]
    wetness = ctx.sampler.blended(ctx.world.moisture)
    top = max(1.0, float(ctx.world.elevation_m.max()))
    height = np.clip(ctx.sampler.blended(ctx.world.elevation_m) / top, 0.0, 1.0)
    by_moisture = np.clip(moisture["base"] + moisture["slope"] * wetness, moisture["min"], moisture["max"])
    by_elevation = np.clip(elevation["base"] + elevation["slope"] * height, elevation["min"], elevation["max"])
    return np.where(factor == 1, by_moisture, np.where(factor == 2, by_elevation, 1.0))


@LAYERS.register("clutter")
def clutter_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Scatter clutter glyphs over land cells from the detail rows (``tables.detail`` / ``detail_relief``).

    Each cell carries clutter with probability ``density`` times its row's factor (wetter is denser for
    vegetation, higher is denser for scree) and takes one glyph of its row's clutter string. The scatter is keyed
    on tile and sub-cell, so it holds still while panning. Only the glyph changes; colours stay.
    """
    style = ctx.detail_style
    row = ctx.detail_row
    used = style.clutter_len[row]
    density = np.where(used > 0, style.density[row] * _clutter_factor(ctx, style.factor[row]), 0.0)
    placed = ctx.land & (ctx.scatter("clutter") < density)
    if not placed.any():
        return
    pick = np.minimum((ctx.scatter("clutter", "glyph") * used).astype(np.int64), np.maximum(used - 1, 0))
    grid.put(placed, glyph=style.clutter_chars[row, pick])
