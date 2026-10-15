"""The ANSI diff writer: draws a cell grid to a terminal, sending only what changed since the last frame.

The explorer composes one :class:`~biomegen.render.grid.CellGrid` the size of the terminal per frame. The
writer compares it with the previous frame (numpy, per cell), then emits a cursor move and the new cells for
each run of changed cells, with a style sequence only where the style changes, naming only the parts (bold, glyph
colour, fill) that differ from the last one sent. An unchanged frame writes nothing, and a cursor step rewrites a
handful of cells instead of the whole screen.

The writer owns the terminal state: the alternate screen, the hidden hardware cursor and disabled line wrap
(so writing the bottom-right cell cannot scroll). Colour is ``"truecolor"``, ``"256"`` or ``"none"``.
"""

from __future__ import annotations

import os
from typing import Optional, TextIO

import numpy as np

from ..render.backends.ansi import MODES, color_code
from ..render.grid import CellGrid

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
        self._codes: dict[tuple[int, int], str] = {}

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
            changed = glyph != self._glyph
            if self.mode != "none":
                changed |= style != self._style
        cells = np.flatnonzero(changed)
        if cells.size:
            self._encode(pieces, glyph, style, cells)
        self._glyph = glyph.copy()
        self._style = style
        if pieces:
            pieces.append("\x1b[0m")
            self._out.write("".join(pieces))
            self._out.flush()

    def _encode(self, pieces: list[str], glyph: np.ndarray, style: np.ndarray, cells: np.ndarray) -> None:
        """Append the changed ``cells`` (flat indices, row-major): a cursor move per run, a style change per segment.

        Runs and style segments are found for the whole frame at once; the loop only joins strings. The terminal keeps
        its style across cursor moves, so a segment sends only the parts of the style that differ from the last one.
        """
        cols = glyph.shape[1]
        col = cells % cols
        run_start = np.ones(cells.size, dtype=bool)
        run_start[1:] = (np.diff(cells) != 1) | (col[1:] == 0)
        glyphs = glyph.ravel()[cells].tolist()
        if self.mode == "none":
            starts = np.flatnonzero(run_start)
            styles: list[int] = []
        else:
            packed = style.ravel()[cells]
            segment_start = run_start.copy()
            segment_start[1:] |= packed[1:] != packed[:-1]
            starts = np.flatnonzero(segment_start)
            styles = packed[starts].tolist()
        ends = np.append(starts[1:], cells.size).tolist()
        moves = run_start[starts].tolist()
        rows = (cells[starts] // cols).tolist()
        columns = col[starts].tolist()
        current: Optional[int] = None
        for index, (first, last) in enumerate(zip(starts.tolist(), ends, strict=True)):
            if moves[index]:
                pieces.append(f"\x1b[{rows[index] + 1};{columns[index] + 1}H")
            if styles and styles[index] != current:
                pieces.append(self._style_change(current, styles[index]))
                current = styles[index]
            pieces.append("".join(glyphs[first:last]))

    def _style_change(self, previous: Optional[int], packed: int) -> str:
        """Return the SGR sequence from style ``previous`` (``None``: unknown) to ``packed`` (see ``_pack_styles``)."""
        bold, fg, bg = packed >> 48 & 1, packed >> 24 & 0xFFFFFF, packed & 0xFFFFFF
        if previous is None:
            codes = ["0", "1"] if bold else ["0"]
            codes += [self._color(38, fg), self._color(48, bg)]
        else:
            codes = []
            if bold != previous >> 48 & 1:
                codes.append("1" if bold else "22")
            if fg != previous >> 24 & 0xFFFFFF:
                codes.append(self._color(38, fg))
            if bg != previous & 0xFFFFFF:
                codes.append(self._color(48, bg))
        return "\x1b[" + ";".join(codes) + "m"

    def _color(self, prefix: int, rgb: int) -> str:
        """Return the colour parameters for ``rgb`` (packed ``0xRRGGBB``), memoised per colour."""
        key = (prefix, rgb)
        code = self._codes.get(key)
        if code is None:
            color = (rgb >> 16 & 0xFF, rgb >> 8 & 0xFF, rgb & 0xFF)
            code = color_code(prefix, color, self.mode)
            self._codes[key] = code
        return code
