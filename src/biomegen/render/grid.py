"""The renderer's intermediate representation: a grid of styled cells and the documents built from it.

A :class:`CellGrid` is the map body, four parallel numpy arrays (glyph, foreground, background, bold).
Layers mutate it in place; the explorer writes it straight to the terminal; SVG and PNG read it. Static
output (frame furniture, legend) is a :class:`Document`, rows of :class:`Span` runs, because margins and
text lines have no background colour (``None`` means the terminal default).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from numpy.typing import ArrayLike

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Span:
    """A run of text with one style; ``None`` colours mean the terminal default."""

    text: str
    fg: Optional[RGB] = None
    bg: Optional[RGB] = None
    bold: bool = False


Document = list[list[Span]]


_DENSE = 1.0 / 16.0  # share of masked cells above which one masked copy beats gathering and scattering them


def _write(target: np.ndarray, mask: np.ndarray, value: ArrayLike, density: float) -> None:
    """Write ``value`` (a full-grid array or a scalar) into ``target`` where ``mask`` holds, ``density`` of the cells.

    A full mask is a plain assignment and a dense one a single masked copy; only a sparse mask gathers its cells.
    Values are cast as an indexed assignment would cast them.
    """
    if density == 1.0:
        target[...] = value
        return
    if density >= _DENSE:
        np.copyto(target, value, casting="unsafe", where=mask[..., np.newaxis] if target.ndim == 3 else mask)
        return
    target[mask] = value[mask] if isinstance(value, np.ndarray) else value


class CellGrid:
    """A ``rows x cols`` grid of cells.

    Attributes:
        glyph: ``U1`` array ``[rows, cols]``, one character per cell.
        fg: ``uint8`` array ``[rows, cols, 3]``, glyph colour.
        bg: ``uint8`` array ``[rows, cols, 3]``, cell fill.
        bold: ``bool`` array ``[rows, cols]``.
    """

    def __init__(self, rows: int, cols: int, bg: RGB = (0, 0, 0), fg: RGB = (255, 255, 255)) -> None:
        if rows <= 0 or cols <= 0:
            raise ValueError(f"grid dimensions must be positive, got {rows}x{cols}")
        self.glyph = np.full((rows, cols), " ", dtype="U1")
        self.fg = np.empty((rows, cols, 3), dtype=np.uint8)
        self.fg[:] = fg
        self.bg = np.empty((rows, cols, 3), dtype=np.uint8)
        self.bg[:] = bg
        self.bold = np.zeros((rows, cols), dtype=bool)

    @property
    def rows(self) -> int:
        return int(self.glyph.shape[0])

    @property
    def cols(self) -> int:
        return int(self.glyph.shape[1])

    def put(
        self,
        mask: np.ndarray,
        glyph: Optional[np.ndarray | str] = None,
        fg: Optional[np.ndarray | RGB] = None,
        bg: Optional[np.ndarray | RGB] = None,
        bold: Optional[bool] = None,
    ) -> None:
        """Write the given attributes into the cells where ``mask`` is true; ``None`` leaves one unchanged.

        Array arguments are full-grid (``[rows, cols]`` or ``[rows, cols, 3]``) and are read at the masked
        cells; scalars (a string, an RGB triple, a bool) apply to every masked cell.
        """
        count = int(np.count_nonzero(mask))
        if count == 0:
            return
        density = 1.0 if count == mask.size else count / mask.size
        if glyph is not None:
            _write(self.glyph, mask, glyph, density)
        if fg is not None:
            _write(self.fg, mask, fg, density)
        if bg is not None:
            _write(self.bg, mask, bg, density)
        if bold is not None:
            _write(self.bold, mask, bold, density)

    def to_document(self) -> Document:
        """Return the grid as rows of spans, merging neighbouring cells that share a style."""
        document: Document = []
        for row in range(self.rows):
            spans: list[Span] = []
            run: list[str] = []
            style: Optional[tuple[RGB, RGB, bool]] = None
            fg_row = self.fg[row].tolist()
            bg_row = self.bg[row].tolist()
            for col in range(self.cols):
                cell_style = (tuple(fg_row[col]), tuple(bg_row[col]), bool(self.bold[row, col]))
                if cell_style != style and run:
                    assert style is not None
                    spans.append(Span("".join(run), style[0], style[1], style[2]))
                    run = []
                style = cell_style
                run.append(str(self.glyph[row, col]))
            if run and style is not None:
                spans.append(Span("".join(run), style[0], style[1], style[2]))
            document.append(spans)
        return document
