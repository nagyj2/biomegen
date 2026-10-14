"""The ANSI diff writer: draws a cell grid to a terminal, sending only what changed since the last frame.

The explorer composes one :class:`~biomegen.render.grid.CellGrid` the size of the terminal per frame. The
writer compares it with the previous frame (numpy, per cell), then emits a cursor move and the new cells for
each run of changed cells, with a style sequence only where the style changes. An unchanged frame writes
nothing, and a cursor step rewrites a handful of cells instead of the whole screen.

The writer owns the terminal state: the alternate screen, the hidden hardware cursor and disabled line wrap
(so writing the bottom-right cell cannot scroll). Colour is ``"truecolor"``, ``"256"`` or ``"none"``.
"""

from __future__ import annotations

import os
from typing import Optional, TextIO

import numpy as np

from ..render.backends.ansi import MODES, style_codes
from ..render.grid import RGB, CellGrid

_ENTER = "\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J"
_LEAVE = "\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l"
_CLEAR = "\x1b[0m\x1b[2J"


def _pack_styles(grid: CellGrid) -> np.ndarray:
    """Pack each cell's fg, bg and bold into one integer so style changes are a single comparison."""
    fg = grid.fg.astype(np.int64)
    bg = grid.bg.astype(np.int64)
    return (
        (fg[..., 0] << 40)
        | (fg[..., 1] << 32)
        | (fg[..., 2] << 24)
        | (bg[..., 0] << 16)
        | (bg[..., 1] << 8)
        | bg[..., 2]
        | (grid.bold.astype(np.int64) << 48)
    )


def _rgb(color: np.ndarray) -> RGB:
    return int(color[0]), int(color[1]), int(color[2])


class DiffWriter:
    """Writes grids to ``out`` as minimal ANSI updates.

    Attributes:
        mode: ``"truecolor"``, ``"256"`` or ``"none"``.
    """

    def __init__(self, out: TextIO, mode: str = "truecolor") -> None:
        if mode != "none" and mode not in MODES:
            raise ValueError(f"unknown colour mode {mode!r}; expected none or one of {', '.join(MODES)}")
        self._out = out
        self.mode = mode
        self._glyph: Optional[np.ndarray] = None
        self._style: Optional[np.ndarray] = None

    def enter(self) -> None:
        """Switch to the alternate screen, hide the cursor and stop line wrap."""
        if os.name == "nt":
            os.system("")  # enables VT escape processing on Windows 10+
        self._out.write(_ENTER)
        self._out.flush()
        self._glyph = self._style = None

    def leave(self) -> None:
        """Undo :meth:`enter`: reset colours, restore wrap and the cursor, leave the alternate screen."""
        self._out.write(_LEAVE)
        self._out.flush()
        self._glyph = self._style = None

    def invalidate(self) -> None:
        """Forget the last frame so the next draw repaints everything (after a resize or a suspend)."""
        self._glyph = self._style = None

    def draw(self, grid: CellGrid) -> None:
        """Write the cells of ``grid`` that differ from the previous frame (all of them on the first)."""
        glyph = grid.glyph
        style = _pack_styles(grid)
        pieces: list[str] = []
        if self._glyph is None or self._glyph.shape != glyph.shape:
            pieces.append(_CLEAR)
            changed = np.ones(glyph.shape, dtype=bool)
        else:
            assert self._style is not None
            changed = (glyph != self._glyph) | (style != self._style)
            if self.mode == "none":
                changed = glyph != self._glyph
        for row in np.nonzero(changed.any(axis=1))[0].tolist():
            self._write_row(pieces, grid, style, changed[row], row)
        self._glyph = glyph.copy()
        self._style = style
        if pieces:
            pieces.append("\x1b[0m")
            self._out.write("".join(pieces))
            self._out.flush()

    def _write_row(self, pieces: list[str], grid: CellGrid, style: np.ndarray, changed: np.ndarray, row: int) -> None:
        """Append the runs of changed cells of one row: a cursor move, then glyphs with style changes."""
        columns = np.nonzero(changed)[0]
        breaks = np.nonzero(np.diff(columns) > 1)[0] + 1
        for run in np.split(columns, breaks):
            start, stop = int(run[0]), int(run[-1]) + 1
            pieces.append(f"\x1b[{row + 1};{start + 1}H")
            if self.mode == "none":
                pieces.append("".join(grid.glyph[row, start:stop].tolist()))
                continue
            cuts = np.nonzero(np.diff(style[row, start:stop]))[0] + 1
            for segment in np.split(np.arange(start, stop), cuts):
                first, last = int(segment[0]), int(segment[-1]) + 1
                pieces.append(
                    style_codes(
                        _rgb(grid.fg[row, first]), _rgb(grid.bg[row, first]), bool(grid.bold[row, first]), self.mode
                    )
                )
                pieces.append("".join(grid.glyph[row, first:last].tolist()))
