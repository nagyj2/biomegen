"""Distinct faction colours: each new colour is the one farthest, in CIELAB, from every colour already taken.

Pure functions of their arguments, so the realms stage, the history stage (fallen realms) and a later simulation (new
factions) draw from one scheme and the map and the chronicle show the same colour for the same faction.
"""

from __future__ import annotations

import colorsys
from collections.abc import Sequence

RGB = tuple[int, int, int]

_WHITE = (0.95047, 1.0, 1.08883)  # D65 reference white


def _linear(channel: int) -> float:
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1.0 / 3.0) if t > 216.0 / 24389.0 else (24389.0 / 27.0 * t + 16.0) / 116.0


def lab(color: RGB) -> tuple[float, float, float]:
    """Return ``color`` as CIELAB ``(L, a, b)``."""
    r, g, b = (_linear(c) for c in color)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / _WHITE[0]
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / _WHITE[1]
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / _WHITE[2]
    fx, fy, fz = _f(x), _f(y), _f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def distance(a: RGB, b: RGB) -> float:
    """The CIELAB distance between two colours (about 2.3 is a just-noticeable difference)."""
    return sum((p - q) ** 2 for p, q in zip(lab(a), lab(b), strict=True)) ** 0.5


def luma(color: RGB) -> float:
    """The perceived brightness of ``color`` on 0..255."""
    return 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]


def hue_candidates(saturation: float, value: float, steps: int, start: float, min_luma: float) -> list[RGB]:
    """Return the colours of ``steps`` hues round the circle (from ``start``) that are bright enough to read on dark."""
    colors = []
    for step in range(steps):
        red, green, blue = colorsys.hsv_to_rgb((start + step / steps) % 1.0, saturation, value)
        color = (int(red * 255), int(green * 255), int(blue * 255))
        if luma(color) >= min_luma:
            colors.append(color)
    return colors


def farthest(candidates: Sequence[RGB], taken: Sequence[RGB]) -> RGB:
    """Return the candidate farthest from its nearest ``taken`` colour (the first of equals; the first if none)."""
    labs = [lab(color) for color in taken]
    best, best_gap = candidates[0], -1.0
    for color in candidates:
        here = lab(color)
        gap = min((sum((p - q) ** 2 for p, q in zip(here, other, strict=True)) for other in labs), default=1e9)
        if gap > best_gap:
            best, best_gap = color, gap
    return best
