"""Boats: a planked hull on the water with a deckhouse near the stern and cargo lashed to the deck."""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .building import Spec, build_building
from .furnish import free_floor, scatter, weighted_choice
from .layout import SiteContext, layout

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_HULL = int(Cell.HULL)
_MIN_DECK = 12  # a deck with fewer cells than this is no boat
_MIN_CABIN_ROWS = 4  # a deckhouse needs at least this many rows (walls included)


def _hull(rows: int, cols: int) -> np.ndarray:
    """Return the deck: a lens pointed at bow and stern, with a free ring for the planking."""
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    rx, ry = max(0.5, (cols - 2) / 2.0), max(0.5, (rows - 2) / 2.0)
    ys, xs = np.ogrid[0:rows, 0:cols]
    nx, ny = (xs - cx) / rx, (ys - cy) / ry
    hull = ny**2 <= np.clip(1.0 - np.abs(nx), 0.0, 1.0)
    hull[0, :] = hull[-1, :] = hull[:, 0] = hull[:, -1] = False
    return hull


def _deckhouse(grid: np.ndarray, ctx: SiteContext, share: float) -> None:
    """Build a small thin-walled cabin in the stern half, wholly on deck, with a door onto the open deck."""
    ys, xs = np.nonzero(grid == _FLOOR)
    if len(xs) < _MIN_DECK:
        return
    min_x, max_x = int(xs.min()), int(xs.max())
    cols = max(8, round((max_x - min_x) * share))
    x0 = min_x + (max_x - min_x) // 4
    x1 = min(x0 + cols, max_x)
    deck = grid[:, x0:x1] == _FLOOR
    height = int(deck.sum(axis=0).min())  # the shortest stretch of deck under the cabin
    rows = height - 2  # leave a walkway round it
    if rows < _MIN_CABIN_ROWS or x1 - x0 < _MIN_CABIN_ROWS:
        return
    ys_here = np.nonzero(deck.any(axis=1))[0]
    y0 = (int(ys_here.min()) + int(ys_here.max())) // 2 - rows // 2 + 1
    cols = x1 - x0
    window = grid[y0 : y0 + rows, x0:x1]
    if window.shape != (rows, cols) or not (window == _FLOOR).all():
        return
    spec = Spec(1, ctx.aspect, ("cabin",), {"cabin": ctx.weights("cabin")}, 0.12, ("rect",), False)
    building = build_building(rows, cols, rng.derive(ctx.seed, "site.layout", "cabin"), spec, (cols + 4, rows // 2))
    if building is not None:
        inside = building.cells != _VOID
        window[inside] = building.cells[inside]


@layout("boat")
def build_boat(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A boat floor: hull, deckhouse and cargo, kept to the water."""
    deck = _hull(ctx.rows, ctx.cols) & ctx.patch.water
    if int(deck.sum()) < _MIN_DECK:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    grid[deck] = _FLOOR
    grid[ndimage.binary_dilation(deck, structure=np.ones((3, 3), bool)) & ~deck] = _HULL
    _deckhouse(grid, ctx, float(ctx.config.get("sites.boat.cabin_share")))
    density = min(0.9, float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.boat_density")))
    table = ctx.weights("deck")
    stream = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(grid, stream, free_floor(grid), density, lambda r, _x, _y: weighted_choice(r, table))
    return grid, grid.copy()
