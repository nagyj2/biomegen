"""Tests for the km-true scale model (cell size, aspect, conversions, lat/lon placement)."""

from __future__ import annotations

import math

import pytest

from biomegen.util.units import KM_PER_DEGREE, grid_scale


def test_cell_size_is_extent_over_grid() -> None:
    # A 6000x3000 km map on a 200x50 grid has 30 km columns and 60 km rows.
    scale = grid_scale(200, 50, (6000.0, 3000.0), 0.0, 0.0)
    assert (scale.km_per_col, scale.km_per_row) == (30.0, 60.0)


def test_aspect_and_area_follow_cell_size() -> None:
    # Aspect is row km over column km; area is their product.
    scale = grid_scale(200, 50, (6000.0, 3000.0), 0.0, 0.0)
    assert scale.aspect == 2.0
    assert scale.cell_area_km2 == 1800.0


def test_sampling_is_row_then_column() -> None:
    # The numpy distance-transform order is [y, x], so rows come first.
    scale = grid_scale(200, 50, (6000.0, 3000.0), 0.0, 0.0)
    assert scale.sampling == (60.0, 30.0)


def test_km_conversions_invert_cell_size() -> None:
    # 90 km is three 30 km columns, one and a half 60 km rows, and 3600 km² is two 1800 km² cells.
    scale = grid_scale(200, 50, (6000.0, 3000.0), 0.0, 0.0)
    assert scale.km_to_cols(90.0) == 3.0
    assert scale.km_to_rows(90.0) == 1.5
    assert scale.area_to_cells(3600.0) == 2.0


def test_distance_km_weights_each_axis() -> None:
    # One row step is twice as long as one column step on a 2:1 grid.
    scale = grid_scale(200, 50, (6000.0, 3000.0), 0.0, 0.0)
    assert scale.distance_km(0, 0, 1, 0) == 30.0
    assert scale.distance_km(0, 0, 0, 1) == 60.0
    assert scale.distance_km(0, 0, 4, 2) == pytest.approx(math.hypot(120.0, 120.0))


def test_latitude_is_centred_and_decreases_downwards() -> None:
    # Row centres are symmetric about the centre latitude, north at the top.
    scale = grid_scale(10, 10, (1000.0, 1000.0), 20.0, 0.0)
    assert scale.lat_of_row(0) > scale.lat_of_row(9)
    assert (scale.lat_of_row(4) + scale.lat_of_row(5)) / 2 == pytest.approx(20.0)


def test_lat_top_is_half_the_span_above_centre() -> None:
    # The top edge sits half the map height (in degrees) above the centre.
    scale = grid_scale(10, 10, (1000.0, 1000.0), 20.0, 0.0)
    assert scale.lat_top == pytest.approx(20.0 + 500.0 / KM_PER_DEGREE)


def test_centre_latitude_is_clamped_inside_the_poles() -> None:
    # A centre at 90 degrees is pulled back so the top edge stays at 89 degrees.
    scale = grid_scale(10, 10, (1000.0, 2000.0), 90.0, 0.0)
    assert scale.lat_top == pytest.approx(89.0)


def test_longitude_is_centred_on_center_lon() -> None:
    # Column centres are symmetric about the centre longitude.
    scale = grid_scale(10, 10, (1000.0, 1000.0), 0.0, 40.0)
    assert (scale.lon_of_col(4) + scale.lon_of_col(5)) / 2 == pytest.approx(40.0)


def test_degrees_of_longitude_widen_with_latitude() -> None:
    # The same km span covers more degrees of longitude at 60 degrees than at the equator.
    equator = grid_scale(10, 10, (1000.0, 1000.0), 0.0, 0.0)
    north = grid_scale(10, 10, (1000.0, 1000.0), 60.0, 0.0)
    assert north.deg_lon_per_km == pytest.approx(2 * equator.deg_lon_per_km, rel=1e-3)


def test_longitude_wraps_at_the_antimeridian() -> None:
    # A map centred on 180 degrees reports its right half as negative (western) longitudes.
    scale = grid_scale(10, 10, (1000.0, 1000.0), 0.0, 180.0)
    assert -180.0 <= scale.lon_of_col(9) < 0.0


@pytest.mark.parametrize("size_km", [(0.0, 100.0), (100.0, -1.0)])
def test_non_positive_extent_is_rejected(size_km: tuple[float, float]) -> None:
    # A zero or negative extent has no cell size.
    with pytest.raises(ValueError):
        grid_scale(10, 10, size_km, 0.0, 0.0)


def test_non_positive_grid_is_rejected() -> None:
    # A grid with no columns has no cell size.
    with pytest.raises(ValueError):
        grid_scale(0, 10, (100.0, 100.0), 0.0, 0.0)
