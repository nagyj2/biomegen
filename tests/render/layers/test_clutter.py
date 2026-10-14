"""Tests for the detail-scale floor, rocky floor and the clutter layer."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.detail import DetailSampler
from biomegen.render.layers import build_grid
from biomegen.render.scatter import scatter01
from biomegen.render.views import View
from biomegen.world.tile import Biome, Relief
from tests.render.conftest import make_world

FLOOR_ONLY = View("t", ("terrain",))
FLOOR_RELIEF = View("t", ("terrain", "relief"))
WITH_CLUTTER = View("t", ("terrain", "relief", "clutter"))


def _crisp_config() -> Config:
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    return config


def _draw(world, view, config=None, cam=(0, 0), tiles=None, cell=(10, 5)):
    config = config or _crisp_config()
    tiles = tiles or (world.width, world.height)
    sampler = DetailSampler(world, config, cell[0], cell[1], cam[0], cam[1], tiles[0], tiles[1])
    return build_grid(world, config, view, sampler)


def _share_of_clutter(grid) -> float:
    return float((grid.glyph != ".").mean())


def test_scatter_without_sub_cell_matches_zero_sub_cell() -> None:
    # Map-scale decoration must not change: a zero sub-cell index is the same key as none.
    tile_x, tile_y = np.meshgrid(np.arange(16), np.arange(16))
    zeros = np.zeros_like(tile_x)
    assert (scatter01(5, tile_x, tile_y) == scatter01(5, tile_x, tile_y, zeros, zeros)).all()


def test_scatter_differs_between_cells_of_one_tile() -> None:
    # Cells inside one tile get different values, so clutter does not fill or skip whole tiles.
    tile = np.zeros((1, 8), dtype=np.int64)
    sub = np.arange(8, dtype=np.int64)[np.newaxis, :]
    assert len(set(scatter01(5, tile, tile, sub, tile).ravel().tolist())) == 8


def test_view_without_detail_layers_reuses_the_map_list() -> None:
    assert View("t", ("terrain", "relief")).layers_for(True) == ("terrain", "relief")


def test_view_uses_its_detail_layers_at_detail_scale() -> None:
    assert View("t", ("terrain",), detail_layers=("terrain", "clutter")).layers_for(True) == ("terrain", "clutter")


def test_floor_fills_every_land_cell() -> None:
    # Unlike the map's sparse glyphs, a detail floor is drawn on every cell of grassland.
    grid = _draw(make_world(4, 3, Biome.GRASS), FLOOR_ONLY)
    assert (grid.glyph == ".").all()


def test_water_floor_is_waves() -> None:
    grid = _draw(make_world(4, 3, Biome.LAKE, -10.0), FLOOR_ONLY)
    assert (grid.glyph == "~").all()


def test_mountain_relief_gives_a_rocky_floor() -> None:
    # Mountains are relief, not a biome: their cells get the caret floor of detail_relief.mountain.
    world = make_world(4, 3, Biome.GRASS, 2000.0)
    world.relief[:] = int(Relief.MOUNTAIN)
    assert (_draw(world, FLOOR_ONLY).glyph == "^").all()


def test_hills_keep_the_biome_floor() -> None:
    # Hills have no rocky floor, so the biome's own floor shows.
    world = make_world(4, 3, Biome.GRASS, 900.0)
    world.relief[:] = int(Relief.HILLS)
    assert (_draw(world, FLOOR_ONLY).glyph == ".").all()


def test_relief_layer_does_not_repeat_its_glyph_across_a_block() -> None:
    # At detail scale the relief layer only recolours; the big-map hill glyph must not appear.
    world = make_world(4, 3, Biome.GRASS, 900.0)
    world.relief[:] = int(Relief.HILLS)
    assert "∩" not in _draw(world, FLOOR_RELIEF).glyph


def test_forest_clutter_density_follows_the_table_and_moisture() -> None:
    # moisture 0.5 gives factor 0.4 + 1.4 * 0.5 = 1.1, so about 0.22 * 1.1 of cells carry clutter.
    world = make_world(20, 10, Biome.FOREST)
    world.moisture[:] = 0.5
    assert abs(_share_of_clutter(_draw(world, WITH_CLUTTER)) - 0.242) < 0.03


def test_wetter_forest_is_denser() -> None:
    dry = make_world(20, 10, Biome.FOREST)
    wet = make_world(20, 10, Biome.FOREST)
    wet.moisture[:] = 1.0
    assert _share_of_clutter(_draw(wet, WITH_CLUTTER)) > _share_of_clutter(_draw(dry, WITH_CLUTTER)) + 0.1


def test_clutter_uses_only_the_row_glyphs() -> None:
    world = make_world(20, 10, Biome.FOREST)
    world.moisture[:] = 0.5
    assert set(np.unique(_draw(world, WITH_CLUTTER).glyph)) <= {".", "t", "T"}


def test_higher_ground_has_more_scree() -> None:
    # Mountain scree scales with relative elevation: the high half of the world is denser than the low half.
    world = make_world(20, 10, Biome.GRASS, 100.0)
    world.relief[:] = int(Relief.MOUNTAIN)
    world.elevation_m[:, 10:] = 4000.0
    glyph = _draw(world, WITH_CLUTTER).glyph
    assert float((glyph[:, 100:] != "^").mean()) > float((glyph[:, :100] != "^").mean()) + 0.1


def test_no_clutter_on_water() -> None:
    assert (_draw(make_world(10, 6, Biome.LAKE, -10.0), WITH_CLUTTER).glyph == "~").all()


def test_clutter_holds_still_when_the_camera_pans() -> None:
    # Clutter is keyed on the world tile and sub-cell, so two tiles of pan shift the picture by two blocks.
    world = make_world(12, 6, Biome.FOREST)
    world.moisture[:] = 0.5
    first = _draw(world, WITH_CLUTTER, cam=(0, 0), tiles=(8, 6))
    panned = _draw(world, WITH_CLUTTER, cam=(2, 0), tiles=(8, 6))
    assert (first.glyph[:, 20:] == panned.glyph[:, :60]).all()
