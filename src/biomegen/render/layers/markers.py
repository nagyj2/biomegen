"""The markers layer: points of interest and runtime overlay glyphs."""

from __future__ import annotations

import numpy as np

from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("markers")
def markers_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw each POI anchor with its ``render.markers`` glyph, then apply overlay glyph edits on top."""
    world = ctx.world
    markers = ctx.config.get("render.markers")
    poi_index = ctx.sampler.nearest(world.poi_index)
    if world.pois:
        glyphs = np.array([markers.get(poi.kind, "?") for poi in world.pois], dtype="U1")
        anchored = ctx.sampler.inside & (poi_index >= 0)
        style = ctx.config.get("render.marker_style")
        grid.put(
            anchored,
            glyph=glyphs[np.clip(poi_index, 0, len(world.pois) - 1)],
            fg=tuple(style["fg"]),
            bg=tuple(style["bg"]),
            bold=True,
        )
    if ctx.overlay is not None:
        for (x, y), attrs in ctx.overlay.surface_edits():
            if "glyph" in attrs:
                at_tile = ctx.sampler.inside & (ctx.sampler.tile_x == x) & (ctx.sampler.tile_y == y)
                grid.put(at_tile, glyph=attrs["glyph"])
