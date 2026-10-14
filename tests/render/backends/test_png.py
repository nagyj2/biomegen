"""Tests for the PNG back-end reading a CellGrid."""

from __future__ import annotations

import pytest

from biomegen.render.backends.png import pillow_available, render_png
from biomegen.render.grid import CellGrid

pytestmark = pytest.mark.skipif(not pillow_available(), reason="Pillow is not installed")


def test_render_png_writes_an_image_of_the_grid_size(tmp_path) -> None:
    from PIL import Image

    path = tmp_path / "grid.png"
    assert render_png(CellGrid(3, 4), 8, (0, 0, 0), str(path))
    assert Image.open(path).size == (32, 24)


def test_render_png_fills_cells_with_the_background_colour(tmp_path) -> None:
    from PIL import Image

    path = tmp_path / "grid.png"
    render_png(CellGrid(2, 2, bg=(12, 34, 56)), 8, (0, 0, 0), str(path))
    assert Image.open(path).getpixel((1, 1)) == (12, 34, 56)
