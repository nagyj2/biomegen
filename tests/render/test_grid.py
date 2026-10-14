"""Tests for the cell grid IR and its conversion to a Document."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.render.grid import CellGrid, Span


def test_new_grid_is_filled_with_the_given_colours() -> None:
    grid = CellGrid(2, 3, bg=(1, 2, 3), fg=(4, 5, 6))
    assert grid.bg[1, 2].tolist() == [1, 2, 3] and grid.fg[0, 0].tolist() == [4, 5, 6]


def test_grid_rejects_empty_dimensions() -> None:
    with pytest.raises(ValueError):
        CellGrid(0, 5)


def test_put_writes_only_masked_cells() -> None:
    grid = CellGrid(2, 2)
    mask = np.array([[True, False], [False, False]])
    grid.put(mask, glyph="x", bg=(9, 9, 9), bold=True)
    assert grid.glyph.tolist() == [["x", " "], [" ", " "]]
    assert grid.bg[0, 0].tolist() == [9, 9, 9] and grid.bg[0, 1].tolist() == [0, 0, 0]
    assert grid.bold.tolist() == [[True, False], [False, False]]


def test_put_reads_array_arguments_at_masked_cells() -> None:
    # A full-grid colour array supplies a different value per masked cell.
    grid = CellGrid(1, 2)
    colours = np.array([[[10, 0, 0], [20, 0, 0]]], dtype=np.uint8)
    grid.put(np.array([[True, True]]), fg=colours)
    assert grid.fg[0].tolist() == [[10, 0, 0], [20, 0, 0]]


def test_to_document_merges_cells_with_one_style() -> None:
    grid = CellGrid(1, 3, bg=(0, 0, 0), fg=(1, 1, 1))
    grid.glyph[0] = list("abc")
    assert grid.to_document() == [[Span("abc", (1, 1, 1), (0, 0, 0), False)]]


def test_to_document_splits_runs_where_the_style_changes() -> None:
    grid = CellGrid(1, 3)
    grid.glyph[0] = list("abc")
    grid.bold[0, 1] = True
    assert [span.text for span in grid.to_document()[0]] == ["a", "b", "c"]
