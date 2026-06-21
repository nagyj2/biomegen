"""Boat interior builder - a planked hull floating on the water, no organic terrain outline.

The one structure placed *on water* rather than on land. It is built as a tapered **hull**: a pointed
lens of deck (FLOOR) ringed by planking (WALL via the shared :func:`~biomegen.world.interiors.grid.
add_walls`), with a small stern **cabin** (a walled deckhouse with a door) and a deck strewn with CARGO,
barrels and crates. Everything outside the hull is left VOID, so the surrounding water tile shows
through and the boat reads as floating on the sea/lake rather than sitting in a box.

Single floor; a pure function of ``interior_seed``, so the boat regenerates identically each open.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ...util import rng
from ..tile import Cell
from .grid import (
    InteriorCtx,
    add_walls,
    free_floor_cells,
    register_interior,
    scatter_furniture,
    weighted_choice,
)

# A boat is mostly cargo: shipped goods, with some barrels and crates lashed to the deck.
_CARGO_FURNITURE: List[Tuple[Cell, float]] = [
    (Cell.CARGO, 10.0),
    (Cell.BARREL, 6.0),
    (Cell.CRATE, 5.0),
]
_CARGO_DENSITY_FACTOR = 1.4


@register_interior("boat")
def build_boat(ctx: InteriorCtx) -> np.ndarray:
    """Build a boat as a ``(grid_h, grid_w)`` uint8 array: a planked hull, a cabin, a laden deck."""
    gw, gh = ctx.grid_w, ctx.grid_h
    grid = np.full((gh, gw), int(Cell.VOID), dtype=np.uint8)
    deck = _hull(gw, gh)
    grid[deck] = int(Cell.FLOOR)
    add_walls(grid)  # ring the deck with planking - the hull
    _add_cabin(grid)
    _furnish_boat(ctx, grid)
    return grid


def _hull(gw: int, gh: int) -> np.ndarray:
    """Return a boolean deck mask: a lens pointed at bow and stern (longer along the wider grid axis).

    Using ``ny^2 <= 1 - |nx|`` (rather than the ellipse's ``1 - nx^2``) tapers the beam linearly to a
    sharp point at each end of the long axis, giving a canoe/longship silhouette instead of an oval.
    """
    cx, cy = (gw - 1) / 2.0, (gh - 1) / 2.0
    rx, ry = max(0.5, (gw - 2) / 2.0), max(0.5, (gh - 2) / 2.0)
    ys, xs = np.ogrid[0:gh, 0:gw]
    nx = (xs - cx) / rx  # -1 stern .. +1 bow (boats are wider than tall, so the length runs along x)
    ny = (ys - cy) / ry
    hull = ny**2 <= np.clip(1.0 - np.abs(nx), 0.0, 1.0)
    hull[0, :] = hull[-1, :] = hull[:, 0] = hull[:, -1] = False  # keep an exterior ring for the planking
    return hull


def _add_cabin(grid: np.ndarray) -> None:
    """Build a small walled deckhouse near the stern with a door opening onto the deck (bow-facing).

    Only cells that already sit on the deck are used, so the cabin never overhangs the water. No-op on a
    deck too small to carry one.
    """
    floor = int(Cell.FLOOR)
    ys, xs = np.nonzero(grid == floor)
    if len(xs) < 12:
        return
    minx, maxx = int(xs.min()), int(xs.max())
    miny, maxy = int(ys.min()), int(ys.max())
    cw = max(2, (maxx - minx) // 4)
    ch = max(2, (maxy - miny) // 2)
    x0, y0 = minx + 1, (miny + maxy) // 2 - ch // 2
    for yy in range(y0, y0 + ch):
        for xx in range(x0, x0 + cw):
            if grid[yy, xx] != floor:
                continue  # build the cabin only where there is deck beneath it
            border = xx in (x0, x0 + cw - 1) or yy in (y0, y0 + ch - 1)
            grid[yy, xx] = int(Cell.WALL) if border else floor
    # Punch one DOOR on the bow-facing wall where open deck lies just beyond it.
    bx = x0 + cw - 1
    for yy in range(y0 + 1, y0 + ch - 1):
        if bx + 1 < grid.shape[1] and grid[yy, bx] == int(Cell.WALL) and grid[yy, bx + 1] == floor:
            grid[yy, bx] = int(Cell.DOOR)
            break


def _furnish_boat(ctx: InteriorCtx, grid: np.ndarray) -> None:
    """Lash cargo, barrels and crates across the open deck."""
    if ctx.clutter_density <= 0:
        return
    free = free_floor_cells(grid)
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    density = min(0.9, ctx.clutter_density * _CARGO_DENSITY_FACTOR)
    scatter_furniture(grid, fr, free, density, lambda r, _x, _y: weighted_choice(r, _CARGO_FURNITURE))
