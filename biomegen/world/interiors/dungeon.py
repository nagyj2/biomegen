"""Dungeon interior builder - BSP rooms + corridors inside an organic boundary, over stacking floors.

Algorithm: first pick the dungeon's **outer shape** - a per-dungeon, floor-independent boundary mask
from the swappable :data:`grid.SHAPES` registry (blob / cave / diamond / ... ; ``"mixed"`` picks one
per dungeon so none is square; see :mod:`shapes`). Then partition the area into rooms (default **BSP**;
see :mod:`grid`), keeping those that fit inside the shape, connect their centres with L-shaped
corridors into one traversable chain, and add a few **extra** room-to-room links so the warren has
loops and side-passages rather than a single spine. Fill the shape (plus the carved passages) solid
with rock so the footprint is *only* walls and floors, and leave everything outside it VOID so the
surrounding terrain shows around the organic outline.

Two **aligned stair shafts** - scattered but fixed across floors so they stack vertically - carry the
stairs. The entry (top) floor gets a real exterior DOOR punched through the outer wall plus stairs
down; intermediate floors show stairs up and down; the deepest floor shows only stairs up. A final
role-based furnishing pass scatters varied furniture across rooms - and the deeper the floor, the more
loot (chests) it holds - while keeping corridors and doorways clear of everything but loose rubble.

Dungeons descend, so floors run from ``lowest_floor`` (negative, deepest) up to ``0`` (the ground/
entry level == ``ctx.top_floor``). Everything is a pure function of ``interior_seed`` and ``floor``,
so a dungeon regenerates identically every time it is opened.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ...util import rng
from ..tile import Cell
from .grid import (
    InteriorCtx,
    Rect,
    build_room_structure,
    clear_blocking_furniture,
    punch_entrance,
    register_interior,
    resolve_shape,
    stair_links,
)

# --- furnishing tuning (kept here, in code, as these are the knobs we iterate on by hand) ---------
# Weighted furniture table for ROOM interiors (corridors/doorways get rubble only). Weights are
# relative; chest weight is added separately because it scales with depth (see _pick_room_furniture).
_ROOM_FURNITURE: List[Tuple[Cell, float]] = [
    (Cell.RUBBLE, 20.0),
    (Cell.BARREL, 14.0),
    (Cell.CRATE, 12.0),
    (Cell.TABLE, 12.0),
    (Cell.CHAIR, 11.0),
    (Cell.SHELF, 9.0),
    (Cell.BED, 7.0),
    (Cell.HEARTH, 5.0),
]
_CHEST_BASE = 4.0  # chest weight on the entry floor (depth 0)
_CHEST_DEPTH_GAIN = 36.0  # extra chest weight at the deepest floor (depth 1) - "more loot at the bottom"
_DEPTH_DENSITY_GAIN = 0.6  # clutter density is multiplied by (1 + this * depth): deeper => more stuff
_CORRIDOR_RUBBLE_CHANCE = 0.45  # corridors/doorways: only rubble, and only sometimes (stay passable)
_EXTRA_CORRIDOR_RATIO = 0.34  # extra room-to-room links beyond the spanning chain (loops + passages)


@register_interior("dungeon")
def build_dungeon(ctx: InteriorCtx) -> np.ndarray:
    """Build one dungeon floor as a ``(grid_h, grid_w)`` uint8 array of :class:`Cell` values."""
    gw, gh = ctx.grid_w, ctx.grid_h
    layout = rng.derive(ctx.interior_seed, "interior", ctx.floor)

    # Organic OUTER SHAPE (per-dungeon, floor-independent so all floors share one outline), then this
    # floor's stair cells from the per-pair link list (up = link to the floor above, down = to below;
    # adjacent floors share a cell so stairs line up, different pairs use different cells).
    mask = resolve_shape(ctx, gw, gh)
    links = stair_links(ctx.interior_seed, gw, gh, ctx.floor_count)
    i = ctx.floor - ctx.lowest_floor  # 0 at the deepest floor
    up = links[i] if ctx.floor < ctx.top_floor else None  # this floor's UP-stairs cell (link to f+1)
    down = links[i - 1] if ctx.floor > ctx.lowest_floor else None  # DOWN-stairs cell (link to f-1)

    # Shared recipe: rooms + corridors inside the shape, stair cells force-carved reachable, then
    # sealed into a solid building (rock inside the outline, terrain outside).
    access = tuple(c for c in (up, down) if c is not None)
    grid, rooms = build_room_structure(ctx, mask, layout, access, _EXTRA_CORRIDOR_RATIO)

    # Stamp the stairs and (entry floor only) punch the entrance LAST: a door on the now-final outer
    # wall, tunnelled in to the nearest room (after the wall passes, so the door keeps its exterior
    # side open while the tunnel reaches a room).
    reserved = set()
    if up is not None:
        grid[up[1], up[0]] = int(Cell.STAIRS_UP)
        reserved.add(up)
    if down is not None:
        grid[down[1], down[0]] = int(Cell.STAIRS_DOWN)
        reserved.add(down)
    if ctx.floor == ctx.top_floor:
        door = punch_entrance(grid, rooms, rng.derive(ctx.interior_seed, "interior.door"))
        if door is not None:
            reserved.add(door)

    _furnish(ctx, grid, rooms, reserved)
    # Guarantee the stairs and entrance stay mutually reachable - furniture must never trap them.
    clear_blocking_furniture(grid, sorted(reserved))
    return grid


def _adjacent_mask(mask: np.ndarray) -> np.ndarray:
    """Return the 4-neighbourhood of ``mask`` (cells orthogonally adjacent to a True cell)."""
    out = np.zeros_like(mask)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _pick_room_furniture(fr, depth: float) -> Cell:
    """Pick one furniture cell from the weighted room table; chest weight grows with ``depth`` (0..1)."""
    weights = [*_ROOM_FURNITURE, (Cell.CHEST, _CHEST_BASE + _CHEST_DEPTH_GAIN * depth)]
    total = sum(w for _c, w in weights)
    r = fr.random() * total
    acc = 0.0
    for cell, w in weights:
        acc += w
        if r < acc:
            return cell
    return Cell.RUBBLE


def _furnish(ctx: InteriorCtx, grid: np.ndarray, rooms: List[Rect], reserved: set) -> None:
    """Scatter furniture on free FLOOR cells.

    Rooms get the full weighted variety (with more chests the deeper the floor); corridors and the
    cells immediately around doors/stairs are kept clear of everything but the occasional loose rubble
    so the dungeon stays traversable. Furniture is part of the deterministic grid but only *rendered*
    at the local scale (the zoom scale suppresses it; see :data:`grid.STRUCTURAL`).
    """
    if ctx.clutter_density <= 0:
        return
    # Classify floor cells: a cell is "protected" (corridor or doorway apron) if it lies outside every
    # room rectangle, or sits next to a door/stairway. Protected cells take rubble only.
    room_mask = np.zeros(grid.shape, dtype=bool)
    for rx, ry, rw, rh in rooms:
        room_mask[ry : ry + rh, rx : rx + rw] = True
    floor = grid == int(Cell.FLOOR)
    special = (grid == int(Cell.DOOR)) | (grid == int(Cell.STAIRS_UP)) | (grid == int(Cell.STAIRS_DOWN))
    protected = floor & (~room_mask | _adjacent_mask(special))

    # Deeper floors are both denser and far more chest-heavy (loot at the bottom). depth: 0 at the
    # entry floor, 1 at the deepest.
    depth = 0.0 if ctx.floor_count <= 1 else (ctx.top_floor - ctx.floor) / (ctx.floor_count - 1)
    density = ctx.clutter_density * (1.0 + _DEPTH_DENSITY_GAIN * depth)

    ys, xs = np.nonzero(floor)
    free = [(int(x), int(y)) for x, y in zip(xs, ys, strict=True) if (int(x), int(y)) not in reserved]
    free.sort()  # stable order so the seeded sample is reproducible
    n = int(len(free) * density)
    if n <= 0:
        return
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    for x, y in fr.sample(free, min(n, len(free))):
        if protected[y, x]:  # corridor / doorway: rubble only, and only sometimes (keep it passable)
            if fr.random() < _CORRIDOR_RUBBLE_CHANCE:
                grid[y, x] = int(Cell.RUBBLE)
            continue
        grid[y, x] = int(_pick_room_furniture(fr, depth))
