"""Tests for the noise utilities (backends, fBm, domain warp, normalisation)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.util import noise


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
