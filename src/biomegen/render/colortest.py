"""The colour and glyph test card behind ``--color-test``."""

from __future__ import annotations

import colorsys

from .backends.ansi import rgb_to_256
from .grid import Document, Span

_STEPS = 72


def color_test(detected: str, environment: dict[str, str]) -> Document:
    """Return swatches that show what a terminal supports.

    Args:
        detected: The colour mode ``--color auto`` would pick (``truecolor``, ``256`` or ``none``).
        environment: The terminal-related environment variables that were set, for the report.
    """
    hues = [tuple(int(c * 255) for c in colorsys.hsv_to_rgb(k / _STEPS, 0.9, 1.0)) for k in range(_STEPS)]
    greys = [(v, v, v) for v in range(0, 256, 4)[:_STEPS]]
    exact = [Span(" ", None, (r, g, b)) for r, g, b in hues]
    banded = [Span(" ", None, _palette_rgb(rgb_to_256((r, g, b)))) for r, g, b in hues]
    document: Document = [
        [Span("Colour test")],
        [Span("")],
        [Span(" 1) truecolor : ")] + exact,
        [Span("    greys     : ")] + [Span(" ", None, grey) for grey in greys],
        [Span(" 2) 256-colour: ")] + banded,
        [Span("")],
        [Span(' Glyphs      :  ≈ ~ ░ · ∴ , " ♣ ♠ ψ ↑ ¨ * ∩ ^ ▲ Λ ✦ ● ○ • ¤ Ω † § × ─│╭╮╰╯┼ ═║ °C km²')],
        [Span("")],
        [Span(" If row 1 is a smooth rainbow and the grey bar has no visible steps, your terminal supports")],
        [Span(" 24-bit truecolor: use --color truecolor. If row 1 looks as blocky as row 2, use --color 256.")],
        [Span(" Boxes or ? in the glyph row: use --ascii, or a font such as Cascadia Mono or DejaVu Sans Mono.")],
        [Span("")],
        [
            Span(
                " Detected: "
                + (", ".join(f"{k}={v}" for k, v in environment.items()) or "no colour hints in environment")
            )
        ],
        [Span(f" auto would choose: {detected}")],
    ]
    return document


def _palette_rgb(index: int) -> tuple[int, int, int]:
    """Return the RGB an xterm-256 palette index displays as (the 6x6x6 cube and the grey ramp)."""
    if index >= 232:
        level = 8 + (index - 232) * 10
        return (level, level, level)
    index -= 16
    levels = (0, 95, 135, 175, 215, 255)
    return (levels[index // 36], levels[(index // 6) % 6], levels[index % 6])
