"""Tests for site geometry: extents, windows, plan resolution and which tiles a site covers."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites.geometry import SiteGeometry, site_geometry
from biomegen.world.entities import POI


@pytest.fixture(scope="module")
def cfg() -> Config:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _poi(kind: str, x: int = 10, y: int = 8, pop: int = 0) -> POI:
    return POI(kind=kind, x=x, y=y, interior_seed=7, pop=pop)


def _geometry(config: Config, kind: str, **kwargs: int) -> SiteGeometry:
    geometry = site_geometry(_poi(kind, **kwargs), config)
    assert geometry is not None
    return geometry


def test_kind_without_a_site_row_has_no_geometry(cfg: Config) -> None:
    assert site_geometry(_poi("bridge"), cfg) is None


def test_extent_is_centred_on_the_anchor(cfg: Config) -> None:
    # A village is 1.5 x 1.25 tiles, so its extent runs half that either side of tile (10, 8).
    assert _geometry(cfg, "village").extent == (9.25, 7.375, 10.75, 8.625)


def test_a_tower_is_smaller_than_one_tile(cfg: Config) -> None:
    left, top, right, bottom = _geometry(cfg, "tower").extent
    assert right - left < 1.0 and bottom - top < 1.0


def test_a_capital_spans_several_tiles(cfg: Config) -> None:
    left, top, right, bottom = _geometry(cfg, "capital").extent
    assert right - left > 2.0 and bottom - top > 1.0


def test_plan_cells_are_widened_by_the_cell_aspect(cfg: Config) -> None:
    # 20 rows per tile and an aspect of 2 give 40 columns per tile, so a tile stays square on screen.
    geometry = _geometry(cfg, "village")
    assert (geometry.cell_w, geometry.cell_h) == (40, 20)


def test_window_holds_the_extent_and_its_margin(cfg: Config) -> None:
    geometry = _geometry(cfg, "village")
    left, top, right, bottom = geometry.extent
    margin = cfg.get("sites.margin_tiles")
    assert geometry.cam_x - 0.5 <= left - margin and right + margin <= geometry.cam_x + geometry.tiles_w - 0.5
    assert geometry.cam_y - 0.5 <= top - margin and bottom + margin <= geometry.cam_y + geometry.tiles_h - 0.5


def test_box_lies_inside_the_window(cfg: Config) -> None:
    geometry = _geometry(cfg, "city")
    col0, row0, col1, row1 = geometry.box
    assert 0 <= col0 < col1 <= geometry.cols and 0 <= row0 < row1 <= geometry.rows


def test_box_size_follows_the_extent_and_resolution(cfg: Config) -> None:
    # A village extent of 1.5 x 1.25 tiles at 40 x 20 cells per tile is 60 x 25 cells.
    geometry = _geometry(cfg, "village")
    assert (geometry.box_cols, geometry.box_rows) == (60, 25)


def test_cell_at_and_position_of_are_inverse(cfg: Config) -> None:
    geometry = _geometry(cfg, "town")
    x, y = geometry.position_of(17, 9)
    assert geometry.cell_at(x, y) == (17, 9)


def test_a_sub_tile_site_covers_only_its_own_tile(cfg: Config) -> None:
    geometry = _geometry(cfg, "tower")
    assert geometry.covers_tile(10, 8) and not geometry.covers_tile(11, 8) and not geometry.covers_tile(10, 9)


def test_a_wide_site_covers_neighbouring_tiles(cfg: Config) -> None:
    geometry = _geometry(cfg, "capital")
    assert geometry.covers_tile(9, 8) and geometry.covers_tile(11, 8) and not geometry.covers_tile(13, 8)


def test_population_does_not_change_a_settlements_extent(cfg: Config) -> None:
    # The extent follows the potential, so a town that grows draws on the same ground.
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    lo, hi = config.get("tables.tiers.town.pop")
    assert site_geometry(_poi("town", pop=lo), config) == site_geometry(_poi("town", pop=hi), config)


def test_a_settlements_extent_follows_its_potential(cfg: Config) -> None:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    village, town = _poi("village"), _poi("village")
    town.potential = "town"
    small, large = site_geometry(village, config), site_geometry(town, config)
    assert small is not None and large is not None and large.box_cols > small.box_cols


def test_jitter_is_seeded_per_poi() -> None:
    config = load_config(None)
    first, second = site_geometry(_poi("camp"), config), site_geometry(_poi("camp"), config)
    assert first == second


def test_extent_too_small_for_a_plan_gives_none(cfg: Config) -> None:
    config = load_config(None)
    config.data["tables"]["sites"]["camp"]["extent_tiles"] = [0.01, 0.01]
    assert site_geometry(_poi("camp"), config) is None
