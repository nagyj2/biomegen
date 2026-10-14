"""Tests for the noise utilities (backends, fBm, domain warp, normalisation)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.util import noise
from biomegen.util.units import grid_scale


def test_default_perlin_backend_registered() -> None:
    assert "perlin" in noise.NOISE_BACKENDS.names()
    assert "value" in noise.NOISE_BACKENDS.names()


def test_perlin_is_deterministic_for_same_seed() -> None:
    cx, cy = noise.coordinate_grid((32, 48), scale=16.0)
    a = noise.fbm(noise.get_sampler("perlin", 123), cx, cy, octaves=4, persistence=0.5, lacunarity=2.0)
    b = noise.fbm(noise.get_sampler("perlin", 123), cx, cy, octaves=4, persistence=0.5, lacunarity=2.0)
    assert np.array_equal(a, b)


def test_perlin_differs_for_different_seed() -> None:
    cx, cy = noise.coordinate_grid((32, 48), scale=16.0)
    a = noise.fbm(noise.get_sampler("perlin", 1), cx, cy, octaves=4, persistence=0.5, lacunarity=2.0)
    b = noise.fbm(noise.get_sampler("perlin", 2), cx, cy, octaves=4, persistence=0.5, lacunarity=2.0)
    assert not np.array_equal(a, b)


def test_fbm_output_is_bounded_and_normalises_to_unit_range() -> None:
    cx, cy = noise.coordinate_grid((40, 40), scale=12.0)
    field = noise.fbm(noise.get_sampler("perlin", 7), cx, cy, octaves=5, persistence=0.5, lacunarity=2.0)
    # fBm is normalised by total amplitude -> stays comfortably within [-1.5, 1.5].
    assert field.min() > -1.5 and field.max() < 1.5
    norm = noise.normalize01(field)
    assert abs(norm.min()) < 1e-9 and abs(norm.max() - 1.0) < 1e-9


def test_coordinate_grid_axis_scaling() -> None:
    # Larger scale_x stretches features along X -> coordinates change more slowly across columns.
    cx1, _ = noise.coordinate_grid((4, 4), scale=10.0, scale_x=1.0)
    cx2, _ = noise.coordinate_grid((4, 4), scale=10.0, scale_x=2.0)
    span1 = cx1[0, -1] - cx1[0, 0]
    span2 = cx2[0, -1] - cx2[0, 0]
    assert span2 < span1


def test_km_grid_has_equal_km_spacing_on_both_axes() -> None:
    # 6000x3000 km over 60x10 cells: 100 km columns, 300 km rows -> one row step is 3x a column step.
    scale = grid_scale(60, 10, (6000.0, 3000.0), 0.0, 0.0)
    cx, cy = noise.km_grid((10, 60), scale, feature_km=100.0)
    assert np.isclose(cx[0, 1] - cx[0, 0], 1.0)
    assert np.isclose(cy[1, 0] - cy[0, 0], 3.0)


def test_km_grid_samples_cell_centres() -> None:
    # The first cell's centre sits half a cell from the map origin.
    scale = grid_scale(10, 10, (1000.0, 1000.0), 0.0, 0.0)
    cx, cy = noise.km_grid((10, 10), scale, feature_km=100.0)
    assert np.isclose(cx[0, 0], 0.5) and np.isclose(cy[0, 0], 0.5)


def test_ridged_is_within_unit_range() -> None:
    cx, cy = noise.coordinate_grid((40, 40), scale=8.0)
    field = noise.ridged(noise.get_sampler("perlin", 3), cx, cy, octaves=4)
    assert field.min() >= 0.0 and field.max() <= 1.0


def test_ridged_crests_where_base_noise_crosses_zero() -> None:
    # Perlin is exactly 0 on integer lattice points, so a one-octave ridged field is 1 there.
    xs = np.arange(5, dtype=np.float64).reshape(1, 5)
    ys = np.zeros_like(xs)
    field = noise.ridged(noise.get_sampler("perlin", 9), xs, ys, octaves=1)
    assert np.allclose(field, 1.0)


def test_belt_lines_cover_a_minority_of_the_map() -> None:
    # Belts are thin bands along zero-crossings, not a general uplift.
    cx, cy = noise.coordinate_grid((80, 160), scale=40.0)
    belts = noise.belt_lines(noise.get_sampler("perlin", 11), cx, cy, width=0.09)
    assert belts.min() >= 0.0 and belts.max() <= 1.0
    assert 0.0 < (belts > 0).mean() < 0.5


def test_belt_lines_widen_with_width() -> None:
    cx, cy = noise.coordinate_grid((80, 160), scale=40.0)
    sampler = noise.get_sampler("perlin", 11)
    narrow = noise.belt_lines(sampler, cx, cy, width=0.05)
    wide = noise.belt_lines(sampler, cx, cy, width=0.2)
    assert (wide > 0).sum() > (narrow > 0).sum()


def test_domain_warp_changes_the_field_but_stays_deterministic() -> None:
    cx, cy = noise.coordinate_grid((30, 30), scale=10.0)
    sampler = noise.get_sampler("perlin", 5)
    warp = noise.get_sampler("perlin", 6)
    plain = noise.fbm(sampler, cx, cy, octaves=3, persistence=0.5, lacunarity=2.0)
    wx, wy = noise.domain_warp(warp, cx, cy, strength=0.5)
    warped = noise.fbm(sampler, wx, wy, octaves=3, persistence=0.5, lacunarity=2.0)
    assert not np.array_equal(plain, warped)
    # Re-running the warp with the same seeds reproduces it exactly.
    wx2, wy2 = noise.domain_warp(noise.get_sampler("perlin", 6), cx, cy, strength=0.5)
    assert np.array_equal(wx, wx2) and np.array_equal(wy, wy2)


def test_opensimplex_backend_runs_and_is_deterministic() -> None:
    cx, cy = noise.coordinate_grid((16, 16), scale=8.0)
    a = noise.get_sampler("opensimplex", 42)(cx, cy)
    b = noise.get_sampler("opensimplex", 42)(cx, cy)
    assert a.shape == (16, 16)
    assert np.array_equal(a, b)


def test_unknown_backend_raises() -> None:
    with pytest.raises(KeyError):
        noise.get_sampler("does-not-exist", 1)
