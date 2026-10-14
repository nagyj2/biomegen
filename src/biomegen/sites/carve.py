"""Carving primitives on a plan grid: rooms, corridors, walls and connectivity.

A grid is a ``uint8`` array ``[row, col]`` of :class:`~biomegen.world.tile.Cell` values. A rectangle is
``(x, y, w, h)`` in cells. Plan cells are terminal cells, taller than wide, so a corridor running up and down is carved
wider than one running across (``vertical_width``) to look the same thickness on screen.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import ndimage

from ..world.tile import Cell

Rect = tuple[int, int, int, int]
Point = tuple[int, int]

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)


def room_center(room: Rect) -> Point:
    """Return the centre cell ``(x, y)`` of ``room``."""
    x, y, w, h = room
    return x + w // 2, y + h // 2


def carve_room(grid: np.ndarray, room: Rect, cell: int = _FLOOR) -> None:
    """Fill ``room`` with ``cell``."""
    x, y, w, h = room
    grid[y : y + h, x : x + w] = cell


def carve_corridor(grid: np.ndarray, a: Point, b: Point, vertical_width: int = 2, cell: int = _FLOOR) -> None:
    """Carve an L-shaped corridor from ``a`` to ``b``: along ``a``'s row, then up or down ``b``'s columns."""
    (ax, ay), (bx, by) = a, b
    rows, cols = grid.shape
    grid[ay, min(ax, bx) : max(ax, bx) + 1] = cell
    left = max(0, bx - (vertical_width - 1) // 2)
    right = min(cols, bx + vertical_width // 2 + 1)
    grid[min(ay, by) : max(ay, by) + 1, left:right] = cell


def add_walls(grid: np.ndarray) -> None:
    """Turn every void cell touching a non-void cell (eight-neighbourhood) into a wall, in place."""
    occupied = grid != _VOID
    grown = ndimage.binary_dilation(occupied, structure=np.ones((3, 3), bool), border_value=0)
    grid[grown & ~occupied] = _WALL


def wall_ring(grid: np.ndarray, rect: Rect) -> None:
    """Wall the one-cell border around ``rect``, only where it is void, so neighbouring buildings and paths survive."""
    x, y, w, h = rect
    rows, cols = grid.shape
    ring = np.zeros(grid.shape, dtype=bool)
    ring[max(y - 1, 0) : min(y + h + 1, rows), max(x - 1, 0) : min(x + w + 1, cols)] = True
    ring[max(y, 0) : min(y + h, rows), max(x, 0) : min(x + w, cols)] = False
    grid[ring & (grid == _VOID)] = _WALL


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Return only the largest four-connected True component of ``mask``."""
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros_like(mask)
    return labels == int(np.bincount(labels.ravel())[1:].argmax()) + 1


def border_void(grid: np.ndarray) -> np.ndarray:
    """Return the void cells reachable from the grid edge: the open ground around a structure."""
    void = grid == _VOID
    seed = np.zeros_like(void)
    seed[0, :] = seed[-1, :] = seed[:, 0] = seed[:, -1] = True
    return ndimage.binary_propagation(seed & void, mask=void)


def fill_enclosed(grid: np.ndarray) -> None:
    """Turn void that is walled off from the outside into wall, so no inaccessible gap shows the terrain."""
    grid[(grid == _VOID) & ~border_void(grid)] = _WALL


def connect_floor_components(grid: np.ndarray, vertical_width: int = 2) -> None:
    """Carve corridors until every floor cell can reach every other, in place."""
    labels, count = ndimage.label(grid == _FLOOR)
    if count <= 1:
        return
    sizes = np.bincount(labels.ravel())[1:]
    order = sorted(range(1, count + 1), key=lambda label: (-int(sizes[label - 1]), label))
    main = np.argwhere(labels == order[0])
    for label in order[1:]:
        cells = np.argwhere(labels == label)
        cy, cx = cells[len(cells) // 2]
        distance = (main[:, 0] - cy) ** 2 + (main[:, 1] - cx) ** 2
        ny, nx = main[int(np.argmin(distance))]
        carve_corridor(grid, (int(cx), int(cy)), (int(nx), int(ny)), vertical_width)
        main = np.vstack([main, cells])


def rect_in_mask(rect: Rect, mask: np.ndarray) -> bool:
    """Return whether the whole rectangle lies inside ``mask``."""
    x, y, w, h = rect
    return bool(mask[y : y + h, x : x + w].all())


def nearest_true(mask: np.ndarray, point: Point, aspect: float = 2.0) -> Optional[Point]:
    """Return the True cell of ``mask`` nearest ``point``, measured on screen (a row is ``aspect`` columns), or None."""
    cells = np.argwhere(mask)
    if len(cells) == 0:
        return None
    px, py = point
    distance = ((cells[:, 1] - px) / aspect) ** 2 + (cells[:, 0] - py) ** 2
    y, x = cells[int(np.argmin(distance))]
    return int(x), int(y)
