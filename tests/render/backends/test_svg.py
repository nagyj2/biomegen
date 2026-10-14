"""Tests for the SVG back-end reading a CellGrid."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from biomegen.render.backends import cells_from_grid
from biomegen.render.backends.svg import render_svg
from biomegen.render.grid import CellGrid


def _grid() -> CellGrid:
    grid = CellGrid(2, 2, bg=(10, 20, 30), fg=(200, 100, 50))
    grid.glyph[0, 0] = "A"
    grid.bold[0, 0] = True
    return grid


def test_cells_from_grid_carries_every_attribute() -> None:
    assert cells_from_grid(_grid())[0][0] == ((10, 20, 30), "A", (200, 100, 50), True)


def test_render_svg_is_well_formed_xml() -> None:
    ET.fromstring(render_svg(_grid(), 10, (0, 0, 0)))


def test_render_svg_sizes_the_canvas_from_the_grid() -> None:
    root = ET.fromstring(render_svg(_grid(), 10, (0, 0, 0)))
    assert (root.get("width"), root.get("height")) == ("20", "20")


def test_render_svg_is_deterministic() -> None:
    assert render_svg(_grid(), 10, (0, 0, 0)) == render_svg(_grid(), 10, (0, 0, 0))


def test_render_svg_draws_only_non_blank_glyphs() -> None:
    root = ET.fromstring(render_svg(_grid(), 10, (0, 0, 0)))
    assert len(root.findall(".//{http://www.w3.org/2000/svg}text")) == 1
