"""Tests for sampling a plan into a grid of another resolution."""

from __future__ import annotations

import numpy as np

from biomegen.sites.blit import sample_rect


def _plan() -> np.ndarray:
    return np.arange(36, dtype=np.uint8).reshape(6, 6)


def test_a_rect_of_the_plans_own_size_copies_it() -> None:
    rows, cols, values = sample_rect(_plan(), 2, 3, 6, 6, 20, 20)  # type: ignore[misc]
    assert (rows, cols) == (slice(2, 8), slice(3, 9)) and np.array_equal(values, _plan())


def test_a_larger_rect_repeats_plan_cells() -> None:
    _, _, values = sample_rect(_plan(), 0, 0, 12, 12, 12, 12)  # type: ignore[misc]
    assert np.array_equal(values[::2, ::2], _plan()) and np.array_equal(values[1::2, 1::2], _plan())


def test_a_smaller_rect_samples_every_other_cell() -> None:
    _, _, values = sample_rect(_plan(), 0, 0, 3, 3, 10, 10)  # type: ignore[misc]
    assert np.array_equal(values, _plan()[::2, ::2])


def test_a_rect_starting_off_the_grid_is_clipped() -> None:
    rows, cols, values = sample_rect(_plan(), -2, 3, 6, 6, 10, 10)  # type: ignore[misc]
    assert (rows, cols) == (slice(0, 4), slice(3, 9)) and np.array_equal(values, _plan()[2:, :])


def test_a_rect_overflowing_the_grid_is_clipped() -> None:
    rows, cols, values = sample_rect(_plan(), 0, 0, 6, 6, 4, 5)  # type: ignore[misc]
    assert (rows, cols) == (slice(0, 4), slice(0, 5)) and values.shape == (4, 5)


def test_a_rect_off_the_grid_gives_none() -> None:
    assert sample_rect(_plan(), 20, 0, 4, 4, 10, 10) is None


def test_an_empty_rect_gives_none() -> None:
    assert sample_rect(_plan(), 0, 0, 0, 4, 10, 10) is None
