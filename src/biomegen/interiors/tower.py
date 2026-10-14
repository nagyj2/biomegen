"""Tower interior builder - a compact stacked keep that *rises* from the ground floor.

A tower is the dungeon's structural twin turned upside down: the same shared recipe (an organic outer
shape filled with rooms + rock, aligned stair shafts that line the floors up vertically, a punched
exterior entrance) but it **ascends** instead of descending. The :func:`biomegen.pipeline.poi_rules.
floors_for` convention puts the ground/entry level at floor ``0`` for both kinds - dungeons run
``0`` down to negative floors, towers run ``0`` up to ``floor_count - 1`` - so the shared
:func:`~biomegen.world.interiors.grid.stamp_circulation` punches the door on floor ``0`` either way and
nothing about the stair model needs to change for "up".

Towers are small (a room or two per floor) and sparsely furnished living/working quarters rather than
loot warrens; the topmost floor is an open **lookout**, kept nearly bare. Everything is a pure
function of ``interior_seed`` and ``floor``, so a tower regenerates identically every time it is opened.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ...util import rng
from ..tile import Cell
from .grid import (
    InteriorCtx,
    build_room_structure,
    clear_blocking_furniture,
    floor_links,
    free_floor_cells,
    register_interior,
    resolve_shape,
    scatter_furniture,
    stamp_circulation,
    weighted_choice,
)

# Weighted furniture for a tower's quarters: a study (shelves/table/chair), a bed, a hearth, and some
# storage. No depth scaling - a tower is lived in top to bottom, not a descent into loot.
_TOWER_FURNITURE: List[Tuple[Cell, float]] = [
    (Cell.SHELF, 16.0),
    (Cell.TABLE, 14.0),
    (Cell.CHAIR, 13.0),
    (Cell.BED, 12.0),
    (Cell.HEARTH, 8.0),
    (Cell.CHEST, 7.0),
    (Cell.BARREL, 6.0),
    (Cell.CRATE, 6.0),
]
_LOOKOUT_FACTOR = 0.5  # the top floor is an open lookout: furnish it at half the usual density
_EXTRA_CORRIDOR_RATIO = 0.15  # towers are compact; a link or two between rooms is plenty


@register_interior("tower")
def build_tower(ctx: InteriorCtx) -> np.ndarray:
    """Build one tower floor as a ``(grid_h, grid_w)`` uint8 array of :class:`Cell` values."""
    layout = rng.derive(ctx.interior_seed, "interior", ctx.floor)
    mask = resolve_shape(ctx, ctx.grid_w, ctx.grid_h)
    up, down = floor_links(ctx)
    access = tuple(c for c in (up, down) if c is not None)
    grid, rooms = build_room_structure(ctx, mask, layout, access, _EXTRA_CORRIDOR_RATIO)
    reserved = stamp_circulation(ctx, grid, rooms, up, down)
    _furnish_tower(ctx, grid, reserved)
    clear_blocking_furniture(grid, sorted(reserved))
    return grid


def _furnish_tower(ctx: InteriorCtx, grid: np.ndarray, reserved: set) -> None:
    """Scatter sparse quarters furniture; the top floor (lookout) is dressed at half density."""
    if ctx.clutter_density <= 0:
        return
    density = ctx.clutter_density * (_LOOKOUT_FACTOR if ctx.floor == ctx.top_floor else 1.0)
    free = free_floor_cells(grid, reserved)
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    scatter_furniture(grid, fr, free, density, lambda r, _x, _y: weighted_choice(r, _TOWER_FURNITURE))
