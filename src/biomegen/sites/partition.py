"""Binary space partition: cut a grid into rooms.

The classic roguelike layout: recursively cut the area into sub-rectangles, then drop a room into each leaf. Plan cells
are taller than wide, so room widths are ``aspect`` times the row limits and the longer physical side is cut first.
"""

from __future__ import annotations

import math
import random

from .carve import Rect

_MAX_DEPTH = 6  # recursion ceiling
_STOP_PROBABILITY = 0.12  # chance a small-enough leaf stops splitting early


def _split(
    rgen: random.Random, x: int, y: int, w: int, h: int, limits: tuple[int, int, int, int], aspect: float, depth: int
) -> list[Rect]:
    """Recursively cut ``(x, y, w, h)`` into leaves no smaller than a room plus slack for its wall."""
    min_w, max_w, min_h, max_h = limits
    leaf_w, leaf_h = min_w + 1, min_h + 1
    can_vertical = w >= 2 * leaf_w
    can_horizontal = h >= 2 * leaf_h
    small = w <= max_w and h <= max_h
    if depth >= _MAX_DEPTH or not (can_vertical or can_horizontal) or (small and rgen.random() < _STOP_PROBABILITY):
        return [(x, y, w, h)] if w >= min_w and h >= min_h else []
    cut_vertical = can_vertical if not can_horizontal else (w >= h * aspect if can_vertical else False)
    if cut_vertical:
        cut = rgen.randint(leaf_w, w - leaf_w)
        return _split(rgen, x, y, cut, h, limits, aspect, depth + 1) + _split(
            rgen, x + cut, y, w - cut, h, limits, aspect, depth + 1
        )
    cut = rgen.randint(leaf_h, h - leaf_h)
    return _split(rgen, x, y, w, cut, limits, aspect, depth + 1) + _split(
        rgen, x, y + cut, w, h - cut, limits, aspect, depth + 1
    )


def bsp_rooms(
    rgen: random.Random, cols: int, rows: int, room_rows: tuple[int, int], aspect: float, border: int = 1
) -> list[Rect]:
    """Return room rectangles inside a ``border``-cell margin of a ``cols x rows`` grid.

    ``room_rows`` is the room height range in rows; widths are that times ``aspect``. The margin leaves a void cell on
    every side for the outer wall.
    """
    min_h, max_h = room_rows
    limits = (math.ceil(min_h * aspect), math.ceil(max_h * aspect), min_h, max_h)
    inner_w, inner_h = cols - 2 * border, rows - 2 * border
    if inner_w < limits[0] or inner_h < min_h:
        return [(border, border, max(1, inner_w), max(1, inner_h))]
    rooms: list[Rect] = []
    for lx, ly, lw, lh in _split(rgen, border, border, inner_w, inner_h, limits, aspect, 0):
        rw = rgen.randint(limits[0], min(limits[1], lw))
        rh = rgen.randint(min_h, min(max_h, lh))
        rooms.append((lx + rgen.randint(0, lw - rw), ly + rgen.randint(0, lh - rh), rw, rh))
    return rooms or [(border, border, inner_w, inner_h)]
