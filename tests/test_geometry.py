"""Tests for the shared geometry primitives (labelling, distance, A*) incl. backend parity."""

from __future__ import annotations

import numpy as np

from biomegen.util import geometry as geo


def test_neighbors_are_bounds_checked() -> None:
    assert set(geo.neighbors4(0, 0, 3, 3)) == {(1, 0), (0, 1)}
    assert len(geo.neighbors8(1, 1, 3, 3)) == 8


def test_label_by_value_basic() -> None:
    # Two separate components of value 1, one of value 0.
    values = np.array(
        [
            [1, 1, 0],
            [1, 0, 0],
            [0, 0, 1],
        ]
    )
    labels, count = geo.label_by_value(values, connectivity=4, backend="numpy")
    # Top-left 1-block, the 0-region, and the lone bottom-right 1 are 3 distinct components.
    assert count == 3
    assert labels[0, 0] == labels[1, 0]  # connected ones share a label
    assert labels[0, 0] != labels[2, 2]  # disjoint ones differ


def test_label_by_value_backend_parity() -> None:
    rng = np.random.default_rng(0)
    values = rng.integers(0, 3, size=(20, 25))
    scipy_labels, scipy_n = geo.label_by_value(values, connectivity=4, backend="scipy")
    bfs_labels, bfs_n = geo.label_by_value(values, connectivity=4, backend="numpy")
    assert scipy_n == bfs_n
    # The two backends may number components differently, but the PARTITION must be identical:
    # two cells are in the same scipy component iff they are in the same in-house component.

    def partition_key(labels):
        # Map each label to the sorted tuple of its member coordinates.
        groups = {}
        for (y, x), lab in np.ndenumerate(labels):
            groups.setdefault(int(lab), []).append((y, x))
        return sorted(tuple(sorted(v)) for v in groups.values())

    assert partition_key(scipy_labels) == partition_key(bfs_labels)


def test_distance_to_ocean_like_field() -> None:
    # One ocean tile in the corner; distance should grow with separation.
    targets = np.zeros((5, 5), dtype=bool)
    targets[0, 0] = True
    d_scipy = geo.distance_to(targets, backend="scipy", metric="euclidean")
    assert d_scipy[0, 0] == 0.0
    assert d_scipy[0, 4] > d_scipy[0, 1]
    # In-house BFS fallback also marks the source 0 and increases outward.
    d_bfs = geo.distance_to(targets, backend="numpy", metric="chebyshev")
    assert d_bfs[0, 0] == 0.0
    assert d_bfs[4, 4] >= d_bfs[1, 1]


def test_distance_to_no_targets_is_inf() -> None:
    targets = np.zeros((4, 4), dtype=bool)
    d = geo.distance_to(targets, backend="scipy")
    assert np.isinf(d).all()


def test_astar_finds_shortest_path_on_open_grid() -> None:
    w = h = 6

    def neighbors(node):
        return geo.neighbors4(node[0], node[1], w, h)

    def cost(_a, _b):
        return 1.0

    def heuristic(a, b):  # type: ignore[misc]
        return abs(a[0] - b[0]) + abs(a[1] - b[1])  # type: ignore[index]

    path = geo.astar((0, 0), (5, 5), neighbors, cost, heuristic_fn=heuristic)
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (5, 5)
    # Manhattan-optimal length on a 4-connected grid is dx+dy+1 nodes.
    assert len(path) == (5 + 5) + 1


def test_astar_routes_around_expensive_terrain() -> None:
    w = h = 5
    # A vertical wall of very high cost down the middle column, with a gap at the bottom.
    cost_grid = np.ones((h, w))
    cost_grid[0:4, 2] = 1000.0

    def neighbors(node):
        return geo.neighbors4(node[0], node[1], w, h)

    def cost(_a, b):
        return float(cost_grid[b[1], b[0]])

    path = geo.astar((0, 0), (4, 0), neighbors, cost)
    assert path is not None
    # The cheapest route detours down around the wall rather than paying 1000 to cross it.
    assert not any(node[1] < 4 and node[0] == 2 for node in path)  # type: ignore[index]


def test_astar_returns_none_when_unreachable() -> None:
    def neighbors(_node):
        return []

    path = geo.astar((0, 0), (1, 1), neighbors, lambda a, b: 1.0)
    assert path is None
