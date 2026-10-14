"""Tests for the scale bar."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.render.furniture.scalebar import scale_bar
from biomegen.util.units import grid_scale

CONFIG = load_config(None)
SCALE = grid_scale(240, 60, (6000.0, 3000.0), 30.0, 0.0)


def test_scale_bar_names_a_configured_length() -> None:
    bar = scale_bar(SCALE, 240, CONFIG, ascii_only=False)
    assert int(bar.split("┤")[1].split(" km")[0]) in CONFIG.get("render.furniture.scale_km")


def test_scale_bar_is_about_a_sixth_of_the_map() -> None:
    # 240 columns / 6 = 40 columns; the bar's interior spans that many within one nice length.
    bar = scale_bar(SCALE, 240, CONFIG, ascii_only=True)
    assert 30 <= len(bar.strip().split(" ")[0]) <= 50


def test_ascii_bar_uses_only_ascii() -> None:
    assert scale_bar(SCALE, 240, CONFIG, ascii_only=True).isascii()
