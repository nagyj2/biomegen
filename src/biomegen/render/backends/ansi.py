"""ANSI back-end: a document as escape-coded text for a terminal (truecolor or 256 colours)."""

from __future__ import annotations

from typing import Optional

from ..grid import RGB, Document

_RESET = "\x1b[0m"
MODES = ("truecolor", "256")


def rgb_to_256(color: RGB) -> int:
    """Return the xterm-256 palette index nearest to ``color`` (the grey ramp for near-greys)."""
    red, green, blue = color
    if abs(red - green) < 10 and abs(green - blue) < 10:
        if red < 8:
            return 16
        if red > 248:
            return 231
        return 232 + round((red - 8) / 247 * 24)
    return 16 + 36 * round(red / 255 * 5) + 6 * round(green / 255 * 5) + round(blue / 255 * 5)


def _color_code(prefix: int, color: RGB, mode: str) -> str:
    if mode == "truecolor":
        return f"{prefix};2;{color[0]};{color[1]};{color[2]}"
    return f"{prefix};5;{rgb_to_256(color)}"


def _style_codes(fg: Optional[RGB], bg: Optional[RGB], bold: bool, mode: str) -> str:
    codes = ["0"]
    if bold:
        codes.append("1")
    if fg is not None:
        codes.append(_color_code(38, fg, mode))
    if bg is not None:
        codes.append(_color_code(48, bg, mode))
    return "\x1b[" + ";".join(codes) + "m"


def to_ansi(document: Document, mode: str = "truecolor") -> str:
    """Return the document as ANSI text; ``mode`` is ``"truecolor"`` or ``"256"``.

    A style sequence is emitted only where the style changes, and every line ends with a reset so a
    broken pipe never leaves the terminal coloured.
    """
    if mode not in MODES:
        raise ValueError(f"unknown colour mode {mode!r}; expected one of {', '.join(MODES)}")
    lines = []
    for row in document:
        parts: list[str] = []
        last: Optional[tuple[Optional[RGB], Optional[RGB], bool]] = None
        for span in row:
            style = (span.fg, span.bg, span.bold)
            if style != last:
                parts.append(_style_codes(span.fg, span.bg, span.bold, mode))
                last = style
            parts.append(span.text)
        parts.append(_RESET)
        lines.append("".join(parts))
    return "\n".join(lines)
