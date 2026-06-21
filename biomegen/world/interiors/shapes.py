"""Dungeon outer-boundary shapes - the swappable algorithms that make a floorplan *not* a rectangle.

Each shape is a function ``(rgen, grid_w, grid_h) -> np.ndarray[bool]`` returning the cells that lie
*inside* the structure's footprint (the builder fills that region with rooms + rock and lets terrain
show through everywhere else, so the dungeon reads as an organic mass rather than a square block).
They register themselves in :data:`~biomegen.world.interiors.grid.SHAPES` and are selected by
``interiors.shape`` - or, with the default ``"mixed"``, the builder picks one per dungeon so no two
dungeons share a shape and none is square.

The algorithms are the standard procedural-dungeon repertoire (see RogueBasin / the literature):

* ``rectangle`` - the full footprint (the classic boxy baseline; kept for comparison/opt-out).
* ``blob``      - metaball accretion: the union of several overlapping ellipses -> a smooth, rounded,
                  lumpy mass. The bread-and-butter "irregular room cluster".
* ``cellular``  - a cellular-automata cave: random seed + Conway-style 4-5 smoothing, then keep the
                  largest cavern. The canonical organic cave generator.
* ``drunkard``  - a drunkard's walk: a random walker stamps a thick winding trail until it has
                  covered a target area -> meandering, cave-carved-by-water feel.
* ``diamond``   - a rhombus (a simple, reliably non-square geometric mask).
* ``cross``     - a plus/cross of two overlapping bars (another geometric non-square mask).

Every shape is inset by one cell (so there is always an exterior ring for the outer wall + an entrance
to punch) and reduced to a single connected component, guaranteeing a usable, traversable footprint.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .grid import SHAPES, largest_component


def _inner(gw: int, gh: int) -> np.ndarray:
    """Boolean mask of the grid interior (everything except the 1-cell border)."""
    m = np.zeros((gh, gw), dtype=bool)
    m[1 : gh - 1, 1 : gw - 1] = True
    return m


def _ellipse(gw: int, gh: int, cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    """Boolean mask of the filled ellipse centred at ``(cx, cy)`` with radii ``(rx, ry)``."""
    ys, xs = np.ogrid[0:gh, 0:gw]
    rx, ry = max(0.5, rx), max(0.5, ry)
    return ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1.0


def _neighbour_count(mask: np.ndarray) -> np.ndarray:
    """8-neighbour count of True cells (for the cellular-automata smoothing rule).

    Off-grid is counted as empty (``mode="constant"``); the cellular smoothing only reads inner cells
    (it re-applies ``& inner`` each pass), whose 3x3 windows are fully on-grid, so this matches a
    wrap-free neighbourhood exactly.
    """
    kernel = np.ones((3, 3), dtype=np.int16)
    kernel[1, 1] = 0  # exclude the cell itself
    return ndimage.convolve(mask.astype(np.int16), kernel, mode="constant", cval=0)


@SHAPES.register("rectangle")
def rectangle(rgen, gw: int, gh: int) -> np.ndarray:
    """The full footprint interior (the boxy baseline)."""
    return _inner(gw, gh)


@SHAPES.register("diamond")
def diamond(rgen, gw: int, gh: int) -> np.ndarray:
    """A rhombus: ``|x-cx|/rx + |y-cy|/ry <= 1`` (a simple reliably non-square mask)."""
    cx, cy = (gw - 1) / 2.0, (gh - 1) / 2.0
    rx, ry = (gw - 2) / 2.0, (gh - 2) / 2.0
    ys, xs = np.ogrid[0:gh, 0:gw]
    mask = np.abs(xs - cx) / max(0.5, rx) + np.abs(ys - cy) / max(0.5, ry) <= 1.0
    return mask & _inner(gw, gh)


@SHAPES.register("cross")
def cross(rgen, gw: int, gh: int) -> np.ndarray:
    """A plus/cross: the union of a vertical and a horizontal bar through the centre."""
    inner = _inner(gw, gh)
    # Each bar spans 45-65% of the perpendicular dimension, centred, with a little jitter.
    bw = max(3, int(gw * rgen.uniform(0.45, 0.65)))
    bh = max(3, int(gh * rgen.uniform(0.45, 0.65)))
    x0 = (gw - bw) // 2
    y0 = (gh - bh) // 2
    mask = np.zeros((gh, gw), dtype=bool)
    mask[:, x0 : x0 + bw] = True  # vertical bar
    mask[y0 : y0 + bh, :] = True  # horizontal bar
    return mask & inner


@SHAPES.register("blob")
def blob(rgen, gw: int, gh: int) -> np.ndarray:
    """Metaball accretion: the union of several overlapping ellipses -> a lumpy organic mass."""
    cx, cy = (gw - 1) / 2.0, (gh - 1) / 2.0
    mask = np.zeros((gh, gw), dtype=bool)
    n = rgen.randint(4, 7)
    for _ in range(n):
        # Ellipse centres cluster around the middle; radii are a healthy fraction of the grid so the
        # union is solid (no pinch-points) and large enough to hold several rooms.
        ex = cx + rgen.uniform(-0.28, 0.28) * gw
        ey = cy + rgen.uniform(-0.28, 0.28) * gh
        rx = rgen.uniform(0.18, 0.34) * gw
        ry = rgen.uniform(0.18, 0.34) * gh
        mask |= _ellipse(gw, gh, ex, ey, rx, ry)
    return largest_component(mask & _inner(gw, gh))


@SHAPES.register("cellular")
def cellular(rgen, gw: int, gh: int) -> np.ndarray:
    """A cellular-automata cave: random seed + 4-5 smoothing, biased to the centre, largest cavern.

    Classic "Cellular Automata Method for Generating Random Cave-Like Levels" (RogueBasin): seed each
    interior cell as wall/floor at random, then repeatedly set a cell solid when >= 5 of its eight
    neighbours are solid (and keep it solid at >= 4). A centre-weighted seed probability plus a final
    intersection with a generous ellipse keep the cavern compact and off the border.
    """
    inner = _inner(gw, gh)
    cx, cy = (gw - 1) / 2.0, (gh - 1) / 2.0
    ys, xs = np.ogrid[0:gh, 0:gw]
    # Centre falloff in [0,1]: ~1 at the middle, ~0 at the corners - seeds the cave toward the centre.
    falloff = 1.0 - np.sqrt(((xs - cx) / max(1.0, cx)) ** 2 + ((ys - cy) / max(1.0, cy)) ** 2)
    falloff = np.clip(falloff, 0.0, 1.0)

    alive = np.zeros((gh, gw), dtype=bool)
    for y in range(gh):
        for x in range(gw):
            if inner[y, x] and rgen.random() < 0.30 + 0.45 * float(falloff[y, x]):
                alive[y, x] = True

    for _ in range(5):  # smoothing passes
        n = _neighbour_count(alive)
        alive = ((n >= 5) | (alive & (n >= 4))) & inner

    alive &= _ellipse(gw, gh, cx, cy, 0.52 * gw, 0.52 * gh)  # trim stray edge growth
    return largest_component(alive)


@SHAPES.register("drunkard")
def drunkard(rgen, gw: int, gh: int) -> np.ndarray:
    """A drunkard's walk: a walker stamps a thick (radius-2) trail until it covers ~45% of the interior.

    Produces a meandering, cave-carved feel. The disk stamp keeps the trail wide enough to hold rooms,
    and the walk is connected by construction; the result is clipped to the interior and reduced to its
    largest component for safety.
    """
    inner = _inner(gw, gh)
    mask = np.zeros((gh, gw), dtype=bool)
    target = int(0.45 * int(inner.sum()))
    x, y = gw // 2, gh // 2
    steps, cap = 0, max(1, target) * 12
    while int(mask.sum()) < target and steps < cap:
        steps += 1
        # Stamp a radius-2 disk around the walker (clipped to the interior).
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx * dx + dy * dy <= 4:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and inner[ny, nx]:
                        mask[ny, nx] = True
        dx, dy = rgen.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        x = min(gw - 2, max(1, x + dx))
        y = min(gh - 2, max(1, y + dy))
    return largest_component(mask)
