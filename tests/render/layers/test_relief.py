"""Tests for the relief layer."""

from __future__ import annotations

from biomegen.render.layers import build_grid
from biomegen.render.views import View
from biomegen.sampling.sampler import Sampler
from biomegen.world.tile import Biome, Relief
from tests.render.conftest import make_world

VIEW = View("t", ("terrain", "relief"))


def _draw(world, config, **kwargs):
    return build_grid(world, config, VIEW, Sampler.viewport(world, world.height, world.width), **kwargs)


def test_relief_glyph_replaces_the_terrain_glyph(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.relief[1, 1] = int(Relief.MOUNTAIN)
    assert _draw(world, config).glyph[1, 1] == config.get("tables.relief.mountain.glyph")


def test_flat_cells_keep_the_terrain_glyph(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.relief[1, 1] = int(Relief.MOUNTAIN)
    assert _draw(world, config, color=False).glyph[0, 0] == config.get("tables.biomes.grass.glyph")


def test_cold_mountain_is_snow_capped(config) -> None:
    # Below the snow line temperature the mountain fill is lighter than on a warm mountain.
    world = make_world(3, 3, Biome.GRASS)
    world.relief[1, 1] = int(Relief.MOUNTAIN)
    world.temperature_c[:] = 15.0
    warm = int(_draw(world, config).bg[1, 1].sum())
    world.temperature_c[:] = -10.0
    assert int(_draw(world, config).bg[1, 1].sum()) > warm


def test_peak_fill_replaces_the_terrain_fill(config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.relief[1, 1] = int(Relief.PEAK)
    assert _draw(world, config).bg[1, 1].tolist() == config.get("render.relief_tints.peak.bg")


def test_water_cells_never_get_relief(config) -> None:
    world = make_world(3, 3, Biome.DEEP, -500.0)
    world.relief[1, 1] = int(Relief.PEAK)
    assert _draw(world, config, color=False).glyph[1, 1] == config.get("tables.biomes.deep.glyph")
