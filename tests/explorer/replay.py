"""A tiny virtual terminal: replays the diff writer's output so tests can look at the screen it builds."""

from __future__ import annotations

import io
import re

import numpy as np

_ESCAPE = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")


def replay(output: str, rows: int, cols: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Interpret cursor moves, truecolor styles and text; return the glyph, fg and bg of each cell."""
    glyph = np.full((rows, cols), " ", dtype="U1")
    fg = np.zeros((rows, cols, 3), dtype=np.uint8)
    bg = np.zeros((rows, cols, 3), dtype=np.uint8)
    row = col = 0
    cur_fg = cur_bg = (0, 0, 0)
    position = 0
    for match in _ESCAPE.finditer(output):
        for char in output[position : match.start()]:
            glyph[row, col], fg[row, col], bg[row, col] = char, cur_fg, cur_bg
            col += 1
        position = match.end()
        params, final = match.group(1), match.group(2)
        if final == "H":
            row, col = (int(v) - 1 for v in params.split(";"))
        elif final == "m":
            numbers = [int(v) for v in params.split(";") if v]
            if not numbers or numbers == [0]:
                cur_fg = cur_bg = (0, 0, 0)
            index = 0
            while index < len(numbers):
                if numbers[index] in (38, 48) and numbers[index + 1] == 2:
                    color = tuple(numbers[index + 2 : index + 5])
                    cur_fg, cur_bg = (color, cur_bg) if numbers[index] == 38 else (cur_fg, color)
                    index += 5
                else:
                    if numbers[index] == 0:
                        cur_fg = cur_bg = (0, 0, 0)
                    index += 1
    return glyph, fg, bg


def screen_text(output: str, rows: int, cols: int) -> list[str]:
    """Replay ``output`` and return the screen as one string per row."""
    glyph, _, _ = replay(output, rows, cols)
    return ["".join(row) for row in glyph.tolist()]


class RecordingOut(io.StringIO):
    """An output stream that keeps the screen text after every flush (one entry per drawn frame)."""

    def __init__(self, rows: int, cols: int) -> None:
        super().__init__()
        self.rows, self.cols = rows, cols
        self.frames: list[list[str]] = []

    def flush(self) -> None:
        self.frames.append(screen_text(self.getvalue(), self.rows, self.cols))
