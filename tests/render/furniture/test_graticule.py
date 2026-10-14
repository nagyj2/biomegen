"""Tests for the latitude and longitude tick labels."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.render.furniture.graticule import latitude_labels, longitude_labels
from biomegen.util.units import grid_scale

CONFIG = load_config(None)
# 240 x 60 cells over 6000 x 3000 km (25 x 50 km cells), centred on 30N 0E.
SCALE = grid_scale(240, 60, (6000.0, 3000.0), 30.0, 0.0)


def test_latitude_labels_name_the_northern_hemisphere() -> None:
    labels = latitude_labels(SCALE, 60, CONFIG, "°")
    assert labels and all(text.endswith("°N") for text in labels.values())


def test_latitude_labels_descend_down_the_map() -> None:
    labels = latitude_labels(SCALE, 60, CONFIG, "°")
    values = [int(labels[row].rstrip("°N")) for row in sorted(labels)]
    assert values == sorted(values, reverse=True)


def test_latitude_label_rows_are_inside_the_grid() -> None:
    assert all(0 <= row < 60 for row in latitude_labels(SCALE, 60, CONFIG, "°"))


def test_ascii_labels_have_no_degree_sign() -> None:
    labels = latitude_labels(SCALE, 60, CONFIG, "") | longitude_labels(SCALE, 240, CONFIG, "")
    assert all("°" not in text for text in labels.values())


def test_longitude_labels_cross_the_prime_meridian() -> None:
    texts = set(longitude_labels(SCALE, 240, CONFIG, "°").values())
    assert "0°" in texts and any(t.endswith("E") for t in texts) and any(t.endswith("W") for t in texts)


def test_longitude_ticks_keep_their_minimum_spacing() -> None:
    columns = sorted(longitude_labels(SCALE, 240, CONFIG, "°"))
    assert all(
        b - a >= CONFIG.get("render.furniture.lon_tick_cols") - 1 for a, b in zip(columns, columns[1:], strict=False)
    )
