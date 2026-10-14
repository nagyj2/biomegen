"""Settlements: walled buildings round a plaza, joined by streets that bridge any water in the way.

A settlement is not one solid mass: the extent holds several separate buildings with open ground between them, so the
terrain shows through the gaps. Plots come from the same partition the dungeons use; each building is walled singly and
given a door facing the plaza. Streets run from every door, and from every road gate on the extent's edge, to the plaza,
reusing one another and bridging water up to ``sites.bridge_max_rows``.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .carve import Point, Rect, carve_room, nearest_true, rect_in_mask, wall_ring
from .furnish import free_floor, scatter, weighted_choice
from .layout import SiteContext, layout
from .partition import bsp_rooms
from .streets import lay_street

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)
_PATH = int(Cell.PATH)


def building_door(grid: np.ndarray, rect: Rect, toward: Point) -> Optional[Point]:
    """Punch a door in ``rect``'s wall on the side facing ``toward`` and return the open cell it opens onto.

    The door goes on the wall cell nearest ``toward`` with the building's floor behind it and open ground in front. None
    is returned for a building with no such wall.
    """
    rows, cols = grid.shape
    x0, y0, w, h = rect
    tx, ty = toward
    best: Optional[tuple[float, Point, Point]] = None
    for y in range(max(0, y0 - 1), min(rows, y0 + h + 1)):
        for x in range(max(0, x0 - 1), min(cols, x0 + w + 1)):
            if grid[y, x] != _WALL:
                continue
            for step_x, step_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ix, iy, ox, oy = x - step_x, y - step_y, x + step_x, y + step_y
                if not (0 <= ix < cols and 0 <= iy < rows and 0 <= ox < cols and 0 <= oy < rows):
                    continue
                if grid[iy, ix] == _FLOOR and grid[oy, ox] in (_VOID, _PATH):
                    candidate = (((x - tx) / 2.0) ** 2 + (y - ty) ** 2, (x, y), (ox, oy))
                    if best is None or candidate < best:
                        best = candidate
                    break
    if best is None:
        return None
    _distance, (door_x, door_y), front = best
    grid[door_y, door_x] = int(Cell.DOOR)
    return front


def _demolish(grid: np.ndarray, rect: Rect) -> None:
    """Clear a building and its wall ring (streets stay), for a building no street can reach."""
    x, y, w, h = rect
    rows, cols = grid.shape
    block = grid[max(y - 1, 0) : min(y + h + 1, rows), max(x - 1, 0) : min(x + w + 1, cols)]
    block[np.isin(block, (_FLOOR, _WALL, int(Cell.DOOR)))] = _VOID


def _plaza(ctx: SiteContext, centre: Point) -> np.ndarray:
    """Return the plaza: an ellipse about ``centre`` ``plaza_rows`` tall, widened by the cell aspect."""
    ys, xs = np.ogrid[0 : ctx.rows, 0 : ctx.cols]
    radius = max(1, ctx.plaza_rows)
    return ((xs - centre[0]) / (radius * ctx.aspect)) ** 2 + ((ys - centre[1]) / radius) ** 2 <= 1.0


def _furnish_homes(ctx: SiteContext, grid: np.ndarray) -> None:
    density = float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.home_density"))
    table = [(Cell[name.upper()], weight) for name, weight in ctx.furniture]
    stream = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(grid, stream, free_floor(grid), density, lambda r, _x, _y: weighted_choice(r, table))


@layout("settlement")
def build_settlement(ctx: SiteContext) -> Optional[np.ndarray]:
    """A settlement floor: buildings, plaza, streets and bridges."""
    rows, cols = ctx.rows, ctx.cols
    dry = ctx.patch.dry
    ground = ndimage.binary_erosion(dry, structure=np.ones((3, 3), bool), border_value=1)
    centre = nearest_true(ground, (cols // 2, rows // 2), ctx.aspect)
    if centre is None:
        return None
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    plaza = _plaza(ctx, centre) & dry

    building_rows = ctx.setting("building_rows")
    gap = ctx.setting("street_gap")
    inset = (int(gap[0]) + 1, int(gap[1]) + 1)  # a wall, then the street, on every side of a building
    plots = bsp_rooms(stream, cols, rows, (int(building_rows[0]), int(building_rows[1])), ctx.aspect, 1, inset)
    buildings = [
        b for b in plots if rect_in_mask(b, ground) and not plaza[b[1] : b[1] + b[3], b[0] : b[0] + b[2]].any()
    ]
    for building in buildings:
        carve_room(grid, building)
    for building in buildings:
        wall_ring(grid, building)
    grid[plaza & (grid == _VOID)] = _PATH

    rules = ctx.street_rules
    doors = [(building_door(grid, b, centre), b) for b in buildings]
    reached = [(front, b) for front, b in doors if front is not None]
    for front, building in sorted(
        reached, key=lambda fb: ((fb[0][0] - centre[0]) / ctx.aspect) ** 2 + (fb[0][1] - centre[1]) ** 2
    ):
        if lay_street(grid, dry, front, centre, rules):
            continue
        # Blocked by buildings or too much water: spur off the nearest street, or pull the building down.
        spur = nearest_true((grid == _PATH) | (grid == int(Cell.BRIDGE)), front, ctx.aspect)
        if spur is None or not lay_street(grid, dry, front, spur, rules):
            _demolish(grid, building)
    for gate in ctx.patch.gates:
        lay_street(grid, dry, (gate.col, gate.row), centre, rules)
    _furnish_homes(ctx, grid)
    return grid
