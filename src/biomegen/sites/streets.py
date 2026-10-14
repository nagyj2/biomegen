"""Streets: least-cost paths over open ground, bridging water where a street has to cross it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Optional, cast

import numpy as np

from ..util import geometry as geo
from ..world.tile import Cell
from .carve import Point

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_RAIL = int(Cell.BRIDGE_WALL)
_OPEN = (_VOID, _PATH, _BRIDGE, _RAIL)  # cells a street may enter
_REUSE = 0.4  # cost multiplier on an existing street, so streets merge instead of running side by side


@dataclass(frozen=True)
class StreetRules:
    """How streets are routed.

    Attributes:
        water_cost: Cost of a cell over water relative to dry ground (such a cell becomes a bridge).
        bridge_max: The most consecutive water cells a street will bridge.
        aspect: Cell height over width; a vertical step is this many times a horizontal one.
    """

    water_cost: float
    bridge_max: int
    aspect: float


def _route(grid: np.ndarray, dry: np.ndarray, a: Point, b: Point, rules: StreetRules) -> Optional[list[Point]]:
    rows, cols = grid.shape

    def neighbours(node: Hashable) -> list[Point]:
        x, y = cast(Point, node)
        out = []
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < cols and 0 <= ny < rows and (int(grid[ny, nx]) in _OPEN or (nx, ny) == b):
                out.append((nx, ny))
        return out

    def cost(p: Hashable, q: Hashable) -> float:
        (px, _py), (qx, qy) = cast(Point, p), cast(Point, q)
        step = rules.aspect if px == qx else 1.0
        base = 1.0 if dry[qy, qx] else rules.water_cost
        return step * base * (_REUSE if int(grid[qy, qx]) == _PATH else 1.0)

    def heuristic(n: Hashable, goal: Hashable) -> float:
        (nx, ny), (gx, gy) = cast(Point, n), cast(Point, goal)
        return _REUSE * (abs(nx - gx) + rules.aspect * abs(ny - gy))

    path = geo.astar(a, b, neighbours, cost, heuristic, max_expansions=rows * cols * 2)
    return [cast(Point, node) for node in path] if path is not None else None


def _longest_water_run(path: list[Point], dry: np.ndarray) -> int:
    longest = run = 0
    for x, y in path:
        run = 0 if dry[y, x] else run + 1
        longest = max(longest, run)
    return longest


def lay_street(grid: np.ndarray, dry: np.ndarray, a: Point, b: Point, rules: StreetRules) -> Optional[list[Point]]:
    """Route a street from ``a`` to ``b`` and write it; return its path, or None if there is none or water is too wide.

    Dry cells become path, and a vertical run is widened to the cell aspect in columns so it looks as thick as a
    horizontal one. Water cells become bridge deck, railed on both sides where there is water to rail.
    """
    path = _route(grid, dry, a, b, rules)
    if path is None or _longest_water_run(path, dry) > rules.bridge_max:
        return None
    rows, cols = grid.shape
    width = max(1, round(rules.aspect))
    for index, (x, y) in enumerate(path):
        if grid[y, x] != _VOID:
            continue
        if dry[y, x]:
            grid[y, x] = _PATH
            vertical = (index > 0 and path[index - 1][0] == x) or (index + 1 < len(path) and path[index + 1][0] == x)
            for extra in range(1, width):
                if vertical and x + extra < cols and dry[y, x + extra] and grid[y, x + extra] == _VOID:
                    grid[y, x + extra] = _PATH
            continue
        grid[y, x] = _BRIDGE
        prev = path[index - 1] if index else path[index + 1] if len(path) > 1 else (x, y)
        across = [(x, y - 1), (x, y + 1)] if prev[1] == y else [(x - 1, y), (x + 1, y)]
        for rx, ry in across:
            if 0 <= rx < cols and 0 <= ry < rows and not dry[ry, rx] and grid[ry, rx] == _VOID:
                grid[ry, rx] = _RAIL
    return path
