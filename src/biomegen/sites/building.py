"""Buildings: hollow, thin-walled, with real rooms joined by doors.

A building is a footprint (a rectangle, an L or a T of wings that share a wall), cut into rooms by recursive
subdivision. Rooms meet along **shared one-cell walls**, so the plan reads as lines, not slabs. Doors join adjacent
rooms along a spanning tree (every room reachable) plus a few loops, and one door opens outside on the side that faces
the street. Rooms take roles by size and by distance from the entrance, and each role is furnished from its own weights.

All grids are ``[row, col]`` of :class:`~biomegen.world.tile.Cell`. Cells are terminal cells, taller than wide, so a
room is ``aspect`` times as many columns as rows.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..world.tile import Cell
from .carve import Point, Rect
from .furnish import Weights, keep_reachable, scatter, weighted_choice

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)
_DOOR = int(Cell.DOOR)

# Shapes a building may take and how often (a plain rectangle is the commonest).
_SHAPES = (("rect", 0.6), ("L", 0.25), ("T", 0.15))
_LOOP_CHANCE = 0.25  # an adjacent pair that is not on the spanning tree gets a door this often


@dataclass(frozen=True)
class Building:
    """A finished building in its own grid.

    Attributes:
        cells: ``[rows, cols]`` of wall, floor, door and furniture cells; void outside the footprint.
        footprint: Bool grid of the cells under the roof: the walls and everything inside them.
        front: The open cell outside the street door (in this grid, possibly just off it), or None.
        doors: Every door cell, the street door first.
        roles: ``(role, floor cells)`` per room, largest first.
    """

    cells: np.ndarray
    footprint: np.ndarray
    front: Optional[Point]
    doors: tuple[Point, ...]
    roles: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Spec:
    """What a building is built to.

    Attributes:
        min_room_rows: The fewest interior rows of a room; interior columns are this times ``aspect``.
        aspect: Cell height over width (how many columns look as wide as a row is tall).
        roles: Room roles, best first: the largest room takes the first, the rest take the others by size in turn.
        furniture: Weights per role (a role with no entry stays bare).
        density: Share of a room's floor cells that get furniture.
        shapes: Which of ``rect``, ``L`` and ``T`` are allowed.
    """

    min_room_rows: int
    aspect: float
    roles: tuple[str, ...]
    furniture: dict[str, Weights]
    density: float
    shapes: tuple[str, ...] = ("rect", "L", "T")


def _wings(rows: int, cols: int, shape: str, rgen: random.Random) -> list[Rect]:
    """Return the outer rectangles ``(x, y, w, h)`` of a footprint: wings that share a wall row or column."""
    if shape == "L":
        main_rows = max(5, round(rows * rgen.uniform(0.5, 0.62)))
        wing_cols = max(8, round(cols * rgen.uniform(0.45, 0.6)))
        return [(0, 0, cols, main_rows), (0, main_rows - 1, wing_cols, rows - main_rows + 1)]
    if shape == "T":
        main_rows = max(5, round(rows * rgen.uniform(0.45, 0.58)))
        wing_cols = max(8, round(cols * rgen.uniform(0.4, 0.55)))
        left = (cols - wing_cols) // 2
        return [(0, 0, cols, main_rows), (left, main_rows - 1, wing_cols, rows - main_rows + 1)]
    return [(0, 0, cols, rows)]


def _split(rgen: random.Random, rect: Rect, min_rows: int, aspect: float, big_rows: int) -> list[Rect]:
    """Cut an outer rectangle into rooms; neighbours share the cut's wall line."""
    x, y, w, h = rect
    min_h = min_rows + 2  # a room's outer height: its rows plus a wall each side
    min_w = math.ceil(min_rows * aspect) + 2
    can_vertical = w >= 2 * min_w - 1
    can_horizontal = h >= 2 * min_h - 1
    big = h > big_rows or w > big_rows * aspect
    if not (can_vertical or can_horizontal) or (not big and rgen.random() < 0.55):
        return [rect]
    vertical = can_vertical and (not can_horizontal or w / aspect >= h)
    if vertical:
        cut = rgen.randint(min_w - 1, w - min_w)
        return _split(rgen, (x, y, cut + 1, h), min_rows, aspect, big_rows) + _split(
            rgen, (x + cut, y, w - cut, h), min_rows, aspect, big_rows
        )
    cut = rgen.randint(min_h - 1, h - min_h)
    return _split(rgen, (x, y, w, cut + 1), min_rows, aspect, big_rows) + _split(
        rgen, (x, y + cut, w, h - cut), min_rows, aspect, big_rows
    )


