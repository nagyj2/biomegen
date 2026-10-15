"""Streets: least-cost paths over open ground, bridging water where a street has to cross it, and the road itself.

The road that reaches a site is the world's own (:mod:`biomegen.sampling.roads`). A layout lays it into its grid with
:func:`lay_roads` so streets, lots and doors are built round and onto it, and the finished plan hands it back with
:func:`clear_roads`: the renderer already draws the road everywhere, so the plan leaves those cells to it and the
road is the same, in the same place, inside the site as outside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Optional, cast

import numpy as np

from ..util import geometry as geo
from ..world.tile import Cell
from .carve import Point
from .patch import SitePatch

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_RAIL = int(Cell.BRIDGE_WALL)
_OPEN = (_VOID, _PATH, _BRIDGE, _RAIL)  # cells a street may enter
_REUSE = 0.4  # cost multiplier on an existing street, so streets merge instead of running side by side
_GREED = 0.8  # weight of the straight-line estimate: above the admissible 0.4, so the search heads for the goal


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


def _route(
    grid: np.ndarray, dry: np.ndarray, a: Point, b: Point, rules: StreetRules, allowed: Optional[np.ndarray] = None
) -> Optional[list[Point]]:
    rows, cols = grid.shape

    def neighbours(node: Hashable) -> list[Point]:
        x, y = cast(Point, node)
        out = []
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (0 <= nx < cols and 0 <= ny < rows):
                continue
            if (nx, ny) == b or (int(grid[ny, nx]) in _OPEN and (allowed is None or allowed[ny, nx])):
                out.append((nx, ny))
        return out

    def cost(p: Hashable, q: Hashable) -> float:
        (px, _py), (qx, qy) = cast(Point, p), cast(Point, q)
        step = rules.aspect if px == qx else 1.0
        base = 1.0 if dry[qy, qx] else rules.water_cost
        return step * base * (_REUSE if int(grid[qy, qx]) == _PATH else 1.0)

    def heuristic(n: Hashable, goal: Hashable) -> float:
        (nx, ny), (gx, gy) = cast(Point, n), cast(Point, goal)
        return _GREED * (abs(nx - gx) + rules.aspect * abs(ny - gy))

    path = geo.astar(a, b, neighbours, cost, heuristic, max_expansions=rows * cols * 2)
    return [cast(Point, node) for node in path] if path is not None else None


def _longest_water_run(path: list[Point], dry: np.ndarray) -> int:
    longest = run = 0
    for x, y in path:
        run = 0 if dry[y, x] else run + 1
        longest = max(longest, run)
    return longest


def lay_street(
    grid: np.ndarray,
    dry: np.ndarray,
    a: Point,
    b: Point,
    rules: StreetRules,
    allowed: Optional[np.ndarray] = None,
) -> Optional[list[Point]]:
    """Route a street from ``a`` to ``b`` and write it; return its path, or None if there is none or water is too wide.

    With ``allowed`` the street keeps to those cells (the ends excepted).

    Dry cells become path, and a vertical run is widened to the cell aspect in columns so it looks as thick as a
    horizontal one. Water cells become bridge deck, railed on both sides where there is water to rail.
    """
    path = _route(grid, dry, a, b, rules, allowed)
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


def lay_roads(grid: np.ndarray, patch: SitePatch, replace: tuple[int, ...] = (_VOID,)) -> None:
    """Lay the road into ``grid``: path on dry bed cells, deck over water, railings in the band beside it.

    Only cells whose value is in ``replace`` change, so a layout lays the road before its buildings (to build round
    it) or after them (so the road stops at a wall).
    """
    free = np.isin(grid, replace)
    grid[patch.road & patch.dry & free] = _PATH
    grid[patch.road & ~patch.dry & free] = _BRIDGE
    grid[patch.rail & ~patch.road & ~patch.dry & free] = _RAIL


def clear_roads(cells: np.ndarray, patch: SitePatch) -> np.ndarray:
    """Return ``cells`` with the road's own cells made void, so the world's road shows there; a lane stays."""
    cleared = cells.copy()
    road = patch.road & np.isin(cells, (_PATH, _BRIDGE, _RAIL))
    railing = patch.rail & ~patch.dry & np.isin(cells, (_BRIDGE, _RAIL))  # the roads layer draws bridge railings
    cleared[road | railing] = _VOID
    return cleared
