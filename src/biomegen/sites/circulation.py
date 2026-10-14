"""Getting in and moving between floors: stairs and the entrance."""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .carve import Point, Rect, border_void, carve_corridor, room_center

_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)
_VOID = int(Cell.VOID)
_MIN_STAIR_GAP = 3  # cells between two staircases, so they never touch


def stair_links(seed: int, mask: np.ndarray, floor_count: int) -> list[Point]:
    """Return one cell per adjacent floor pair, drawn from the structure ``mask`` (``floor_count - 1`` of them).

    Link ``i`` joins floor ``lowest + i`` (its up stairs) to floor ``lowest + i + 1`` (its down stairs), so a staircase
    you descend lands on the up stairs of the floor below. The list depends only on the seed and the
    floor-independent mask, so every floor rebuilds the same links and the shafts line up.
    """
    if floor_count <= 1:
        return []
    inner = ndimage.binary_erosion(mask, iterations=2)
    candidates = np.argwhere(inner if inner.any() else mask)
    stream = rng.derive(seed, "site.shaft")
    ordered = [(int(x), int(y)) for y, x in candidates.tolist()]
    links: list[Point] = []
    for _ in range(floor_count - 1):
        far = [p for p in ordered if all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) >= _MIN_STAIR_GAP for q in links)]
        links.append(stream.choice(far or ordered))
    return links


def floor_links(
    links: list[Point], floor: int, lowest_floor: int, floor_count: int
) -> tuple[Optional[Point], Optional[Point]]:
    """Return this floor's ``(up, down)`` stair cells; the top floor has no up stairs, the lowest no down stairs."""
    index = floor - lowest_floor
    up = links[index] if floor < lowest_floor + floor_count - 1 else None
    down = links[index - 1] if floor > lowest_floor else None
    return up, down


def force_floor_access(grid: np.ndarray, cell: Point, rooms: list[Rect], vertical_width: int = 2) -> None:
    """Make ``cell`` reachable floor: carve a small pocket there and a corridor to the nearest room."""
    cx, cy = cell
    rows, cols = grid.shape
    grid[max(1, cy - 1) : min(rows - 1, cy + 2), max(1, cx - 2) : min(cols - 1, cx + 3)] = _FLOOR
    if rooms:
        nearest = min(rooms, key=lambda r: (room_center(r)[0] - cx) ** 2 + (room_center(r)[1] - cy) ** 2)
        carve_corridor(grid, (cx, cy), room_center(nearest), vertical_width)


def punch_entrance(
    grid: np.ndarray,
    rooms: list[Rect],
    rgen: random.Random,
    target: Optional[Point],
    vertical_width: int = 2,
) -> Optional[Point]:
    """Open a door in the outer wall and tunnel inward to the nearest room; return the door cell or None.

    The outer wall is backed by rock, so the door's cell is joined to the nearest room by a corridor. The door goes on
    the boundary wall nearest ``target`` (the road's gate); with no target a seeded boundary wall is chosen.
    """
    rows, cols = grid.shape
    exterior = border_void(grid)
    candidates: list[Point] = []
    for y, x in np.argwhere(grid == _WALL).tolist():
        for step_y, step_x in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + step_y, x + step_x
            if not (0 <= ny < rows and 0 <= nx < cols) or exterior[ny, nx]:
                candidates.append((x, y))
                break
    if not candidates or not rooms:
        return None
    candidates.sort(key=lambda p: (p[1], p[0]))
    if target is not None:
        door = min(candidates, key=lambda p: (((p[0] - target[0]) / 2.0) ** 2 + (p[1] - target[1]) ** 2, p[1], p[0]))
    else:
        door = rgen.choice(candidates)
    nearest = min(rooms, key=lambda r: (room_center(r)[0] - door[0]) ** 2 + (room_center(r)[1] - door[1]) ** 2)
    carve_corridor(grid, door, room_center(nearest), vertical_width)
    grid[door[1], door[0]] = int(Cell.DOOR)
    return door


def stamp_stairs(grid: np.ndarray, up: Optional[Point], down: Optional[Point]) -> set[Point]:
    """Write the stair cells and return them (furnishing keeps them clear)."""
    reserved: set[Point] = set()
    if up is not None:
        grid[up[1], up[0]] = int(Cell.STAIRS_UP)
        reserved.add(up)
    if down is not None:
        grid[down[1], down[0]] = int(Cell.STAIRS_DOWN)
        reserved.add(down)
    return reserved
