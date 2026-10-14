"""Tests for the framed static map."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.render.backends.plain import to_plain
from biomegen.render.furniture.frame import build_frame, title_text
from biomegen.render.grid import CellGrid
from biomegen.util.units import grid_scale
from biomegen.world.world import World

CONFIG = load_config(None)


def _world() -> World:
    world = World(240, 60, 77, grid_scale(240, 60, (6000.0, 3000.0), 30.0, 0.0))
    world.island_name = "Testland"
    world.terrain_style = "archipelago"
    return world


def test_title_names_the_world_and_seed() -> None:
    assert "Testland" in title_text(_world(), CONFIG, False) and "seed 77" in title_text(_world(), CONFIG, False)


def test_title_reports_the_map_size_in_km() -> None:
    assert "6,000 x 3,000 km" in title_text(_world(), CONFIG, True)


def test_frame_has_a_title_line_the_rows_and_two_footer_lines() -> None:
    document = build_frame(_world(), CONFIG, CellGrid(60, 240))
    assert len(document) == 60 + 3


def test_every_frame_line_has_the_same_width() -> None:
    lines = to_plain(build_frame(_world(), CONFIG, CellGrid(60, 240))).split("\n")
    margin = CONFIG.get("render.furniture.margin")
    assert {len(line) for line in lines[:-1]} == {margin + 240 + 2}


def test_unicode_frame_uses_box_drawing_borders() -> None:
    first = to_plain(build_frame(_world(), CONFIG, CellGrid(60, 240))).split("\n")[0]
    assert "╔" in first and "╗" in first


def test_ascii_frame_is_pure_ascii() -> None:
    assert to_plain(build_frame(_world(), CONFIG, CellGrid(60, 240), ascii_only=True)).isascii()


def test_frame_title_line_carries_the_scale_bar() -> None:
    assert "km" in to_plain(build_frame(_world(), CONFIG, CellGrid(60, 240))).split("\n")[0]


def test_longitude_tick_marks_sit_in_the_bottom_border() -> None:
    lines = to_plain(build_frame(_world(), CONFIG, CellGrid(60, 240))).split("\n")
    assert "╧" in lines[-2]
