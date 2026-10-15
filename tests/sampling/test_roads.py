"""Tests for the road bed: one rasterisation of the road links that every grid shares."""

from __future__ import annotations

import numpy as np

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sampling.detail import DetailSampler
from biomegen.sampling.roads import KIND_LONE, KIND_NAMES, bed_half_width, road_bed
from tests.render.conftest import make_world


def _config() -> Config:
    config = load_config(None)
    config.data["render"]["road_warp"] = 0.0
    return config


def _sampler(world, config: Config, cell_w: int = 8, cell_h: int = 4) -> DetailSampler:
    return DetailSampler(world, config, cell_w, cell_h, 0, 0, 6, 3)


def test_a_world_without_roads_has_no_bed() -> None:
    world = make_world(6, 3)
    assert road_bed(_sampler(world, _config()), world, _config()) is None


def test_a_horizontal_road_is_a_band_of_horizontal_cells() -> None:
    world = make_world(6, 3)
    world.road[1, :] = 1
    config = _config()
    found = road_bed(_sampler(world, config), world, config)
    assert found is not None and set(np.unique(found.kind[found.bed])) == {KIND_NAMES.index("horizontal")}


def test_the_bed_is_thin_next_to_the_tile() -> None:
    world = make_world(6, 3)
    world.road[1, :] = 1
    config = _config()
    sampler = _sampler(world, config)
    found = road_bed(sampler, world, config)
    assert found is not None and found.bed.any(axis=1).sum() <= max(2, round(sampler.cell_h * 0.5))


def test_a_lone_road_tile_is_a_disc() -> None:
    world = make_world(6, 3)
    world.road[1, 2] = 1
    config = _config()
    found = road_bed(_sampler(world, config, 40, 20), world, config)
    assert found is not None and (found.kind[found.bed] == KIND_LONE).all()


def test_the_bed_is_never_thinner_than_the_minimum_rows() -> None:
    world = make_world(6, 3)
    world.road[1, :] = 1
    config = _config()
    config.data["render"]["road_min_rows"] = 3.0
    sampler = _sampler(world, config, 4, 2)
    assert bed_half_width(config, sampler) * sampler.cell_h * 2 >= 3.0


def test_a_coarser_grid_shows_the_same_road_over_the_same_ground() -> None:
    # The road's centre is the same world position at both resolutions: both beds are centred on the road tile's row.
    world = make_world(6, 3)
    world.road[1, :] = 1
    config = _config()
    centres = []
    for cell_h in (4, 8):
        sampler = _sampler(world, config, cell_h * 2, cell_h)
        found = road_bed(sampler, world, config)
        assert found is not None
        rows = np.nonzero(found.bed.any(axis=1))[0]
        centres.append((rows.min() + rows.max() + 1) / 2 / cell_h)
    assert abs(centres[0] - centres[1]) < 0.15


def test_a_diagonal_link_across_water_corners_is_kept() -> None:
    # Two land road tiles joined across the corner of two river tiles: the diagonal is the only link, so it is drawn.
    world = make_world(2, 2)
    world.road[0, 0] = world.road[1, 1] = 1
    world.water_type[0, 1] = world.water_type[1, 0] = 2
    config = _config()
    found = road_bed(_sampler(world, config), world, config)
    assert found is not None and KIND_NAMES.index("falling") in set(np.unique(found.kind[found.bed]))


def test_a_diagonal_link_is_left_out_when_an_orthogonal_corner_is_road() -> None:
    # An L of three road tiles: the diagonal between its ends would cut the corner, so only the two straight links draw.
    world = make_world(2, 2)
    world.road[0, 0] = world.road[0, 1] = world.road[1, 1] = 1
    config = _config()
    found = road_bed(_sampler(world, config), world, config)
    assert found is not None and KIND_NAMES.index("falling") not in set(np.unique(found.kind[found.bed]))
