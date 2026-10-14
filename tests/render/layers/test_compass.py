"""Tests for the compass layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.sampler import Sampler
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "compass"))


def _draw(world, config, **kwargs):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_compass_is_stamped_in_open_sea(config) -> None:
    world = make_world(40, 12, Biome.DEEP, -3000.0)
    assert "N" in _draw(world, config, color=False).glyph and "┼" in _draw(world, config, color=False).glyph


def test_compass_is_not_stamped_on_land(config) -> None:
    world = make_world(40, 12, Biome.GRASS)
    assert "┼" not in _draw(world, config, color=False).glyph


def test_ascii_compass_uses_ascii(config) -> None:
    world = make_world(40, 12, Biome.DEEP, -3000.0)
    assert "+" in _draw(world, config, ascii_only=True, color=False).glyph


def test_compass_skips_corners_that_hold_land(config) -> None:
    # Land in the north-east block pushes the rose to the next open corner (north-west).
    world = make_world(40, 12, Biome.DEEP, -3000.0)
    world.biome[1:4, 30:38] = int(Biome.GRASS)
    glyph = _draw(world, config, color=False).glyph
    assert "┼" in glyph[:, :20]


def test_tiny_grids_get_no_compass(config) -> None:
    world = make_world(6, 3, Biome.DEEP, -3000.0)
    assert "┼" not in _draw(world, config, color=False).glyph
