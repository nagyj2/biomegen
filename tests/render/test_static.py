"""Tests for static rendering of a whole world."""

from __future__ import annotations

from biomegen.render.backends.plain import to_plain
from biomegen.render.colortest import color_test
from biomegen.render.static import render_detail, render_static
from biomegen.world.tile import Biome
from tests.render.conftest import make_world


def _world():
    world = make_world(64, 24, Biome.DEEP, -2000.0)
    world.biome[6:18, 20:44] = int(Biome.GRASS)
    world.elevation_m[6:18, 20:44] = 150.0
    world.island_name = "Testland"
    return world


def test_grid_has_one_cell_per_tile(config) -> None:
    static = render_static(_world(), config)
    assert (static.grid.rows, static.grid.cols) == (24, 64)


def test_document_is_frame_plus_legend(config) -> None:
    with_legend = len(render_static(_world(), config).document)
    assert with_legend > len(render_static(_world(), config, legend=False).document) == 24 + 3


def test_legend_can_be_left_out(config) -> None:
    assert "LEGEND" not in to_plain(render_static(_world(), config, legend=False).document)


def test_ascii_static_render_is_pure_ascii(config) -> None:
    assert to_plain(render_static(_world(), config, ascii_only=True, color=False).document).isascii()


def test_labels_none_leaves_names_off(config) -> None:
    from tests.render.conftest import add_feature

    world = _world()
    add_feature(world, "sea", "Calm Sea", (8, 3))
    assert "Calm Sea" not in to_plain(render_static(world, config, labels="none", legend=False).document)


def test_unknown_view_is_a_key_error(config) -> None:
    import pytest

    with pytest.raises(KeyError, match="available"):
        render_static(_world(), config, "nope")


def test_every_default_view_renders(config) -> None:
    for name in config.get("render.views"):
        assert render_static(_world(), config, name).grid.rows == 24


def test_color_test_reports_the_detected_mode() -> None:
    assert "auto would choose: 256" in to_plain(color_test("256", {}))


def test_color_test_lists_the_environment() -> None:
    assert "COLORTERM=truecolor" in to_plain(color_test("truecolor", {"COLORTERM": "truecolor"}))


def test_detail_render_fills_whole_tiles_of_the_area(config) -> None:
    # A 120 x 36 area with 10 x 5 zoom cells holds 12 x 7 tiles: 120 columns by 35 rows.
    static = render_detail(_world(), config, "zoom", area=(120, 36))
    assert (static.grid.rows, static.grid.cols) == (35, 120)


def test_detail_render_is_the_bare_grid(config) -> None:
    # No frame, title or legend: the document has one line per grid row.
    static = render_detail(_world(), config, "local", area=(80, 24))
    assert len(static.document) == static.grid.rows


def test_detail_render_is_repeatable(config) -> None:
    first = to_plain(render_detail(_world(), config, "zoom", at=(30, 12), color=False).document)
    assert first == to_plain(render_detail(_world(), config, "zoom", at=(30, 12), color=False).document)


def test_detail_render_follows_the_chosen_tile(config) -> None:
    # Centring on the grassland or on the open sea gives different pictures.
    land = render_detail(_world(), config, "zoom", at=(32, 12), area=(60, 20)).grid
    sea = render_detail(_world(), config, "zoom", at=(2, 2), area=(60, 20)).grid
    assert not (land.glyph == sea.glyph).all()


def test_ascii_detail_render_is_pure_ascii(config) -> None:
    assert to_plain(render_detail(_world(), config, "local", ascii_only=True, color=False).document).isascii()


def test_data_view_works_at_detail_scale(config) -> None:
    # The elevation ramp tints a zoomed view of a coast; land and sea get different fills.
    grid = render_detail(_world(), config, "zoom", "elevation", at=(20, 12), area=(60, 20)).grid
    assert len({tuple(rgb) for rgb in grid.bg.reshape(-1, 3).tolist()}) > 3
