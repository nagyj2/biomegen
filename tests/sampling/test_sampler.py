"""Tests for the sampler that maps grid cells to world positions."""

from __future__ import annotations

import numpy as np

from biomegen.sampling.sampler import Sampler
from tests.render.conftest import make_world


def test_viewport_at_step_one_reads_each_tile() -> None:
    # One cell per tile: nearest() returns the world array unchanged.
    world = make_world(4, 3)
    world.elevation_m[:] = np.arange(12).reshape(3, 4)
    sampler = Sampler.viewport(world, 3, 4)
    assert (sampler.nearest(world.elevation_m) == world.elevation_m).all()


def test_viewport_stride_skips_tiles() -> None:
    world = make_world(6, 2)
    world.elevation_m[:] = np.arange(12).reshape(2, 6)
    sampler = Sampler.viewport(world, 1, 3, step_x=2.0)
    assert sampler.nearest(world.elevation_m)[0].tolist() == [0, 2, 4]


def test_cells_past_the_edge_are_not_inside() -> None:
    world = make_world(3, 3)
    sampler = Sampler.viewport(world, 3, 5)
    assert sampler.inside[0].tolist() == [True, True, True, False, False]


def test_bilinear_blends_neighbouring_tiles() -> None:
    world = make_world(2, 2)
    world.elevation_m[:] = [[0.0, 10.0], [0.0, 10.0]]
    sampler = Sampler.viewport(world, 1, 1, x0=0.5)
    assert sampler.bilinear(world.elevation_m)[0, 0] == 5.0


def test_bilinear_clamps_at_the_world_edge() -> None:
    world = make_world(2, 2)
    world.elevation_m[:] = [[0.0, 10.0], [0.0, 10.0]]
    sampler = Sampler.viewport(world, 1, 1, x0=1.0)
    assert sampler.bilinear(world.elevation_m, dx=5.0)[0, 0] == 10.0


def test_cell_of_inverts_a_viewport() -> None:
    # Tile (5, 2) shown from an origin at (3, 1) with unit steps sits at column 2, row 1.
    world = make_world(10, 6)
    assert Sampler.viewport(world, 4, 6, x0=3.0, y0=1.0).cell_of(5, 2) == (2, 1)


def test_cell_of_is_none_off_the_grid() -> None:
    world = make_world(10, 6)
    assert Sampler.viewport(world, 2, 2).cell_of(5, 1) is None
