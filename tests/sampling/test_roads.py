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
    # An L of three road tiles: the diagonal between its ends would cut the corner, so only the two straight links draw
    # (with the corner rounding off, which would add slanting pieces of its own).
    world = make_world(2, 2)
    world.road[0, 0] = world.road[0, 1] = world.road[1, 1] = 1
    config = _config()
    config.data["render"]["road_smooth"] = 0.0
    found = road_bed(_sampler(world, config), world, config)
    assert found is not None and KIND_NAMES.index("falling") not in set(np.unique(found.kind[found.bed]))


# --- rounded corners -------------------------------------------------------------------------------------------------


def _bed(world, smooth: float, cell_w: int = 20, cell_h: int = 10):
    from biomegen.sampling.roads import road_bed

    config = _config()
    config.data["render"]["road_smooth"] = smooth
    sampler = DetailSampler(world, config, cell_w, cell_h, 0, 0, world.width, world.height)
    return road_bed(sampler, world, config), sampler


def _bend_world():
    """A 90 degree bend: road along row 2 from column 0 to 2, then down column 2 to row 4."""
    world = make_world(6, 6)
    world.road[2, 0:3] = 1
    world.road[3:5, 2] = 1
    return world


def _corner_cell(sampler):
    """The grid cell nearest the centre of tile (2, 2), the sharp corner."""
    distance = np.hypot(sampler.fx - 2.0, sampler.fy - 2.0)
    return np.unravel_index(int(np.argmin(distance)), distance.shape)


def test_a_sharp_corner_is_on_the_bed_when_rounding_is_off() -> None:
    found, sampler = _bed(_bend_world(), 0.0)
    assert found is not None and bool(found.bed[_corner_cell(sampler)])


def test_a_corner_is_cut_when_rounding_is_on() -> None:
    # The curve passes about a sixth of a tile from the corner tile's centre, outside the thin bed.
    found, sampler = _bed(_bend_world(), 1.0)
    assert found is not None and not bool(found.bed[_corner_cell(sampler)])


def test_a_rounded_corner_is_still_one_connected_road() -> None:
    from scipy import ndimage

    found, _ = _bed(_bend_world(), 1.0)
    assert found is not None and ndimage.label(found.bed, structure=np.ones((3, 3)))[1] == 1


def test_a_rounded_corner_stays_close_to_the_polyline() -> None:
    # Every bed cell lies within a third of a tile of the sharp polyline (the road never wanders far).
    found, sampler = _bed(_bend_world(), 1.0)
    assert found is not None
    points = [(0.0, 2.0), (2.0, 2.0), (2.0, 4.0)]
    distance = np.full(sampler.fx.shape, np.inf)
    for (ax, ay), (bx, by) in zip(points, points[1:], strict=False):
        dx, dy = bx - ax, by - ay
        t = np.clip(((sampler.fx - ax) * dx + (sampler.fy - ay) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        distance = np.minimum(distance, np.hypot(sampler.fx - (ax + t * dx), sampler.fy - (ay + t * dy)))
    assert float(distance[found.bed].max()) < 0.34


def test_a_rounded_corner_is_drawn_with_a_slanting_piece() -> None:
    found, _ = _bed(_bend_world(), 1.0)
    assert found is not None and {KIND_NAMES.index("rising"), KIND_NAMES.index("falling")} & set(
        np.unique(found.kind[found.bed]).tolist()
    )


def test_a_straight_road_is_the_same_with_or_without_rounding() -> None:
    world = make_world(6, 3)
    world.road[1, :] = 1
    sharp, _ = _bed(world, 0.0)
    round_, _ = _bed(world, 1.0)
    assert sharp is not None and round_ is not None and np.array_equal(sharp.bed, round_.bed)


def test_a_junction_stays_straight() -> None:
    # The tile where three roads meet is not rounded: the bed matches the unrounded one around it.
    world = make_world(5, 5)
    world.road[2, 1:4] = 1
    world.road[3, 2] = 1
    sharp, _ = _bed(world, 0.0)
    round_, _ = _bed(world, 1.0)
    assert sharp is not None and round_ is not None and np.array_equal(sharp.bed, round_.bed)


def test_a_staircase_of_tiles_reads_as_a_curve_not_steps() -> None:
    # Alternating east and south steps: rounded, so slanting pieces appear where the steps were.
    world = make_world(8, 8)
    for step in range(4):
        world.road[step * 2, step * 2 : step * 2 + 2] = 1
        world.road[step * 2 + 1 : step * 2 + 3, step * 2 + 1] = 1
    found, _ = _bed(world, 1.0)
    assert found is not None and (found.kind[found.bed] >= KIND_NAMES.index("rising")).any()


def test_rounding_above_one_is_treated_as_full_rounding() -> None:
    full, _ = _bed(_bend_world(), 1.0)
    over, _ = _bed(_bend_world(), 5.0)
    assert full is not None and over is not None and np.array_equal(full.bed, over.bed)


def test_links_leave_out_a_corner_cut() -> None:
    from biomegen.sampling.roads import _links

    road = np.zeros((3, 3), dtype=bool)
    road[0, 0] = road[0, 1] = road[1, 1] = True
    assert (1, 1) not in _links(road, 0, 0)


def test_links_keep_a_true_diagonal() -> None:
    from biomegen.sampling.roads import _links

    road = np.zeros((3, 3), dtype=bool)
    road[0, 0] = road[1, 1] = True
    assert _links(road, 0, 0) == [(1, 1)]


def test_piece_kinds_follow_their_slope() -> None:
    from biomegen.sampling.roads import _kind_of

    assert [_kind_of(1, 0), _kind_of(0, 1), _kind_of(1, -1), _kind_of(1, 1), _kind_of(1, 0.2), _kind_of(0.2, 1)] == [
        0,
        1,
        2,
        3,
        0,
        1,
    ]
