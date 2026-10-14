"""The bridges layer: each bridge POI as a straight deck flanked by walls, at the detail scales."""

from __future__ import annotations

import numpy as np

from ..colors import scale_colors
from ..detail import DetailSampler
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("bridges")
def bridges_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw every ``bridge`` POI as a deck between the road pieces it joins, over whatever water it spans.

    The deck is the straight span from ``extra["p0"]`` to ``extra["p1"]`` at its real angle. Cells within
    ``max(render.road_half_width, 0.18)`` tiles of it (measured across the span, clamped to its length plus
    ``render.bridge_overhang`` at each end so it overlaps the road bed) are the deck; a band as wide again on
    either long side is the wall. The unwarped positions are used, so the span reads dead straight. At the map
    scale a bridge is a marker, so this layer draws nothing there.
    """
    sampler = ctx.sampler
    if not isinstance(sampler, DetailSampler):
        return
    cfg = ctx.config
    glyphs = cfg.get("render.bridge_glyphs") or {}
    colors = cfg.get("render.detail_colors")
    deck_half = max(float(cfg.get("render.road_half_width")), 0.18)
    overhang = float(cfg.get("render.bridge_overhang"))
    reach = 2.0 * deck_half + overhang
    for poi in ctx.world.pois:
        if poi.kind != "bridge":
            continue
        start = poi.extra.get("p0") or [poi.x, poi.y]
        end = poi.extra.get("p1") or [poi.x, poi.y]
        ax, ay, bx, by = float(start[0]), float(start[1]), float(end[0]), float(end[1])
        window = sampler.cell_window(min(ax, bx) - reach, max(ax, bx) + reach, min(ay, by) - reach, max(ay, by) + reach)
        if window is None:
            continue
        x = sampler.fx[window]
        y = sampler.fy[window]
        span = float(np.hypot(bx - ax, by - ay))
        if span <= 1e-6:
            across = np.hypot(x - ax, y - ay)
            along_ok = np.ones_like(x, dtype=bool)
        else:
            ux, uy = (bx - ax) / span, (by - ay) / span
            along = (x - ax) * ux + (y - ay) * uy
            across = np.abs((x - ax) * -uy + (y - ay) * ux)
            along_ok = (along >= -overhang) & (along <= span + overhang)
        inside = sampler.inside[window]
        wall = along_ok & inside & (across > deck_half) & (across <= 2.0 * deck_half)
        deck = along_ok & inside & (across <= deck_half)
        for mask, part in ((wall, "wall"), (deck, "deck")):
            if mask.any():
                full = np.zeros(sampler.fx.shape, dtype=bool)
                full[window] = mask
                grid.put(
                    full,
                    glyph=str(glyphs.get(part, ":" if part == "deck" else "#")),
                    fg=tuple(colors[f"{part}_fg"]),
                    bg=scale_colors(colors[f"{part}_bg"], ctx.shade),
                )
