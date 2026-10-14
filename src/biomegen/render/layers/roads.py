"""The roads layer: road tiles drawn with a glyph that follows their connections."""

from __future__ import annotations

import numpy as np

from ..grid import CellGrid
from . import LAYERS, LayerContext

_NORTH, _EAST, _SOUTH, _WEST = 1, 2, 4, 8


def connection_mask(road: np.ndarray) -> np.ndarray:
    """Return, per tile, a 0..15 bit mask of which of its four neighbours are also road."""
    padded = np.pad(road.astype(bool), 1)
    mask = np.zeros(road.shape, dtype=np.uint8)
    mask |= np.where(padded[:-2, 1:-1], _NORTH, 0).astype(np.uint8)
    mask |= np.where(padded[1:-1, 2:], _EAST, 0).astype(np.uint8)
    mask |= np.where(padded[2:, 1:-1], _SOUTH, 0).astype(np.uint8)
    mask |= np.where(padded[1:-1, :-2], _WEST, 0).astype(np.uint8)
    return mask


@LAYERS.register("roads")
def roads_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw road tiles with the glyph for their connection mask (``render.roads``); the fill is kept."""
    cfg = ctx.config.get("render.roads")
    road = ctx.sampler.inside & (ctx.sampler.nearest(ctx.world.road) > 0)
    if not road.any():
        return
    glyphs = np.array(cfg["ascii" if ctx.ascii_only else "glyphs"], dtype="U1")
    grid.put(road, glyph=glyphs[ctx.sampler.nearest(connection_mask(ctx.world.road))], fg=tuple(cfg["fg"]))
