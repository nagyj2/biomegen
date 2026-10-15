"""Battlefields: a wide trampled field with a standard at each end, wreckage thickest at the centre, wrecked wagons and
a burial ground in one corner. Nothing is built, so it never reads as a camp."""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .furnish import free_floor, weighted_choice
from .layout import SiteContext, layout
from .streets import lay_roads

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)


def _graves(
    grid: np.ndarray, stream, count: int, centre: tuple[int, int], radii: tuple[float, float], aspect: float
) -> None:
    """Lay ``count`` burial mounds in rows (every other row and ``2 * aspect`` columns) in one corner of the field."""
    cx, cy = centre
    rx, ry = radii
    side_x, side_y = stream.choice((-1, 1)), stream.choice((-1, 1))
    step_x, step_y = max(2, round(2 * aspect)), 2
    per_row = max(2, round(count**0.5 * 1.6))
    left = round(cx + side_x * 0.45 * rx - (per_row * step_x) // 2)
    top = round(cy + side_y * 0.5 * ry - (count // per_row) * step_y // 2)
    placed = 0
    for row in range(count):
        if placed >= count:
            break
        x, y = left + (row % per_row) * step_x, top + (row // per_row) * step_y
        if 0 <= y < grid.shape[0] and 0 <= x < grid.shape[1] and grid[y, x] == _FLOOR:
            grid[y, x] = int(Cell.GRAVE)
            placed += 1


@layout("battlefield")
def build_battlefield(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A battlefield floor: an ellipse of trampled ground, a standard at each end, wreckage, wagons and graves."""
    rows, cols, aspect = ctx.rows, ctx.cols, ctx.aspect
    centre = nearest_true(ctx.patch.dry, (cols // 2, rows // 2), aspect)
    if centre is None:
        return None
    cx, cy = centre
    settings = ctx.config.get("sites.battlefield")
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    radius_y = max(2.0, float(settings["clearing"]) * rows)
    radius_x = min(radius_y * aspect * 1.7, float(settings["clearing"]) * cols * 1.1)
    ys, xs = np.ogrid[0:rows, 0:cols]
    norm = ((xs - cx) / max(1.0, radius_x)) ** 2 + ((ys - cy) / max(1.0, radius_y)) ** 2
    field = (norm <= 1.0) & ctx.patch.dry
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    grid[field] = _FLOOR

    # Wreckage: denser the nearer the middle, where the lines met.
    table = ctx.weights("debris")
    furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    chance = float(settings["debris_density"]) * (
        1.0 + float(settings["centre_boost"]) * (1.0 - np.clip(norm, 0.0, 1.0))
    )
    roll = rng.derive_numpy(ctx.seed, "site.furnish", ctx.floor, "debris").random(grid.shape)
    for y, x in np.argwhere((grid == _FLOOR) & (roll < chance)).tolist():
        grid[y, x] = int(weighted_choice(furnish, table))

    _graves(grid, stream, stream.randint(*(int(v) for v in settings["graves"])), (cx, cy), (radius_x, radius_y), aspect)
    for index in range(int(settings["banners"])):  # the standards, at either end of the long axis
        bx, by = round(cx + (-1 if index % 2 == 0 else 1) * 0.74 * radius_x), cy
        if 0 <= bx < cols and 0 <= by < rows and grid[by, bx] != _VOID:
            grid[by, bx] = int(Cell.BANNER)
    lo, hi = (int(v) for v in settings["wagons"])
    for _ in range(stream.randint(lo, hi)):
        spots = free_floor(grid)
        if spots:
            wx, wy = stream.choice(spots)
            grid[wy, wx] = int(Cell.WAGON)
    lay_roads(grid, ctx.patch, (_VOID, _FLOOR))
    return grid, grid.copy()
