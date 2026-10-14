"""Furnishing: scatter furniture over free floor, and keep every doorway and stair reachable."""

from __future__ import annotations

import random
from collections import deque
from typing import Callable, Iterable, Optional

import numpy as np

from ..world.tile import Cell
from .carve import Point
from .cells import PASSABLE

Weights = list[tuple[Cell, float]]


def weighted_choice(rgen: random.Random, table: Weights) -> Cell:
    """Pick one cell from ``(cell, weight)`` pairs; the weights need not sum to one."""
    total = sum(weight for _cell, weight in table)
    roll = rgen.random() * total
    running = 0.0
    for cell, weight in table:
        running += weight
        if roll < running:
            return cell
    return table[0][0]


def free_floor(grid: np.ndarray, reserved: Iterable[Point] = ()) -> list[Point]:
    """Return the ``(x, y)`` floor cells not in ``reserved``, in row-major order (a stable order to sample from)."""
    keep = set(reserved)
    ys, xs = np.nonzero(grid == int(Cell.FLOOR))
    free = [(int(x), int(y)) for x, y in zip(xs, ys, strict=True) if (int(x), int(y)) not in keep]
    free.sort(key=lambda p: (p[1], p[0]))
    return free


def adjacent(mask: np.ndarray) -> np.ndarray:
    """Return the cells orthogonally next to a True cell of ``mask``."""
    out = np.zeros_like(mask)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def scatter(
    grid: np.ndarray,
    rgen: random.Random,
    cells: list[Point],
    density: float,
    choose: Callable[[random.Random, int, int], Optional[Cell]],
) -> None:
    """Furnish a ``density`` fraction of ``cells``; ``choose(rgen, x, y)`` picks each one (None leaves it bare)."""
    count = int(len(cells) * density)
    if count <= 0:
        return
    for x, y in rgen.sample(cells, min(count, len(cells))):
        cell = choose(rgen, x, y)
        if cell is not None:
            grid[y, x] = int(cell)


def keep_reachable(grid: np.ndarray, specials: list[Point]) -> None:
    """Clear any blocking furniture between the first of ``specials`` (doors, stairs) and each of the others.

    Walks the shortest path through anything that is not rock or void and turns each impassable cell on it back into
    floor, the smallest edit that leaves every stair and door reachable from every other.
    """
    if len(specials) < 2:
        return
    rows, cols = grid.shape
    solid = (int(Cell.WALL), int(Cell.VOID))
    start = specials[0]
    parent: dict[Point, Optional[Point]] = {start: None}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for step_x, step_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + step_x, y + step_y
            if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in parent and int(grid[ny, nx]) not in solid:
                parent[(nx, ny)] = (x, y)
                queue.append((nx, ny))
    for special in specials[1:]:
        node: Optional[Point] = special
        while node is not None and node in parent:
            x, y = node
            if int(grid[y, x]) not in PASSABLE:
                grid[y, x] = int(Cell.FLOOR)
            node = parent[node]
