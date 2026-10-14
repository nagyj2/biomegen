"""Camp interior builder - an open-air campsite, no walls at all.

A camp is the one land structure that is *not* a building: there is no masonry, just a cleared,
trampled patch of ground (FLOOR) with a CAMPFIRE at its heart, a ring of TENTs around it, a supply
WAGON parked at the edge, and a few loose barrels/crates. The cleared patch is deliberately drawn as
FLOOR so the camp still reads at the ``zoom`` scale - where tents/campfire (furniture) are suppressed,
the bare clearing is what shows. The surrounding VOID lets the terrain (grass/forest) show right up to
the campsite, so it sits in the landscape rather than in a box.

Single floor, so floor cycling reports "single floor"; everything is a pure function of ``interior_seed``.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .grid import (
    InteriorCtx,
    ctx_buildable,
    free_floor_cells,
    register_interior,
    scatter_furniture,
    weighted_choice,
)

_CLEARING_FACTOR = 0.42  # clearing radius as a fraction of the smaller grid dimension
_MIN_TENTS = 3
_TENT_PER_AREA = 90  # one extra tent per ~this many clearing cells (so bigger camps get more tents)
_TENT_SIZES: List[Tuple[int, int]] = [(2, 2), (3, 2), (2, 3)]
_SUPPLIES: List[Tuple[Cell, float]] = [(Cell.BARREL, 5.0), (Cell.CRATE, 4.0), (Cell.ROCK, 2.0)]


@register_interior("camp")
def build_camp(ctx: InteriorCtx) -> np.ndarray:
    """Build a camp as a ``(grid_h, grid_w)`` uint8 array: a cleared patch, a fire, tents, a wagon."""
    gw, gh = ctx.grid_w, ctx.grid_h
    rgen = rng.derive(ctx.interior_seed, "interior", ctx.floor)
    grid = np.full((gh, gw), int(Cell.VOID), dtype=np.uint8)
    cx, cy = gw // 2, gh // 2
    radius = max(2.0, _CLEARING_FACTOR * min(gw, gh))

    # Trampled clearing (FLOOR) - the camp's footprint at the zoom scale - with the fire at its centre.
    ys, xs = np.ogrid[0:gh, 0:gw]
    clearing = (xs - cx) ** 2 + (ys - cy) ** 2 <= radius * radius
    # On the coast the camp pitches on the dry shore: keep the clearing off the water (and its margin).
    buildable = ctx_buildable(ctx)
    if buildable is not None:
        clearing &= buildable
    grid[clearing] = int(Cell.FLOOR)
    grid[cy, cx] = int(Cell.CAMPFIRE)  # the anchor tile is always dry land, so the fire sits on land

    n_tents = _MIN_TENTS + int(clearing.sum()) // _TENT_PER_AREA
    _place_tents(grid, rgen, cx, cy, radius, n_tents)
    _place_wagon(grid, rgen, cx, cy, radius)
    _scatter_supplies(ctx, grid)
    if buildable is not None:
        grid[~buildable] = int(Cell.VOID)  # clear any tent/wagon that landed on water
        grid[cy, cx] = int(Cell.CAMPFIRE)  # ...but keep the campfire (centre is land)
    return grid


def _place_tents(grid: np.ndarray, rgen, cx: int, cy: int, radius: float, n: int) -> None:
    """Stamp ``n`` small TENT blocks evenly spaced around the campfire (with a little angular jitter)."""
    h, w = grid.shape
    for i in range(n):
        ang = (i / max(1, n)) * 2.0 * math.pi + rgen.uniform(-0.3, 0.3)
        dist = radius * rgen.uniform(0.55, 0.8)
        tx = int(round(cx + dist * math.cos(ang)))
        ty = int(round(cy + dist * math.sin(ang)))
        tw, th = rgen.choice(_TENT_SIZES)
        for yy in range(ty - th // 2, ty - th // 2 + th):
            for xx in range(tx - tw // 2, tx - tw // 2 + tw):
                if 0 <= xx < w and 0 <= yy < h:
                    grid[yy, xx] = int(Cell.TENT)


def _place_wagon(grid: np.ndarray, rgen, cx: int, cy: int, radius: float) -> None:
    """Park a single supply WAGON at the clearing edge, at a random bearing from the fire."""
    h, w = grid.shape
    ang = rgen.uniform(0.0, 2.0 * math.pi)
    wx = int(round(cx + radius * 0.85 * math.cos(ang)))
    wy = int(round(cy + radius * 0.85 * math.sin(ang)))
    if 0 <= wx < w and 0 <= wy < h:
        grid[wy, wx] = int(Cell.WAGON)


def _scatter_supplies(ctx: InteriorCtx, grid: np.ndarray) -> None:
    """Scatter a few loose barrels/crates/rocks over the remaining cleared ground."""
    free = free_floor_cells(grid)
    if not free:
        return
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    density = max(0.04, ctx.clutter_density * 0.6)
    scatter_furniture(grid, fr, free, density, lambda r, _x, _y: weighted_choice(r, _SUPPLIES))
