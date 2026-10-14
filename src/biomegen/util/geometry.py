"""Shared spatial primitives reused across hydrology, regions, POI placement and roads.

Centralising these here means stages reuse one correct, tested implementation instead of each
reinventing BFS / union-find / A*. Two families have a fast ``scipy`` path and an in-house fallback,
selected by the ``compute.backend`` config key:

* :func:`label_by_value`  - connected components of equal-valued cells (region & lake labelling).
* :func:`distance_to`     - distance from every cell to the nearest "target" cell (dist-to-ocean,
                            distance-to-freshwater, remoteness).

:func:`astar` is the generic weighted-grid pathfinder used by the roads stage. Neighbour iterators
round out the module.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from typing import Any, Callable, Dict, Hashable, Iterable, List, Optional, Tuple, cast

import numpy as np

Coord = Tuple[int, int]


# ---------------------------------------------------------------------------
# Neighbour iterators (bounds-checked).
# ---------------------------------------------------------------------------
# Offsets are listed in a fixed order so any iteration built on them is deterministic.
_OFFSETS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_OFFSETS8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def neighbors4(x: int, y: int, width: int, height: int) -> List[Coord]:
    """Return the in-bounds 4-connected (orthogonal) neighbours of ``(x, y)``."""
    return [(x + dx, y + dy) for dx, dy in _OFFSETS4 if 0 <= x + dx < width and 0 <= y + dy < height]


def neighbors8(x: int, y: int, width: int, height: int) -> List[Coord]:
    """Return the in-bounds 8-connected (orthogonal + diagonal) neighbours of ``(x, y)``."""
    return [(x + dx, y + dy) for dx, dy in _OFFSETS8 if 0 <= x + dx < width and 0 <= y + dy < height]


# ---------------------------------------------------------------------------
# Connected components of equal-valued cells.
# ---------------------------------------------------------------------------
def _label_by_value_scipy(values: np.ndarray, connectivity: int) -> Tuple[np.ndarray, int]:
    """scipy path: label each distinct value's mask with ndimage.label and offset the ids."""
    from scipy import ndimage

    structure = ndimage.generate_binary_structure(2, 1 if connectivity == 4 else 2)
    labels = np.full(values.shape, -1, dtype=np.int32)
    offset = 0
    # Iterate values in sorted order so component numbering is deterministic.
    for value in sorted(np.unique(values).tolist()):
        mask = values == value
        labeled = cast(Any, ndimage.label(mask, structure=structure))
        comp, n = labeled
        sel = comp > 0
        labels[sel] = comp[sel] - 1 + offset
        offset += n
    return labels, offset


def _label_by_value_bfs(values: np.ndarray, connectivity: int) -> Tuple[np.ndarray, int]:
    """In-house path: BFS flood fill, assigning a new label to each equal-valued component."""
    h, w = values.shape
    labels = np.full(values.shape, -1, dtype=np.int32)
    offsets = _OFFSETS4 if connectivity == 4 else _OFFSETS8
    next_label = 0
    # Row-major scan order makes labelling deterministic.
    for y in range(h):
        for x in range(w):
            if labels[y, x] != -1:
                continue
            target = values[y, x]
            queue = deque([(x, y)])
            labels[y, x] = next_label
            while queue:
                cx, cy = queue.popleft()
                for dx, dy in offsets:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and labels[ny, nx] == -1 and values[ny, nx] == target:
                        labels[ny, nx] = next_label
                        queue.append((nx, ny))
            next_label += 1
    return labels, next_label


def label_by_value(values: np.ndarray, connectivity: int = 4, backend: str = "scipy") -> Tuple[np.ndarray, int]:
    """Label connected components of equal-valued cells.

    Returns ``(labels, count)`` where ``labels`` is an ``int32`` array of component ids ``0..count-1``
    (every cell belongs to exactly one component). Two adjacent cells share a label iff they hold the
    same value and are connected under the chosen ``connectivity`` (4 or 8). Used to turn a per-tile
    "group" field into discrete regions, and to find lake basins.
    """
    if backend == "scipy":
        try:
            return _label_by_value_scipy(values, connectivity)
        except ImportError:
            pass  # fall through to the in-house implementation
    return _label_by_value_bfs(values, connectivity)


# ---------------------------------------------------------------------------
# Distance from every cell to the nearest target cell.
# ---------------------------------------------------------------------------
def _distance_bfs(targets: np.ndarray, connectivity: int) -> np.ndarray:
    """Multi-source BFS distance (step count) from every cell to the nearest True cell in ``targets``."""
    h, w = targets.shape
    INF = np.float32(np.inf)
    dist = np.full(targets.shape, INF, dtype=np.float32)
    offsets = _OFFSETS4 if connectivity == 4 else _OFFSETS8
    queue: deque[Coord] = deque()
    ys, xs = np.nonzero(targets)
    for x, y in zip(xs.tolist(), ys.tolist(), strict=True):
        dist[y, x] = 0.0
        queue.append((x, y))
    while queue:
        cx, cy = queue.popleft()
        d = dist[cy, cx] + 1.0
        for dx, dy in offsets:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h and d < dist[ny, nx]:
                dist[ny, nx] = d
                queue.append((nx, ny))
    return dist


