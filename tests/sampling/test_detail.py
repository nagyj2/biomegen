"""Tests for the detail sampler: zoom and local cells read the world through one continuous, warped field."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.detail import (
    SCALE_LOCAL,
    SCALE_ZOOM,
    DetailSampler,
    centre_camera,
    detail_cell_size,
    detail_sampler,
)
from biomegen.world.tile import Biome
from tests.render.conftest import make_world


def _crisp_config() -> Config:
    config = load_config(None)
    config.data["render"]["blend_strength"] = 0.0
    return config


def _patchwork_world(width: int = 8, height: int = 6):
    """A world of grass, forest, desert and lake tiles in a fixed pseudo-random pattern."""
    world = make_world(width, height)
    pattern = np.random.default_rng(5).integers(0, 4, size=(height, width))
    world.biome[:] = np.array([int(Biome.GRASS), int(Biome.FOREST), int(Biome.DESERT), int(Biome.LAKE)])[pattern]
    return world


def test_zoom_cells_are_aspect_corrected(config: Config) -> None:
    # Zoom height is render.zoom_scale; width is widened by render.cell_aspect.
    assert detail_cell_size(SCALE_ZOOM, config, 120, 36) == (10, 5)


def test_local_cell_height_fits_the_configured_tile_rows(config: Config) -> None:
    # Local picks a height so render.local_rows tiles fill the area's height.
    assert detail_cell_size(SCALE_LOCAL, config, 120, 36) == (18, 9)


def test_grid_holds_whole_tiles_only(config: Config) -> None:
    # A 125 x 37 area with 10 x 5 cells fits 12 x 7 tiles: 120 columns by 35 rows.
    sampler = detail_sampler(make_world(30, 20), config, SCALE_ZOOM, 125, 37, 0, 0)
    assert (sampler.cols, sampler.rows) == (120, 35)


def test_each_cell_block_reads_its_own_tile_without_warp() -> None:
    # With the warp off, every cell of a tile's block reads that tile (nearest lookup).
    world = make_world(4, 3)
    world.elevation_m[:] = np.arange(12).reshape(3, 4)
    sampler = DetailSampler(world, _crisp_config(), 10, 5, 0, 0, 4, 3)
    assert (sampler.nearest(world.elevation_m)[::5, ::10] == world.elevation_m).all()


def test_sub_indices_count_cells_inside_a_tile() -> None:
    # sub_x runs 0..cell_w-1 across each block; sub_y runs 0..cell_h-1 down it.
    world = make_world(3, 3)
    sampler = DetailSampler(world, _crisp_config(), 4, 2, 0, 0, 3, 3)
    assert (sampler.sub_x[0].tolist(), sampler.sub_y[:, 0].tolist()) == ([0, 1, 2, 3] * 3, [0, 1] * 3)


def test_cells_outside_the_world_are_not_inside() -> None:
    # A camera hanging off the top-left leaves the first block of cells outside the world.
    world = make_world(4, 4)
    sampler = DetailSampler(world, _crisp_config(), 2, 1, -1, -1, 3, 3)
    assert sampler.inside[:, :2].sum() == 0


def test_cell_of_gives_the_centre_cell_of_the_tile_block() -> None:
    # Tile (3, 2) seen from camera (1, 1) with 10 x 5 cells has its block at cols 20-29, rows 5-9.
    world = make_world(8, 6)
    assert DetailSampler(world, _crisp_config(), 10, 5, 1, 1, 6, 4).cell_of(3, 2) == (25, 7)


def test_cell_of_is_none_off_the_grid() -> None:
    world = make_world(8, 6)
    assert DetailSampler(world, _crisp_config(), 10, 5, 1, 1, 2, 2).cell_of(7, 5) is None


def test_zoom_and_local_agree_at_the_same_world_position(config: Config) -> None:
    # Cell c of a 10 x 5 grid and cell 3c+1 of a 30 x 15 grid sit at the same world position, so the
    # blended biome there must be identical: the warp is a function of position, not of the scale.
    world = _patchwork_world()
    zoom = DetailSampler(world, config, 10, 5, 0, 0, 8, 6).biome()
    local = DetailSampler(world, config, 30, 15, 0, 0, 8, 6).biome()
    assert (local[1::3, 1::3] == zoom).all()


def test_warp_moves_some_biome_borders(config: Config) -> None:
    # The blend is real: a patchwork world reads differently with the warp on and off.
    world = _patchwork_world()
    warped = DetailSampler(world, config, 10, 5, 0, 0, 8, 6).biome()
    crisp = DetailSampler(world, _crisp_config(), 10, 5, 0, 0, 8, 6).biome()
    assert (warped != crisp).any()


def test_diagonal_water_tiles_join() -> None:
    # Two lake tiles touching at a corner give the cell between them water (coverage over the threshold).
    world = make_world(2, 2)
    world.biome[0, 0] = world.biome[1, 1] = int(Biome.LAKE)
    biome = DetailSampler(world, _crisp_config(), 10, 5, 0, 0, 2, 2).biome()
    assert biome[4, 9] == int(Biome.LAKE)


def test_water_coverage_does_not_flood_land_far_from_water() -> None:
    # The far corner of a land tile beside a lake tile stays land.
    world = make_world(3, 1)
    world.biome[0, 0] = int(Biome.LAKE)
    biome = DetailSampler(world, _crisp_config(), 10, 5, 0, 0, 3, 1).biome()
    assert biome[2, 29] == int(Biome.GRASS)


@pytest.mark.parametrize("scale", [SCALE_ZOOM, SCALE_LOCAL])
def test_biome_is_deterministic(config: Config, scale: str) -> None:
    # The same world and camera give the same blended biome twice.
    world = _patchwork_world()
    first = detail_sampler(world, config, scale, 60, 20, 0, 0).biome()
    second = detail_sampler(world, config, scale, 60, 20, 0, 0).biome()
    assert (first == second).all()


@pytest.mark.parametrize(
    ("tile", "tiles", "world_size", "first"),
    [(30, 12, 64, 24), (0, 12, 64, 0), (63, 12, 64, 52), (2, 12, 6, -3)],
)
def test_camera_centres_the_tile_and_stays_in_the_world(tile: int, tiles: int, world_size: int, first: int) -> None:
    # Centred in the middle, clamped at either edge, and a small world is centred in the window.
    assert centre_camera(tile, tiles, world_size) == first
