"""Tests for static rendering of a whole world."""

from __future__ import annotations

from biomegen.render.backends.plain import to_plain
from biomegen.render.colortest import color_test
from biomegen.render.static import render_static
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
