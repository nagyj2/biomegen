"""Tests for the terrain layer."""

from __future__ import annotations

import numpy as np

from biomegen.render.layers import build_grid
from biomegen.render.sampler import Sampler
from biomegen.render.views import View
from biomegen.world.tile import Biome
from tests.render.conftest import make_world

TERRAIN = View("t", ("terrain",))


def _draw(world, config, **kwargs):
    return build_grid(world, config, TERRAIN, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_deep_sea_darkens_with_depth(config) -> None:
    # Deeper water is drawn darker than shallow water of the same biome.
    world = make_world(2, 1, Biome.DEEP, -100.0)
    world.elevation_m[0, 1] = -3500.0
    grid = _draw(world, config)
    assert grid.bg[0, 1].sum() < grid.bg[0, 0].sum()


def test_land_cell_takes_its_biome_colour_on_flat_ground(config) -> None:
    # With no slope the hillshade factor is 1, so the fill is the table colour.
    world = make_world(5, 5, Biome.GRASS, 100.0)
    grid = _draw(world, config)
    assert grid.bg[2, 2].tolist() == list(config.get("tables.biomes.grass.bg"))


def test_slope_facing_the_light_is_brighter(config) -> None:
    # Ground rising toward the south-east faces the north-west light, so it is brighter than ground
    # falling toward the south-east by the same amount.
    world = make_world(5, 3, Biome.GRASS, 1000.0)
    ramp = np.arange(5) * 100.0
    world.elevation_m[:] = 1000.0 + ramp
    lit = _draw(world, config).bg[1, 2].sum()
    world.elevation_m[:] = 1000.0 - ramp
    assert lit > _draw(world, config).bg[1, 2].sum()


def test_sparse_biome_hides_some_glyphs_in_colour(config) -> None:
    world = make_world(40, 20, Biome.GRASS)
    grid = _draw(world, config)
    assert 0.3 < float((grid.glyph != " ").mean()) < 0.6


def test_sparse_biome_shows_every_glyph_without_colour(config) -> None:
    # Colourless output needs the glyph to identify the biome, so nothing is thinned.
    world = make_world(40, 20, Biome.GRASS)
    grid = _draw(world, config, color=False)
    assert bool((grid.glyph != " ").all())


def test_ascii_mode_uses_the_ascii_column(config) -> None:
    world = make_world(3, 3, Biome.FOREST)
    grid = _draw(world, config, ascii_only=True, color=False)
    assert set(grid.glyph.ravel().tolist()) == {config.get("tables.biomes.forest.ascii")}


def test_cells_outside_the_world_stay_blank(config) -> None:
    world = make_world(2, 2)
    grid = build_grid(world, config, TERRAIN, Sampler.viewport(world, 2, 4))
    assert grid.glyph[0, 3] == " " and grid.bg[0, 3].tolist() == [0, 0, 0]


def test_scatter_is_stable_when_the_view_pans(config) -> None:
    # The glyph shown on a tile does not change when the viewport origin moves.
    world = make_world(40, 4, Biome.GRASS)
    whole = build_grid(world, config, TERRAIN, Sampler.viewport(world, 4, 40))
    panned = build_grid(world, config, TERRAIN, Sampler.viewport(world, 4, 30, x0=10.0))
    assert (whole.glyph[:, 10:] == panned.glyph).all()