def _shared(a: Rect, b: Rect) -> Optional[tuple[str, list[Point]]]:
    """Return the door candidates on the wall two rooms share, with the wall's orientation, or None."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if ax + aw - 1 == bx or bx + bw - 1 == ax:  # a shared column
        column = bx if ax + aw - 1 == bx else ax
        lo, hi = max(ay, by) + 1, min(ay + ah, by + bh) - 2
        if hi >= lo:
            return "v", [(column, row) for row in range(lo, hi + 1)]
    if ay + ah - 1 == by or by + bh - 1 == ay:  # a shared row
        row = by if ay + ah - 1 == by else ay
        lo, hi = max(ax, bx) + 1, min(ax + aw, bx + bw) - 2
        if hi >= lo:
            return "h", [(col, row) for col in range(lo, hi + 1)]
    return None


def _entrance(grid: np.ndarray, footprint: np.ndarray, toward: Point, aspect: float) -> Optional[tuple[Point, Point]]:
    """Return ``(door cell, open cell outside it)`` on the outer wall nearest ``toward``, or None."""
    rows, cols = grid.shape
    best: Optional[tuple[tuple[float, int, int], Point, Point]] = None
    for y, x in np.argwhere(grid == _WALL).tolist():
        for step_x, step_y in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            ox, oy, ix, iy = x + step_x, y + step_y, x - step_x, y - step_y
            outside = not (0 <= ox < cols and 0 <= oy < rows) or not footprint[oy, ox]
            if outside and 0 <= ix < cols and 0 <= iy < rows and grid[iy, ix] == _FLOOR:
                key = (((x - toward[0]) / aspect) ** 2 + (y - toward[1]) ** 2, y, x)
                if best is None or key < best[0]:
                    best = (key, (x, y), (ox, oy))
                break
    return (best[1], best[2]) if best is not None else None


def build_building(
    rows: int, cols: int, rgen: random.Random, spec: Spec, toward: Optional[Point] = None
) -> Optional[Building]:
    """Build a building that fits ``rows x cols`` cells (outer size), with its street door facing ``toward``.

    ``toward`` is a point in the building's own grid, outside it or at its edge (None: no street door, for a ruin or a
    sealed vault). Returns None when the space is too small for even one room.
    """
    smallest_rows = spec.min_room_rows + 2
    smallest_cols = math.ceil(spec.min_room_rows * spec.aspect) + 2
    if rows < smallest_rows or cols < smallest_cols:
        return None
    shapes = [name for name, _ in _SHAPES if name in spec.shapes]
    weights = [weight for name, weight in _SHAPES if name in spec.shapes]
    big = rows >= 2 * smallest_rows + 1 and cols >= 2 * smallest_cols
    shape = rgen.choices(shapes, weights)[0] if big and shapes else "rect"
    flip_x = rgen.random() < 0.5
    flip_y = rgen.random() < 0.5
    rooms: list[Rect] = []
    for wing in _wings(rows, cols, shape, rgen):
        rooms += _split(rgen, wing, spec.min_room_rows, spec.aspect, 3 * spec.min_room_rows + 1)

    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    footprint = np.zeros((rows, cols), dtype=bool)
    for x, y, w, h in rooms:
        footprint[y : y + h, x : x + w] = True
        grid[y : y + h, x : x + w] = _WALL
    for x, y, w, h in rooms:
        grid[y + 1 : y + h - 1, x + 1 : x + w - 1] = _FLOOR
    if flip_x:
        grid, footprint = grid[:, ::-1].copy(), footprint[:, ::-1].copy()
        rooms = [(cols - x - w, y, w, h) for x, y, w, h in rooms]
    if flip_y:
        grid, footprint = grid[::-1].copy(), footprint[::-1].copy()
        rooms = [(x, rows - y - h, w, h) for x, y, w, h in rooms]

    entrance = _entrance(grid, footprint, toward, spec.aspect) if toward is not None else None
    start = 0
    doors: list[Point] = []
    front: Optional[Point] = None
    if entrance is not None:
        door, front = entrance
        grid[door[1], door[0]] = _DOOR
        doors.append(door)
        inner = (door[0] - (front[0] - door[0]), door[1] - (front[1] - door[1]))
        start = next(
            (i for i, (x, y, w, h) in enumerate(rooms) if x < inner[0] < x + w - 1 and y < inner[1] < y + h - 1), 0
        )

    adjacent: dict[int, list[tuple[int, list[Point]]]] = {i: [] for i in range(len(rooms))}
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            shared = _shared(rooms[i], rooms[j])
            if shared is not None:
                adjacent[i].append((j, shared[1]))
                adjacent[j].append((i, shared[1]))
    seen = {start}
    order = [start]
    tree: set[tuple[int, int]] = set()
    for node in order:
        links = sorted(adjacent[node], key=lambda link: link[0])
        rgen.shuffle(links)
        for other, cells in links:
            if other not in seen:
                seen.add(other)
                order.append(other)
                tree.add((min(node, other), max(node, other)))
                door = cells[len(cells) // 2] if len(cells) < 3 else cells[rgen.randint(1, len(cells) - 2)]
                grid[door[1], door[0]] = _DOOR
                doors.append(door)
    for i in sorted(adjacent):
        for j, cells in sorted(adjacent[i], key=lambda link: link[0]):
            if i < j and (i, j) not in tree and rgen.random() < _LOOP_CHANCE:
                door = cells[rgen.randint(0, len(cells) - 1)]
                grid[door[1], door[0]] = _DOOR
                doors.append(door)

    roles = _furnish(grid, rooms, start, rgen, spec, doors)
    return Building(grid, footprint, front, tuple(doors), roles)


def _furnish(
    grid: np.ndarray, rooms: list[Rect], start: int, rgen: random.Random, spec: Spec, doors: list[Point]
) -> tuple[tuple[str, int], ...]:
    """Give each room a role (the largest the first) and furnish it; return ``(role, floor cells)``, largest first."""
    by_size = sorted(range(len(rooms)), key=lambda i: (-(rooms[i][2] * rooms[i][3]), i))
    others = spec.roles[1:] or spec.roles
    assigned = {
        room: spec.roles[0] if index == 0 else others[(index - 1) % len(others)] for index, room in enumerate(by_size)
    }
    summary = []
    for i in by_size:
        x, y, w, h = rooms[i]
        role = assigned[i]
        cells = [(cx, cy) for cy in range(y + 1, y + h - 1) for cx in range(x + 1, x + w - 1) if grid[cy, cx] == _FLOOR]
        summary.append((role, len(cells)))
        table = spec.furniture.get(role)
        if table:
            apron = {(dx + sx, dy + sy) for dx, dy in doors for sx, sy in ((0, 1), (0, -1), (1, 0), (-1, 0))}
            free = [c for c in cells if c not in apron]

            def choose(stream: random.Random, _x: int, _y: int, weights: Weights = table) -> Cell:
                return weighted_choice(stream, weights)

            scatter(grid, rgen, free, spec.density, choose)
    keep_reachable(grid, sorted(doors))
    return tuple(summary)
