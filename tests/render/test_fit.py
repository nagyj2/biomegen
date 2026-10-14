"""Tests for the fit-to-screen sampler: a cell shows the most salient tile of its block."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.render.fit import FitSampler, fit_blocks, tile_priority
from biomegen.world.tile import Biome, Relief, WaterType
from tests.render.conftest import make_world


def test_blocks_are_the_smallest_that_fit_the_area() -> None:
    # A 240 x 60 world in a 100 x 40 area needs 3 x 2 tile blocks, giving 80 x 30 cells.
    assert fit_blocks(240, 60, 100, 40) == (3, 2, 80, 30)


def test_a_world_smaller_than_the_area_is_one_to_one() -> None:
    assert fit_blocks(40, 20, 100, 40) == (1, 1, 40, 20)


def test_a_cell_shows_the_highest_priority_tile_of_its_block(config: Config) -> None:
    # A lone lake among grass in a 2 x 2 block wins over the grass (lake 75 against grass 30).
    world = make_world(4, 4, Biome.GRASS)
    world.biome[1, 1] = int(Biome.LAKE)
    sampler = FitSampler(world, config, 2, 2)
    assert (int(sampler.tile_x[0, 0]), int(sampler.tile_y[0, 0])) == (1, 1)


def test_a_road_beats_plain_land(config: Config) -> None:
    world = make_world(4, 4, Biome.FOREST)
    world.road[1, 0] = 1
    sampler = FitSampler(world, config, 2, 2)
    assert (int(sampler.tile_x[0, 0]), int(sampler.tile_y[0, 0])) == (0, 1)


def test_a_poi_beats_a_road(config: Config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    world.road[0, 0] = 1
    world.poi_index[1, 1] = 0
    sampler = FitSampler(world, config, 2, 2)
    assert (int(sampler.tile_x[0, 0]), int(sampler.tile_y[0, 0])) == (1, 1)


def test_ties_take_the_first_tile_in_reading_order(config: Config) -> None:
    sampler = FitSampler(make_world(4, 4, Biome.GRASS), config, 2, 2)
    assert (int(sampler.tile_x[1, 1]), int(sampler.tile_y[1, 1])) == (2, 2)


def test_mountain_relief_outranks_its_biome(config: Config) -> None:
    # Mountains are relief: a mountain tile among grass is salient (60 against 30).
    world = make_world(4, 4, Biome.GRASS)
    world.relief[0, 1] = int(Relief.MOUNTAIN)
    assert int(tile_priority(world, config)[0, 1]) == 60


def test_a_river_counts_as_salient_water(config: Config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    world.water_type[2, 2] = int(WaterType.FRESH)
    assert int(tile_priority(world, config)[2, 2]) == 75


def test_cell_of_maps_a_tile_to_its_block(config: Config) -> None:
    sampler = FitSampler(make_world(240, 60), config, 100, 40)
    assert sampler.cell_of(7, 5) == (2, 2)


def test_partial_edge_blocks_pick_a_real_tile(config: Config) -> None:
    # A 5 x 5 world in 2 x 2 blocks has a ragged last block; its chosen tile must lie inside the world.
    sampler = FitSampler(make_world(5, 5, Biome.GRASS), config, 3, 3)
    assert bool(sampler.inside.all()) and int(sampler.tile_x.max()) <= 4


def test_every_cell_reads_a_tile_inside_its_block(config: Config) -> None:
    world = make_world(20, 10, Biome.GRASS)
    world.road[3, 7] = 1
    sampler = FitSampler(world, config, 7, 4)
    cols = np.arange(sampler.cols)[np.newaxis, :]
    rows = np.arange(sampler.rows)[:, np.newaxis]
    inside_block = (sampler.tile_x // sampler.block_w == cols) & (sampler.tile_y // sampler.block_h == rows)
    assert bool(inside_block.all())
