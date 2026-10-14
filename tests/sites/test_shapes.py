"""Tests for structure outlines."""

from __future__ import annotations

import random

import numpy as np
import pytest
from scipy import ndimage

from biomegen.sites.shapes import MIXED, SHAPES, outline

COLS, ROWS = 54, 18


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_every_shape_is_one_connected_piece(name: str) -> None:
    mask = SHAPES[name](random.Random(3), COLS, ROWS)
    assert ndimage.label(mask)[1] == 1


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_every_shape_keeps_a_one_cell_border_free(name: str) -> None:
    mask = SHAPES[name](random.Random(3), COLS, ROWS)
    assert not (mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_every_shape_is_deterministic(name: str) -> None:
    assert np.array_equal(SHAPES[name](random.Random(5), COLS, ROWS), SHAPES[name](random.Random(5), COLS, ROWS))


def test_mixed_never_picks_the_plain_rectangle() -> None:
    rectangle = SHAPES["rectangle"](random.Random(0), COLS, ROWS)
    shapes = [outline(MIXED, random.Random(seed), COLS, ROWS, 10) for seed in range(12)]
    assert not any(np.array_equal(shape, rectangle) for shape in shapes)


def test_a_shape_too_small_falls_back_to_the_rectangle() -> None:
    mask = outline("diamond", random.Random(1), COLS, ROWS, COLS * ROWS)  # more area than any shape can hold
    assert np.array_equal(mask, SHAPES["rectangle"](random.Random(1), COLS, ROWS))