def distance_to(targets: np.ndarray, backend: str = "scipy", metric: str = "euclidean") -> np.ndarray:
    """Return a float array of the distance from every cell to the nearest True cell in ``targets``.

    With the scipy backend and ``metric='euclidean'`` this is an exact Euclidean distance transform
    (``distance_transform_edt``); the in-house fallback returns an 8-connected BFS step count (a
    Chebyshev approximation). Target cells get distance 0. If there are no targets, every cell is
    ``inf``.
    """
    if not targets.any():
        return np.full(targets.shape, np.inf, dtype=np.float32)
    if backend == "scipy" and metric == "euclidean":
        try:
            from scipy import ndimage

            # distance_transform_edt measures distance from each True cell to the nearest False cell,
            # so invert: ~targets is True on non-target cells, giving their distance to a target.
            dist = cast(Any, ndimage.distance_transform_edt(~targets))
            return cast(np.ndarray, dist).astype(np.float32)
        except ImportError:
            pass
    connectivity = 8 if metric in ("euclidean", "chebyshev") else 4
    return _distance_bfs(targets, connectivity)


# ---------------------------------------------------------------------------
# Generic A* over a weighted graph (used for roads).
# ---------------------------------------------------------------------------
def octile_distance(a: Coord, b: Coord) -> float:
    """Octile distance heuristic for 8-connected grids (admissible when min step cost is 1)."""
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    return (dx + dy) + (math.sqrt(2.0) - 2.0) * min(dx, dy)


def astar(
    start: Hashable,
    goal: Hashable,
    neighbors_fn: Callable[[Hashable], Iterable[Hashable]],
    cost_fn: Callable[[Hashable, Hashable], float],
    heuristic_fn: Optional[Callable[[Hashable, Hashable], float]] = None,
    max_expansions: Optional[int] = None,
    goal_fn: Optional[Callable[[Hashable], bool]] = None,
) -> Optional[List[Hashable]]:
    """Find a least-cost path from ``start`` to ``goal`` with the A* algorithm.

    Parameters
    ----------
    neighbors_fn:
        ``node -> iterable of adjacent nodes``.
    cost_fn:
        ``(a, b) -> step cost`` to move from ``a`` to neighbour ``b`` (must be non-negative).
    heuristic_fn:
        Optional admissible estimate ``(node, goal) -> cost``. If omitted, A* degenerates to Dijkstra
        (heuristic 0), which always finds the optimum but explores more nodes.
    max_expansions:
        Optional cap on the number of node expansions. If the search expands more than this many
        nodes without reaching ``goal``, it returns ``None`` (caller can fall back). This bounds the
        cost of searches over weak/non-monotone cost surfaces (e.g. meandering roads) so the open set
        cannot wander indefinitely.
    goal_fn:
        Optional callable ``node -> bool`` that replaces the ``current == goal`` equality check.
        Use when the state representation encodes extra information (e.g. direction) beyond position,
        so that multiple states map to the same logical goal. When provided, ``goal`` is still passed
        to ``heuristic_fn`` as usual.

    Returns the path as a list ``[start, ..., goal]`` or ``None`` if ``goal`` is unreachable (or the
    expansion cap is hit). A monotonic insertion counter breaks ties deterministically so the same
    inputs always yield the same path.
    """
    if heuristic_fn is None:
        heuristic_fn = lambda a, b: 0.0  # noqa: E731 - Dijkstra fallback

    _at_goal = goal_fn if goal_fn is not None else lambda n: n == goal

    counter = 0
    expansions = 0
    # Priority queue of (f_score, insertion_order, node).
    open_heap: List[Tuple[float, int, Hashable]] = [(0.0, counter, start)]
    came_from: Dict[Hashable, Hashable] = {}
    g_score: Dict[Hashable, float] = {start: 0.0}
    closed: set = set()

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if _at_goal(current):
            # Reconstruct the path by walking parents back to the start.
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        if current in closed:
            continue
        closed.add(current)
        expansions += 1
        if max_expansions is not None and expansions > max_expansions:
            return None  # bail out of an over-long search; caller falls back
        for nb in neighbors_fn(current):
            if nb in closed:
                continue
            tentative = g_score[current] + cost_fn(current, nb)
            if tentative < g_score.get(nb, math.inf):
                came_from[nb] = current
                g_score[nb] = tentative
                counter += 1
                f = tentative + heuristic_fn(nb, goal)
                heapq.heappush(open_heap, (f, counter, nb))
    return None
