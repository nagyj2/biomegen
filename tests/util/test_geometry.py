"""Tests for the shared geometry primitives (labelling, distance, A*) incl. backend parity."""

from __future__ import annotations

import math

import numpy as np
import pytest

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


def test_distance_to_unit_sampling_matches_default() -> None:
    # Passing (1, 1) explicitly is the tile metric, identical to the default call.
    rng = np.random.default_rng(3)
    targets = rng.random((12, 15)) < 0.1
    assert np.array_equal(geo.distance_to(targets, sampling=(1.0, 1.0)), geo.distance_to(targets))


def test_distance_to_scales_each_axis_by_sampling() -> None:
    # One target: a cell two columns away is 2 x col_size, two rows away is 2 x row_size.
    targets = np.zeros((5, 5), dtype=bool)
    targets[2, 2] = True
    dist = geo.distance_to(targets, sampling=(40.0, 20.0))
    assert (dist[2, 4], dist[4, 2]) == (40.0, 80.0)


def test_distance_to_fallback_scales_each_axis_by_sampling() -> None:
    # The in-house fallback weights orthogonal steps by the axis size and diagonals by the larger size.
    targets = np.zeros((5, 5), dtype=bool)
    targets[2, 2] = True
    dist = geo.distance_to(targets, backend="pure", sampling=(40.0, 20.0))
    assert (dist[2, 4], dist[4, 2], dist[3, 3]) == (40.0, 80.0, 40.0)


def test_distance_to_fallback_with_equal_sizes_scales_step_count() -> None:
    # Equal non-unit sizes give the unit BFS step count times the size.
    rng = np.random.default_rng(5)
    targets = rng.random((10, 10)) < 0.08
    scaled = geo.distance_to(targets, backend="pure", sampling=(3.0, 3.0))
    assert np.array_equal(scaled, geo.distance_to(targets, backend="pure") * 3.0)


def test_octile_distance_unit_size_is_the_classic_formula() -> None:
    # Unit sizes reproduce (dx + dy) + (sqrt 2 - 2) * min(dx, dy) exactly, so roads are unchanged.
    for b in [(3, 1), (0, 7), (5, 5), (9, 2)]:
        dx, dy = abs(b[0]), abs(b[1])
        assert geo.octile_distance((0, 0), b) == (dx + dy) + (math.sqrt(2.0) - 2.0) * min(dx, dy)


def test_octile_distance_weights_axes_by_cell_size() -> None:
    # Two diagonal steps on a 1x2 grid, then two more columns.
    assert geo.octile_distance((0, 0), (4, 2), col_size=1.0, row_size=2.0) == pytest.approx(
        2 * math.hypot(1.0, 2.0) + 2 * 1.0
    )


def test_step_length_is_euclidean_in_cell_units() -> None:
    # A diagonal step on a 3x4 km grid is 5 km; orthogonal steps are one cell size.
    assert geo.step_length((0, 0), (1, 1), 3.0, 4.0) == 5.0
    assert geo.step_length((0, 0), (0, 1), 3.0, 4.0) == 4.0
