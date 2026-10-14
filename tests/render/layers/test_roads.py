"""Tests for the roads layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.layers.roads import connection_mask8, road_glyph_table
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "roads"))


def _draw(world, config, **kwargs):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_connection_mask_marks_road_neighbours() -> None:
    # A horizontal run: the middle tile connects east (4) and west (64) only.
    world = make_world(3, 3)
    world.road[1, :] = 1
    assert int(connection_mask8(world.road)[1, 1]) == 4 + 64


def test_road_end_connects_one_way() -> None:
    world = make_world(3, 3)
    world.road[1, :] = 1
    assert int(connection_mask8(world.road)[1, 0]) == 4


def test_connection_mask_marks_diagonal_neighbours() -> None:
    # A rising diagonal: the middle tile connects north-east (2) and south-west (32).
    world = make_world(3, 3)
    world.road[2, 0] = world.road[1, 1] = world.road[0, 2] = 1
    assert int(connection_mask8(world.road)[1, 1]) == 2 + 32


def test_a_corner_does_not_count_as_a_diagonal_link() -> None:
    # An L of three tiles: the end tile touches the far end at a corner, but they already join through the middle.
    world = make_world(3, 3)
    world.road[0, 0] = world.road[0, 1] = world.road[1, 1] = 1
    assert int(connection_mask8(world.road)[0, 0]) == 4


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


def _center_glyph(config, cells, **kwargs) -> str:
    world = make_world(3, 3, Biome.GRASS)
    for y, x in cells:
        world.road[y, x] = 1
    return str(_draw(world, config, **kwargs).glyph[1, 1])


def test_rising_diagonal_road_draws_a_slash(config) -> None:
    assert _center_glyph(config, [(2, 0), (1, 1), (0, 2)]) == "╱"


def test_falling_diagonal_road_draws_a_backslash(config) -> None:
    assert _center_glyph(config, [(0, 0), (1, 1), (2, 2)]) == "╲"


def test_ascii_diagonal_road_draws_ascii_slashes(config) -> None:
    assert _center_glyph(config, [(2, 0), (1, 1), (0, 2)], ascii_only=True) == "/"


def test_diagonal_bend_draws_a_crossing(config) -> None:
    # Two diagonal neighbours that are not opposite (north-east and south-east) meet at a point.
    assert _center_glyph(config, [(0, 2), (1, 1), (2, 2)]) == "╳"


def test_cardinal_and_diagonal_neighbours_meeting_draw_a_junction(config) -> None:
    # A road from the west that forks north-east and south-east: three roads meet at the centre tile.
    assert _center_glyph(config, [(1, 0), (1, 1), (0, 2), (2, 2)]) == "✳"


def test_one_cardinal_and_one_diagonal_neighbour_take_the_diagonal_slant(config) -> None:
    # A road arriving from the west that bends north-east keeps a smooth slash, not a junction.
    assert _center_glyph(config, [(1, 0), (1, 1), (0, 2)]) == "╱"


def test_every_neighbour_combination_has_a_glyph(config) -> None:
    # All 256 masks map to one printable character, in both the unicode and the ascii set.
    assert all(
        len(road_glyph_table(config, ascii_only)) == 256
        and all(g.strip() or g == " " for g in road_glyph_table(config, ascii_only))
        for ascii_only in (False, True)
    )


def test_ascii_table_is_plain_ascii(config) -> None:
    assert all(ord(g) < 128 for g in road_glyph_table(config, True))
