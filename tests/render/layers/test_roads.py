"""Tests for the roads layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.layers.roads import connection_mask
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "roads"))


def _draw(world, config, **kwargs):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_connection_mask_marks_road_neighbours() -> None:
    # A horizontal run: the middle tile connects east and west only (2 + 8).
    world = make_world(3, 3)
    world.road[1, :] = 1
    assert int(connection_mask(world.road)[1, 1]) == 10


def test_road_end_connects_one_way() -> None:
    world = make_world(3, 3)
    world.road[1, :] = 1
    assert int(connection_mask(world.road)[1, 0]) == 2


def test_straight_road_uses_the_horizontal_glyph(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.road[1, :] = 1
    assert _draw(world, config).glyph[1, 1] == config.get("render.roads.glyphs")[10]


def test_ascii_road_uses_ascii_glyphs(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.road[1, :] = 1
    assert _draw(world, config, ascii_only=True).glyph[1, 1] == config.get("render.roads.ascii")[10]


def test_road_keeps_the_terrain_fill(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.road[1, 1] = 1
    drawn = _draw(world, config)
    bare = build_grid(world, config, View("t", ("terrain",)), Sampler.viewport(world, 3, 3))
    assert drawn.bg[1, 1].tolist() == bare.bg[1, 1].tolist()


def test_off_road_cells_are_untouched(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.road[1, 1] = 1
    assert _draw(world, config, color=False).glyph[0, 0] == config.get("tables.biomes.grass.glyph")
