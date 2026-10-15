"""Battlefields: a trampled field strewn with the wreckage of a battle, and a few wrecked carts."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .furnish import free_floor, scatter, weighted_choice
from .layout import SiteContext, layout
from .streets import lay_roads

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)


@layout("battlefield")
def build_battlefield(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A battlefield floor: an open ellipse of ground with debris scattered over it and a few wrecked wagons."""
    rows, cols, aspect = ctx.rows, ctx.cols, ctx.aspect
    centre = nearest_true(ctx.patch.dry, (cols // 2, rows // 2), aspect)
    if centre is None:
        return None
    cx, cy = centre
    settings = ctx.config.get("sites.battlefield")
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    radius_y = max(2.0, float(settings["clearing"]) * rows)
    radius_x = min(radius_y * aspect, float(settings["clearing"]) * cols)
    ys, xs = np.ogrid[0:rows, 0:cols]
    field = ((xs - cx) / max(1.0, radius_x)) ** 2 + ((ys - cy) / max(1.0, radius_y)) ** 2 <= 1.0
    field &= ctx.patch.dry
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    grid[field] = _FLOOR
    lo, hi = (int(v) for v in settings["wagons"])
    for _ in range(stream.randint(lo, hi)):
        spots = free_floor(grid)
        if spots:
            wx, wy = stream.choice(spots)
            grid[wy, wx] = int(Cell.WAGON)
    table = ctx.weights("debris")
    furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(
        grid, furnish, free_floor(grid), float(settings["debris_density"]), lambda r, _x, _y: weighted_choice(r, table)
    )
    lay_roads(grid, ctx.patch, (_VOID, _FLOOR))
    return grid, grid.copy()
