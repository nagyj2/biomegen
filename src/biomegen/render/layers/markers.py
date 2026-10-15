"""The markers layer: points of interest and runtime overlay glyphs."""

from __future__ import annotations

import numpy as np

from ...sampling.detail import SCALE_SITE, DetailSampler
from ..grid import CellGrid
from ..poi_style import poi_marker, poi_on_map
from . import LAYERS, LayerContext


@LAYERS.register("markers")
def markers_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw each POI anchor with its marker (:func:`~biomegen.render.poi_style.poi_marker`), then apply overlay edits.

    A tile is drawn once: at a detail scale only the centre cell of its block carries the glyph. A marker with no
    background colour keeps the terrain's. A detail scale draws POI markers only when it is listed in
    ``render.detail_marker_scales`` (the zoom scale); the others show the plan itself. Surface edits from the overlay
    draw at every scale but the site scale, where the plan covers the ground.
    """
    world = ctx.world
    poi_index = ctx.sampler.nearest(world.poi_index)
    sampler = ctx.sampler
    shown = not isinstance(sampler, DetailSampler) or sampler.scale in ctx.config.get("render.detail_marker_scales")
    if world.pois and shown:
        styles = [poi_marker(ctx.config, poi.kind, ctx.ascii_only, poi.free) for poi in world.pois]
        glyphs = np.array([glyph for glyph, _fg, _bg in styles], dtype="U1")
        fgs = np.array([fg for _glyph, fg, _bg in styles], dtype=np.uint8)
        bgs = np.array([bg if bg is not None else (0, 0, 0) for _glyph, _fg, bg in styles], dtype=np.uint8)
        has_bg = np.array([bg is not None for _glyph, _fg, bg in styles])
        at = np.clip(poi_index, 0, len(world.pois) - 1)
        anchored = ctx.sampler.inside & ctx.sampler.anchor & (poi_index >= 0)
        if not isinstance(sampler, DetailSampler):  # the map scale leaves out kinds whose row hides them there
            on_map = np.array([poi_on_map(ctx.config, poi.kind) for poi in world.pois])
            anchored &= on_map[np.clip(poi_index, 0, len(world.pois) - 1)]
        grid.put(anchored, glyph=glyphs[at], fg=fgs[at], bold=True)
        grid.put(anchored & has_bg[at], bg=bgs[at])
    if ctx.overlay is not None and not (isinstance(sampler, DetailSampler) and sampler.scale == SCALE_SITE):
        for (x, y), attrs in ctx.overlay.surface_edits():
            if "glyph" in attrs:
                at_tile = (
                    ctx.sampler.inside & ctx.sampler.anchor & (ctx.sampler.tile_x == x) & (ctx.sampler.tile_y == y)
                )
                grid.put(at_tile, glyph=attrs["glyph"])
