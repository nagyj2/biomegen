"""Ruin interior builder - a once-solid building, collapsed and overgrown with rubble.

A ruin starts life as an ordinary single-floor stone building (the same shared recipe a dungeon floor
uses: an organic outer shape filled with rooms + rock, an entrance punched through the wall) and is
then **eroded**: a seeded fraction of its walls crumble to open gaps (so the surrounding terrain shows
straight through the breaches) and a fraction of its floor cracks into rubble. What furniture remains is
rubble-dominated, with the occasional chest still worth looting. The erosion fraction is the config knob
``interiors.ruin_erosion``.

There is only one floor (ruin do not descend), so :func:`~biomegen.interiors.grid.floor_links`
yields no stairs and :func:`~biomegen.interiors.grid.stamp_circulation` simply punches the ground-
floor entrance. Everything is a pure function of ``interior_seed``, so a ruin regenerates identically.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .grid import (
    InteriorCtx,
    build_room_structure,
    floor_links,
    free_floor_cells,
    register_interior,
    resolve_shape,
    scatter_furniture,
    stamp_circulation,
    weighted_choice,
)

# Rubble dominates; a little decayed furniture and the odd surviving chest remain.
_RUIN_FURNITURE: List[Tuple[Cell, float]] = [
    (Cell.RUBBLE, 40.0),
    (Cell.CHEST, 8.0),
    (Cell.BARREL, 7.0),
    (Cell.CRATE, 6.0),
    (Cell.TABLE, 5.0),
    (Cell.SHELF, 4.0),
    (Cell.BED, 3.0),
]
_RUIN_DENSITY_FACTOR = 1.5  # ruin are strewn with debris - dress more of the surviving floor
_FLOOR_CRACK_FACTOR = 0.5  # floor cracks into rubble at half the wall-collapse rate
_EXTRA_CORRIDOR_RATIO = 0.2


@register_interior("ruin")
def build_ruin(ctx: InteriorCtx) -> np.ndarray:
    """Build a ruin as a ``(grid_h, grid_w)`` uint8 array: a building, eroded and rubble-strewn."""
    layout = rng.derive(ctx.interior_seed, "interior", ctx.floor)
    mask = resolve_shape(ctx, ctx.grid_w, ctx.grid_h)
    up, down = floor_links(ctx)  # single floor -> (None, None): no stairs, just the entrance below
    access = tuple(c for c in (up, down) if c is not None)
    grid, rooms = build_room_structure(ctx, mask, layout, access, _EXTRA_CORRIDOR_RATIO)
    reserved = stamp_circulation(ctx, grid, rooms, up, down)
    _erode(ctx, grid)
    _furnish_ruin(ctx, grid, reserved)
    return grid


def _erode(ctx: InteriorCtx, grid: np.ndarray) -> None:
    """Collapse a seeded fraction of walls to open gaps and crack some floor into rubble, in place.

    Only WALL and FLOOR are touched (the DOOR and any later furniture are left intact), so the entrance
    survives. Collapsed walls become VOID - genuine breaches the terrain shows through - giving the ruin
    its broken, open silhouette rather than a sealed building.
    """
    erg = rng.derive_numpy(ctx.interior_seed, "interior.erode")
    roll = erg.random(grid.shape)
    wall = grid == int(Cell.WALL)
    grid[wall & (roll < ctx.ruin_erosion)] = int(Cell.VOID)
    floorm = grid == int(Cell.FLOOR)
    grid[floorm & (roll < ctx.ruin_erosion * _FLOOR_CRACK_FACTOR)] = int(Cell.RUBBLE)


def _furnish_ruin(ctx: InteriorCtx, grid: np.ndarray, reserved: set) -> None:
    """Scatter rubble-heavy debris (and a few surviving valuables) over the remaining floor."""
    if ctx.clutter_density <= 0:
        return
    free = free_floor_cells(grid, reserved)
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    density = min(0.9, ctx.clutter_density * _RUIN_DENSITY_FACTOR)
    scatter_furniture(grid, fr, free, density, lambda r, _x, _y: weighted_choice(r, _RUIN_FURNITURE))
