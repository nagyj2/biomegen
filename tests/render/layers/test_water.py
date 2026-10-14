"""Tests for the water layer."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.render.detail import DetailSampler
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


def _draw_detail(world, view=VIEW):
    # Warp off, so the 10 x 5 cells of each tile line up with the tile grid.
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    return build_grid(world, config, view, DetailSampler(world, config, 10, 5, 0, 0, world.width, world.height))


def test_diagonal_river_tiles_join_at_detail_scale(config) -> None:
    # Two river tiles touching at a corner give the cell between them water, so the stream is unbroken.
    world = make_world(2, 2, Biome.GRASS)
    world.water_type[0, 0] = world.water_type[1, 1] = int(WaterType.FRESH)
    assert _draw_detail(world).glyph[4, 9] == config.get("render.water.river_glyph")


def test_detail_river_leaves_distant_land_alone(config) -> None:
    # The far side of a land tile beside a river tile is still land.
    world = make_world(3, 1, Biome.GRASS)
    world.water_type[0, 0] = int(WaterType.FRESH)
    assert _draw_detail(world).glyph[2, 29] != config.get("render.water.river_glyph")
