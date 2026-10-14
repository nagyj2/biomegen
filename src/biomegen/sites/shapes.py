"""Outlines for solid structures: the algorithms that make a floor plan not a rectangle.

Each shape is a function ``(rgen, cols, rows) -> bool[rows, cols]`` returning the cells inside the structure. The
builder fills that region with rooms and rock and lets terrain show everywhere else, so the structure reads as an
organic mass. Every shape is inset by one cell (an exterior ring for the outer wall and the entrance) and reduced to one
connected piece. Dimensions are relative, so a shape keeps its proportions on any grid.

* ``rectangle`` - the whole interior.
* ``blob``      - the union of several overlapping ellipses: a smooth lumpy mass.
* ``cellular``  - a cellular-automata cave: random seed, 4-5 smoothing, the largest cavern.
* ``drunkard``  - a drunkard's walk that stamps a thick trail: a meandering, water-carved cave.
* ``diamond``   - a rhombus.
* ``cross``     - a plus of two overlapping bars.
"""

from __future__ import annotations

import random
from typing import Callable

import numpy as np
from scipy import ndimage

from .carve import largest_component

Shape = Callable[[random.Random, int, int], np.ndarray]
SHAPES: dict[str, Shape] = {}

MIXED = "mixed"  # config value meaning "pick a concrete outline per structure"


def _shape(name: str) -> Callable[[Shape], Shape]:
    def register(function: Shape) -> Shape:
        SHAPES[name] = function
        return function

    return register


def _inner(cols: int, rows: int) -> np.ndarray:
    mask = np.zeros((rows, cols), dtype=bool)
    mask[1 : rows - 1, 1 : cols - 1] = True
    return mask


def _ellipse(cols: int, rows: int, cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    ys, xs = np.ogrid[0:rows, 0:cols]
    return ((xs - cx) / max(0.5, rx)) ** 2 + ((ys - cy) / max(0.5, ry)) ** 2 <= 1.0


@_shape("rectangle")
def rectangle(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """The full interior (the boxy baseline)."""
    return _inner(cols, rows)


@_shape("diamond")
def diamond(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """A rhombus: ``|x - cx| / rx + |y - cy| / ry <= 1``."""
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    ys, xs = np.ogrid[0:rows, 0:cols]
    rx, ry = max(0.5, (cols - 2) / 2.0), max(0.5, (rows - 2) / 2.0)
    return (np.abs(xs - cx) / rx + np.abs(ys - cy) / ry <= 1.0) & _inner(cols, rows)


@_shape("cross")
def cross(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """A plus: a vertical and a horizontal bar through the centre, each 45-65% of the other dimension."""
    bar_w = max(3, int(cols * rgen.uniform(0.45, 0.65)))
    bar_h = max(3, int(rows * rgen.uniform(0.45, 0.65)))
    mask = np.zeros((rows, cols), dtype=bool)
    mask[:, (cols - bar_w) // 2 : (cols - bar_w) // 2 + bar_w] = True
    mask[(rows - bar_h) // 2 : (rows - bar_h) // 2 + bar_h, :] = True
    return mask & _inner(cols, rows)


@_shape("blob")
def blob(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """Metaball accretion: overlapping ellipses clustered round the middle, large enough to hold several rooms."""
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    mask = np.zeros((rows, cols), dtype=bool)
    for _ in range(rgen.randint(4, 7)):
        mask |= _ellipse(
            cols,
            rows,
            cx + rgen.uniform(-0.28, 0.28) * cols,
            cy + rgen.uniform(-0.28, 0.28) * rows,
            rgen.uniform(0.18, 0.34) * cols,
            rgen.uniform(0.18, 0.34) * rows,
        )
    return largest_component(mask & _inner(cols, rows))


@_shape("cellular")
def cellular(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """A cave: a centre-weighted random seed, smoothed so a cell is solid with five solid neighbours (four if solid)."""
    inner = _inner(cols, rows)
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    ys, xs = np.ogrid[0:rows, 0:cols]
    falloff = np.clip(1.0 - np.sqrt(((xs - cx) / max(1.0, cx)) ** 2 + ((ys - cy) / max(1.0, cy)) ** 2), 0.0, 1.0)
    chance = 0.30 + 0.45 * falloff
    alive = np.array([[rgen.random() < chance[y, x] for x in range(cols)] for y in range(rows)]) & inner
    kernel = np.ones((3, 3), dtype=np.int16)
    kernel[1, 1] = 0
    for _ in range(5):
        near = ndimage.convolve(alive.astype(np.int16), kernel, mode="constant", cval=0)
        alive = ((near >= 5) | (alive & (near >= 4))) & inner
    alive &= _ellipse(cols, rows, cx, cy, 0.52 * cols, 0.52 * rows)
    return largest_component(alive)


@_shape("drunkard")
def drunkard(rgen: random.Random, cols: int, rows: int) -> np.ndarray:
    """A walker stamping an ellipse twice as wide as tall (cells are taller than wide) over 45% of the interior."""
    inner = _inner(cols, rows)
    mask = np.zeros((rows, cols), dtype=bool)
    target = int(0.45 * int(inner.sum()))
    x, y = cols // 2, rows // 2
    steps, cap = 0, max(1, target) * 12
    ys, xs = np.ogrid[0:rows, 0:cols]
    while int(mask.sum()) < target and steps < cap:
        steps += 1
        mask |= (((xs - x) / 4.0) ** 2 + ((ys - y) / 2.0) ** 2 <= 1.0) & inner
        step_x, step_y = rgen.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        x = min(cols - 2, max(1, x + step_x))
        y = min(rows - 2, max(1, y + step_y))
    return largest_component(mask)


def outline(name: str, rgen: random.Random, cols: int, rows: int, min_area: int) -> np.ndarray:
    """Return the outline mask for ``name`` (``MIXED`` picks one per structure, never the plain rectangle).

    A shape too small to hold ``min_area`` cells falls back to the rectangle, a choice that depends only on the grid.
    """
    if name == MIXED:
        name = rgen.choice(sorted(n for n in SHAPES if n != "rectangle"))
    mask = SHAPES[name](rgen, cols, rows)
    return mask if int(mask.sum()) >= min_area else SHAPES["rectangle"](rgen, cols, rows)
