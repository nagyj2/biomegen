"""Boats: a planked hull on the water with a deckhouse near the stern and cargo lashed to the deck."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import add_walls
from .furnish import free_floor, scatter, weighted_choice
from .layout import SiteContext, layout

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)


def _hull(rows: int, cols: int) -> np.ndarray:
    """Return the deck: a lens pointed at bow and stern, with a free ring for the planking."""
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    rx, ry = max(0.5, (cols - 2) / 2.0), max(0.5, (rows - 2) / 2.0)
    ys, xs = np.ogrid[0:rows, 0:cols]
    nx, ny = (xs - cx) / rx, (ys - cy) / ry
    hull = ny**2 <= np.clip(1.0 - np.abs(nx), 0.0, 1.0)
    hull[0, :] = hull[-1, :] = hull[:, 0] = hull[:, -1] = False
    return hull


def _deckhouse(grid: np.ndarray, share: float) -> None:
    """Build a small walled cabin near the stern, only over deck, with a door onto the open deck."""
    ys, xs = np.nonzero(grid == _FLOOR)
    if len(xs) < 12:
        return
    min_x, max_x, min_y, max_y = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    width = max(3, round((max_x - min_x) * share))
    height = max(3, (max_y - min_y) // 2)
    x0, y0 = min_x + 1, (min_y + max_y) // 2 - height // 2
    for y in range(y0, y0 + height):
        for x in range(x0, x0 + width):
            if grid[y, x] != _FLOOR:
                continue
            edge = x in (x0, x0 + width - 1) or y in (y0, y0 + height - 1)
            grid[y, x] = _WALL if edge else _FLOOR
    door_x = x0 + width - 1
    for y in range(y0 + 1, y0 + height - 1):
        if door_x + 1 < grid.shape[1] and grid[y, door_x] == _WALL and grid[y, door_x + 1] == _FLOOR:
            grid[y, door_x] = int(Cell.DOOR)
            return


@layout("boat")
def build_boat(ctx: SiteContext) -> Optional[np.ndarray]:
    """A boat floor: hull, deckhouse and cargo, kept to the water."""
    deck = _hull(ctx.rows, ctx.cols) & ctx.patch.water
    if int(deck.sum()) < 12:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    grid[deck] = _FLOOR
    add_walls(grid)
    _deckhouse(grid, float(ctx.config.get("sites.boat.cabin_share")))
    density = min(0.9, float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.boat_density")))
    table = [(Cell[name.upper()], weight) for name, weight in ctx.furniture]
    stream = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(grid, stream, free_floor(grid), density, lambda r, _x, _y: weighted_choice(r, table))
    return grid
