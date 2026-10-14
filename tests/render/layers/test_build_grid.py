"""Tests for build_grid and the layer registry."""

from __future__ import annotations

import pytest

from biomegen.render.layers import LAYERS, build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.tile import Biome
from tests.render.conftest import make_world


def test_built_in_layers_are_registered() -> None:
    assert {"terrain", "relief", "water"} <= set(LAYERS.names())


def test_unknown_layer_fails_before_drawing(config) -> None:
    world = make_world(2, 2)
    with pytest.raises(KeyError, match="nope"):
        build_grid(world, config, View("t", ("terrain", "nope")), Sampler.viewport(world, 2, 2))


def test_grid_size_follows_the_sampler(config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    grid = build_grid(world, config, View("t", ("terrain",)), Sampler.viewport(world, 3, 5))
    assert (grid.rows, grid.cols) == (3, 5)
