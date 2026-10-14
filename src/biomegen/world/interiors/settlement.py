"""Settlement interior builder - a cluster of small buildings with open streets between them.

Civilized POIs (``city`` / ``town`` / ``village``) are NOT one solid mass like a dungeon or tower:
they read as a little settlement, so the footprint holds **several separate buildings** with walkable
streets and open ground between them (the surrounding terrain shows through the gaps, exactly as it
shows around a dungeon's organic outline). The three kinds share one builder and differ only in scale -
a village's smaller footprint admits a few huts, a city's larger one many buildings around a plaza.

Recipe: partition the footprint into plots (the shared BSP partitioner), drop one capped building rect
in each, wall each building individually (:func:`~biomegen.world.interiors.grid.wall_ring`) and punch a
DOOR facing the centre, clear a central PATH plaza, then lay PATH streets from every door to the plaza
(and along a chain through the doors) - carved only over open ground so they never tunnel through a
building. Finally each building's interior is dressed with domestic furniture. Single floor, so there
are no stairs; everything is a pure function of ``interior_seed``.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np

from ...util import rng
from ..tile import Cell
from .grid import (
    PARTITIONS,
    InteriorCtx,
    Rect,
    adjacent_mask,
    bridge_disconnected_regions,
    building_door,
    carve_path_guarded,
    carve_room,
    ctx_buildable,
    free_floor_cells,
    place_settlement_bridges,
    rect_in_mask,
    register_interior,
    room_center,
    scatter_furniture,
    wall_ring,
    weighted_choice,
)

# Weighted furniture for a home/hall: beds, a table and chairs, a hearth, shelves, and some storage.
_HOME_FURNITURE: List[Tuple[Cell, float]] = [
    (Cell.BED, 16.0),
    (Cell.TABLE, 15.0),
    (Cell.CHAIR, 14.0),
    (Cell.HEARTH, 12.0),
    (Cell.SHELF, 11.0),
    (Cell.CHEST, 9.0),
    (Cell.BARREL, 8.0),
    (Cell.CRATE, 7.0),
]
_HOME_DENSITY_FACTOR = 1.6  # homes are cosier than dungeons - dress a bit more of the floor
_MAX_BUILDING = 8  # cap a building's side so no single plot becomes a giant hall (keeps them house-scale)
_PLAZA_RADIUS = {"city": 3, "town": 2, "village": 1}  # central PATH square, scaled by settlement size


@register_interior("city")
@register_interior("town")
@register_interior("village")
def build_settlement(ctx: InteriorCtx) -> np.ndarray:
    """Build a settlement as a ``(grid_h, grid_w)`` uint8 array: buildings + streets + plaza."""
    gw, gh = ctx.grid_w, ctx.grid_h
    rgen = rng.derive(ctx.interior_seed, "interior", ctx.floor)
    grid = np.full((gh, gw), int(Cell.VOID), dtype=np.uint8)

    # One capped building per BSP plot; the partitioner already leaves margins between plots, which
    # become the streets. Drop any plot too small to be a building.
    buildings = [_cap(b) for b in PARTITIONS.get(ctx.partition)(rgen, gw, gh, ctx.room_min, ctx.room_max)]
    buildings = [b for b in buildings if b[2] >= 2 and b[3] >= 2]
    # On the coast keep only buildings that sit wholly on dry land, so the settlement clusters on the
    # shore rather than out over the water (the streets/plaza are clamped to land below).
    buildable = ctx_buildable(ctx)
    if buildable is not None:
        buildings = [b for b in buildings if rect_in_mask(b, buildable)]
    for b in buildings:
        carve_room(grid, b, int(Cell.FLOOR))
    for b in buildings:
        wall_ring(grid, b)

    center = (gw // 2, gh // 2)
    _plaza(grid, center, _PLAZA_RADIUS.get(ctx.kind, 1))
    fronts = [d for d in (building_door(grid, b, center) for b in buildings) if d is not None]
    # Streets: a chain through the door-fronts plus a spur from each to the plaza, over open ground only.
    for front, nxt in zip(fronts, fronts[1:], strict=False):
        carve_path_guarded(grid, front, nxt)
    for front in fronts:
        carve_path_guarded(grid, front, center)

    _road_entrance(ctx, grid, buildings, center)

    if buildable is not None and ctx.settlement_bridges:
        # Force crossings between any disconnected land areas before detecting which road
        # segments cross water: carve_path_guarded may not have spanned the full gap.
        bridge_disconnected_regions(grid, buildable, center, ctx.bridge_max_span)

    _furnish_settlement(ctx, grid)
    if buildable is not None:
        if ctx.settlement_bridges:
            place_settlement_bridges(grid, buildable, ctx.bridge_max_span)
        keep = (grid == int(Cell.BRIDGE)) | (grid == int(Cell.BRIDGE_WALL))
        grid[~buildable & ~keep] = int(Cell.VOID)  # clear strayed cells; preserve bridge spans
    return grid


def _road_entrance(ctx: InteriorCtx, grid: np.ndarray, buildings: List[Rect], center: Tuple[int, int]) -> None:
    """Open a road-facing gate into the settlement: a DOOR on the edge-most building + a main street.

    When a road reaches this settlement (``ctx.entrance_side`` is set), the building nearest the
    road-facing edge gets a door punched on that side and a PATH street carved from it out to the
    footprint edge (where the road arrives) and in to the central plaza - so the road snaps to the
    settlement and leads, via a door, into the interior. With no road the settlement is unchanged.
    """
    sx, sy = ctx.entrance_side
    if (sx, sy) == (0, 0) or not buildings:
        return
    gw, gh = ctx.grid_w, ctx.grid_h
    # Midpoint of the footprint edge the road arrives from.
    ex = 0 if sx < 0 else (gw - 1 if sx > 0 else gw // 2)
    ey = 0 if sy < 0 else (gh - 1 if sy > 0 else gh // 2)
    edge = (ex, ey)
    nearest = min(buildings, key=lambda b: (room_center(b)[0] - ex) ** 2 + (room_center(b)[1] - ey) ** 2)
    front = building_door(grid, nearest, edge)  # door on the wall facing the road
    if front is None:
        return
    carve_path_guarded(grid, front, edge)  # street out to where the road meets the settlement
    carve_path_guarded(grid, front, center)  # and in to the plaza (the interior)


def _cap(rect: Rect) -> Rect:
    """Shrink ``rect`` (centred) so neither side exceeds :data:`_MAX_BUILDING`."""
    rx, ry, rw, rh = rect
    if rw > _MAX_BUILDING:
        rx, rw = rx + (rw - _MAX_BUILDING) // 2, _MAX_BUILDING
    if rh > _MAX_BUILDING:
        ry, rh = ry + (rh - _MAX_BUILDING) // 2, _MAX_BUILDING
    return rx, ry, rw, rh


def _plaza(grid: np.ndarray, center: Tuple[int, int], radius: int) -> None:
    """Clear a central PATH square of the given ``radius``, over open ground only (never buildings)."""
    if radius <= 0:
        return
    cx, cy = center
    h, w = grid.shape
    for y in range(max(0, cy - radius), min(h, cy + radius + 1)):
        for x in range(max(0, cx - radius), min(w, cx + radius + 1)):
            if grid[y, x] == int(Cell.VOID):
                grid[y, x] = int(Cell.PATH)


def _furnish_settlement(ctx: InteriorCtx, grid: np.ndarray) -> None:
    """Dress building interiors (FLOOR cells) with domestic furniture, keeping doorways clear."""
    if ctx.clutter_density <= 0:
        return
    apron = adjacent_mask(grid == int(Cell.DOOR))  # leave the cells just inside each door open
    free: List[Tuple[int, int]] = [(x, y) for x, y in free_floor_cells(grid) if not apron[y, x]]
    fr = rng.derive(ctx.interior_seed, "interior.furnish", ctx.floor)
    density = min(0.9, ctx.clutter_density * _HOME_DENSITY_FACTOR)
    scatter_furniture(grid, fr, free, density, lambda r, _x, _y: weighted_choice(r, _HOME_FURNITURE))
