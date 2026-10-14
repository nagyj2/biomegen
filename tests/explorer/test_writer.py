"""Tests for the ANSI diff writer, including a replay of its output on a tiny virtual screen."""

from __future__ import annotations

import io
import re

import numpy as np
import pytest

from biomegen.explorer.writer import DiffWriter
from biomegen.render.grid import CellGrid
from tests.explorer.replay import replay as _replay


def _grid(rows: int = 3, cols: int = 6) -> CellGrid:
    grid = CellGrid(rows, cols)
    grid.glyph[:] = "."
    return grid


def _draw(writer: DiffWriter, out: io.StringIO, grid: CellGrid) -> str:
    """Draw ``grid`` and return only what this draw wrote."""
    out.seek(0)
    out.truncate()
    writer.draw(grid)
    return out.getvalue()


def test_first_draw_writes_every_cell() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    grid.glyph[1, 2] = "X"
    glyph, _, _ = _replay(_draw(writer, out, grid), 3, 6)
    assert (glyph == grid.glyph).all()


def test_an_unchanged_frame_writes_nothing() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    assert _draw(writer, out, grid) == ""


def test_one_changed_cell_writes_one_move_and_one_glyph() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    grid.glyph[1, 3] = "X"
    update = _draw(writer, out, grid)
    assert update.count("\x1b[2;4H") == 1 and update.count("X") == 1 and update.count("H") == 1


def test_neighbouring_changes_share_one_cursor_move() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    grid.glyph[0, 1:4] = "abc"
    assert _draw(writer, out, grid).count("H") == 1


def test_separate_changes_in_a_row_get_their_own_moves() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    grid.glyph[0, 0] = "a"
    grid.glyph[0, 5] = "b"
    assert _draw(writer, out, grid).count("H") == 2


def test_a_colour_change_alone_is_rewritten() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    grid.bg[2, 2] = (10, 20, 30)
    assert "48;2;10;20;30" in _draw(writer, out, grid)


def test_replaying_a_sequence_of_frames_rebuilds_the_last_one() -> None:
    # Apply the first frame, then the diff to a second: the virtual screen must equal the second grid.
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    rng = np.random.default_rng(1)
    first = _grid(4, 10)
    first.fg[:] = rng.integers(0, 256, size=first.fg.shape)
    first.bg[:] = rng.integers(0, 4, size=first.bg.shape) * 60
    second = _grid(4, 10)
    second.glyph[:] = np.where(rng.random((4, 10)) < 0.3, "#", ".")
    second.fg[:] = first.fg
    second.bg[:] = first.bg
    second.bg[1, 4:7] = (200, 100, 50)
    initial = _draw(writer, out, first)
    update = _draw(writer, out, second)
    # Replaying both outputs in order on one screen is what a terminal does.
    glyph, fg, bg = _replay(initial + update, 4, 10)
    assert (glyph == second.glyph).all() and (fg == second.fg).all() and (bg == second.bg).all()


def test_a_size_change_clears_and_repaints_everything() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    _draw(writer, out, _grid(3, 6))
    update = _draw(writer, out, _grid(4, 8))
    assert "\x1b[2J" in update and update.count("H") == 4


def test_invalidate_forces_a_full_repaint() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "truecolor")
    grid = _grid()
    _draw(writer, out, grid)
    writer.invalidate()
    assert "\x1b[2J" in _draw(writer, out, grid)


def test_no_colour_mode_writes_no_style_sequences() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "none")
    grid = _grid()
    grid.fg[:] = (200, 10, 10)
    assert not re.search(r"\x1b\[[0-9;]*m(?!$)", _draw(writer, out, grid).replace("\x1b[0m", ""))


def test_256_colour_mode_uses_palette_indices() -> None:
    out = io.StringIO()
    writer = DiffWriter(out, "256")
    grid = _grid()
    grid.fg[:] = (200, 10, 10)
    assert "38;5;" in _draw(writer, out, grid)


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="colour mode"):
        DiffWriter(io.StringIO(), "mono")


def test_enter_and_leave_manage_the_alternate_screen() -> None:
    out = io.StringIO()
    writer = DiffWriter(out)
    writer.enter()
    writer.leave()
    text = out.getvalue()
    assert text.index("\x1b[?1049h") < text.index("\x1b[?1049l") and "\x1b[?25l" in text and "\x1b[?25h" in text
