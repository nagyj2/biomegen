"""Tests for the water layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.tile import Biome, WaterType
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "water"))


def _draw(world, config, view=VIEW):
    return build_grid(world, config, view, Sampler.viewport(world, world.height, world.width))


def test_river_over_land_draws_the_water_glyph(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.water_type[1, 1] = int(WaterType.FRESH)
    assert _draw(world, config).glyph[1, 1] == config.get("render.water.river_glyph")


def test_river_fill_is_bluer_than_the_land_beside_it(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.water_type[1, 1] = int(WaterType.FRESH)
    grid = _draw(world, config)
    assert grid.bg[1, 1, 2] > grid.bg[1, 0, 2]


def test_lake_cells_are_not_treated_as_rivers(config) -> None:
    # A fresh-water cell whose biome is already water keeps the terrain drawing.
    world = make_world(3, 3, Biome.LAKE, -10.0)
    world.water_type[:] = int(WaterType.FRESH)
    assert _draw(world, config).glyph[1, 1] == config.get("tables.biomes.lake.glyph")


def test_tinted_views_blend_the_river_more_gently(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.water_type[1, 1] = int(WaterType.FRESH)
    plain = _draw(world, config).bg[1, 1].astype(int)
    tinted = _draw(world, config, View("t", ("terrain", "water"), "elevation")).bg[1, 1].astype(int)
    assert abs(int(tinted[0]) - int(plain[0])) > 0
