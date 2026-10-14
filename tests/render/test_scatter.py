"""Tests for the deterministic per-tile scatter."""

from __future__ import annotations

import numpy as np

from biomegen.render.scatter import scatter01


def _tiles() -> tuple[np.ndarray, np.ndarray]:
    grid_x, grid_y = np.meshgrid(np.arange(64), np.arange(64))
    return grid_x, grid_y


def test_scatter_is_repeatable() -> None:
    tile_x, tile_y = _tiles()
    assert (scatter01(7, tile_x, tile_y) == scatter01(7, tile_x, tile_y)).all()


def test_scatter_depends_on_the_salt() -> None:
    tile_x, tile_y = _tiles()
    assert not (scatter01(7, tile_x, tile_y) == scatter01(8, tile_x, tile_y)).all()


def test_scatter_is_uniform_enough_for_density_thresholds() -> None:
    # A threshold of 0.25 should select about a quarter of the tiles.
    tile_x, tile_y = _tiles()
    assert abs(float((scatter01(3, tile_x, tile_y) < 0.25).mean()) - 0.25) < 0.03
