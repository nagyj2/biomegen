"""The borders layer: lines between realms and red war fronts, for the political view."""

from __future__ import annotations

import numpy as np

from ..colors import mix_colors
from ..grid import CellGrid
from . import LAYERS, LayerContext


@LAYERS.register("borders")
def borders_layer(ctx: LayerContext, grid: CellGrid) -> None:
    """Draw a line wherever two neighbouring land cells belong to different realms (``render.borders``).

    Only the cell of the pair with the larger realm id is marked (wild land counts as -1), so a border is one cell
    wide at every scale. Realms are read through :attr:`LayerContext.realm`, warped like the biome blend, so the line
    wobbles identically at the zoom and local scales. A border between a vassal and its own overlord is fainter; where
    ``World.front`` marks a war the line is red. Cells on the grid's edge are compared only with the neighbours inside
    it.
    """
    world = ctx.world
    if not world.realms:
        return
    cfg = ctx.config.get("render.borders")
    realm = ctx.realm
    # Index -1 is wild land, so these tables read -1 as "no realm" through numpy's negative indexing.
    tops = np.array([world.top_realm(r.id) for r in world.realms] + [-1])
    hard = np.zeros(realm.shape, dtype=bool)
    soft = np.zeros(realm.shape, dtype=bool)
    pairs = (
        ((slice(None), slice(None, -1)), (slice(None), slice(1, None))),
        ((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
    )
    for first, second in pairs:
        a, b = realm[first], realm[second]
        differ = ctx.land[first] & ctx.land[second] & (a != b)
        same_top = (tops[a] == tops[b]) & (a >= 0) & (b >= 0)
        larger_is_first = a > b
        for mask, target in ((differ & ~same_top, hard), (differ & same_top, soft)):
            target[first] |= mask & larger_is_first
            target[second] |= mask & ~larger_is_first
    soft &= ~hard
    front = ctx.sampler.blended(world.front) & hard
    lines = np.where(hard[..., np.newaxis], mix_colors(grid.bg, (255, 255, 255), float(cfg["lighten"])), grid.bg)
    lines = np.where(soft[..., np.newaxis], mix_colors(grid.bg, (255, 255, 255), float(cfg["vassal_lighten"])), lines)
    war = mix_colors(grid.bg, np.asarray(cfg["front_color"], dtype=np.uint8), float(cfg["front_mix"]))
    grid.put(hard | soft, bg=np.where(front[..., np.newaxis], war, lines))
