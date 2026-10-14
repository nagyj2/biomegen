"""Tests for the land and river masks shared by the layers and the site plans."""

from __future__ import annotations

from biomegen.config.model import Config
from biomegen.sampling.detail import DetailSampler
from biomegen.sampling.sampler import Sampler
from biomegen.sampling.terrain import land_mask, river_mask, water_biomes
from biomegen.world.tile import Biome, WaterType
from tests.render.conftest import make_world


def test_water_biomes_flags_the_water_covers(config: Config) -> None:
    water = water_biomes(config)
    assert water[int(Biome.LAKE)] and water[int(Biome.DEEP)] and not water[int(Biome.GRASS)]


def test_land_mask_excludes_lake_cells(config: Config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.biome[1, 1] = int(Biome.LAKE)
    sampler = Sampler.viewport(world, 3, 3)
    land = land_mask(sampler, sampler.biome(), water_biomes(config))
    assert not land[1, 1] and land[0, 0]


def test_river_mask_covers_fresh_water_over_a_land_biome(config: Config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    world.water_type[1, :] = int(WaterType.FRESH)
    sampler = Sampler.viewport(world, 3, 3)
    water = water_biomes(config)
    river = river_mask(sampler, world, land_mask(sampler, sampler.biome(), water), water)
    assert river[1].all() and not river[0].any()


def test_river_mask_is_smoothed_at_the_detail_scales(config: Config) -> None:
    # A diagonal river of two corner-touching tiles stays one connected stream in the detail cells.
    world = make_world(2, 2, Biome.GRASS)
    world.water_type[0, 0] = world.water_type[1, 1] = int(WaterType.FRESH)
    sampler = DetailSampler(world, config, 10, 5, 0, 0, 2, 2)
    water = water_biomes(config)
    river = river_mask(sampler, world, land_mask(sampler, sampler.biome(), water), water)
    assert river[4, 9] or river[5, 10]  # a cell between the two tile centres is river
