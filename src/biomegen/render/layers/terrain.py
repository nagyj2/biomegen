"""The terrain layer: biome colours and glyphs, sea depth, hillshade and sparse-glyph scatter.

At the detail scales the glyph is the biome's floor (a rocky floor on mountain relief) on every cell.
"""

from __future__ import annotations

import numpy as np

from ...world.tile import Biome
from ..colors import mix_colors, scale_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("terrain")
def terrain_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Fill every cell inside the world from its biome row; shade land, deepen the sea, thin sparse glyphs."""
    style = ctx.biome_style
    biome = ctx.biome
    detailed = ctx.sampler.detailed
    ctx.seen.biomes.update(np.unique(biome[ctx.sampler.inside]).tolist())
    glyph = ctx.detail_floor if detailed else style.glyph[biome]
    fg = style.fg[biome]
    bg = style.bg[biome]

    # Colour maths runs on the cells it changes only; the per-cell arithmetic is the same as over the whole grid.
    sea = ctx.biome_is(Biome.DEEP, Biome.SHALLOW)
    if sea.any():
        depth = np.clip(-ctx.elevation_m[sea] / float(ctx.config.get("render.sea_depth_m")), 0.0, 1.0)
        bg[sea] = mix_colors(style.bg[int(Biome.SHALLOW)], style.bg[int(Biome.DEEP)], np.sqrt(depth))
    land = ctx.land
    if land.any():
        bg[land] = scale_colors(bg[land], ctx.shade[land])

    if ctx.color and not detailed:  # detail floors are drawn on every cell: clutter does the scattering
        sparkle_cfg = ctx.config.get("render.sea_sparkle")
        sparkle = ctx.biome_is(Biome.DEEP) & (ctx.scatter("sparkle") < float(sparkle_cfg["density"]))
        glyph = np.where(sparkle, sparkle_cfg["ascii" if ctx.ascii_only else "glyph"], glyph)
        fg[sparkle] = scale_colors(bg[sparkle], float(sparkle_cfg["boost"]))
        hidden = (
            ctx.land & style.sparse[biome] & (ctx.scatter("sparse") >= float(ctx.config.get("render.sparse_density")))
        )
        glyph = np.where(hidden, " ", glyph)

    grid.put(ctx.sampler.inside, glyph=glyph, fg=fg, bg=bg)
