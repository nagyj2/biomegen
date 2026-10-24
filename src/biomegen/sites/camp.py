"""Camps: a trampled clearing with a fire, tents round it, a wagon and scattered supplies.

Seen from outside (and at the roof level) a tent is a ``tent`` roof. Under it, on the ground view, the edge shows how
the canopy meets the ground: tarp (``TARP``) where it comes down to the earth, on up to three sides and more than one
cell long, a half-touching cell (``TARP_LIFT``) where a tarp's end rises off it, and a post (``POST``) wherever it
hangs clear and needs holding up. Inside that is a patch of bedrolls set in from every side (a random share of the
room, ``sites.camp.tent_bedding``), bare floor round it and, by chance (``sites.camp.tent_gear``), gear on that floor.
"""

from __future__ import annotations

import math
import random
from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .furnish import Weights, free_floor, scatter, weighted_choice
from .kinds import lay_roof
from .layout import SiteBuilding, SiteContext, layout
from .streets import lay_roads

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)


def _roof_tent(ctx: SiteContext, outside: np.ndarray, pitch: tuple[slice, slice], canvas: np.ndarray) -> SiteBuilding:
    """Roof the canvas cells of one tent's pitch (a slice pair of rows and columns) with the ``tent`` kind's roof."""
    rows, cols = pitch
    return lay_roof(
        ctx.config, outside, "tent", (cols.start, rows.start, cols.stop - cols.start, rows.stop - rows.start), canvas
    )


def _post_cells(count: int, gap: int) -> list[int]:
    """Return which of ``count`` cells along an open side hold a post, so no open run is longer than ``gap``."""
    extra = 0
    while -(-(count - extra) // (extra + 1)) > gap:  # the longest run left once ``extra`` posts are set
        extra += 1
    return [min(count - 1, max(0, round((step + 1) * (count + 1) / (extra + 1)) - 1)) for step in range(extra)]


def _ring(height: int, width: int) -> list[tuple[int, int]]:
    """Return the edge cells ``(row, column)`` of a ``height`` by ``width`` tent clockwise from its top-left corner."""
    top = [(0, x) for x in range(width)]
    right = [(y, width - 1) for y in range(1, height)]
    bottom = [(height - 1, x) for x in range(width - 2, -1, -1)]
    left = [(y, 0) for y in range(height - 2, 0, -1)]
    return top + right + bottom + left


def _supports(
    height: int, width: int, stream: random.Random, settings: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the ``(posts, tarp, lift)`` masks of a ``height`` by ``width`` tent: how its canopy meets the ground.

    One to three sides, or none, are a tarp: the canopy comes down to the ground along them (``tent_tarp_sides``). A
    corner touches the ground wherever either of its sides is a tarp, so it is a post only between two open sides.
    Where a tarp ends the canopy may rise off the ground over one more cell, half touching it (``tent_taper``: the
    ``lift`` mask). The open stretches that remain hang from posts: any held only by the ground at both ends gets a
    pole, as does any longer than ``tent_post_gap``, so a tarp needs few poles. A tent cut short by the map edge is a
    tarp round one pole.
    """
    posts = np.zeros((height, width), dtype=bool)
    tarp = np.zeros((height, width), dtype=bool)
    lift = np.zeros((height, width), dtype=bool)
    if height < 3 or width < 3:
        posts[height // 2, width // 2] = True
        tarp[:] = ~posts
        return posts, tarp, lift
    count = stream.choices(range(4), weights=[float(w) for w in settings["tent_tarp_sides"]])[0]
    tarp_sides = set(stream.sample(range(4), count))  # 0 north, 1 east, 2 south, 3 west
    ring = _ring(height, width)
    labels = []  # T tarp, P post, O open (held by nothing yet), L lifted end of a tarp
    for y, x in ring:
        touched = [side for side, on in enumerate((y == 0, x == width - 1, y == height - 1, x == 0)) if on]
        grounded = any(side in tarp_sides for side in touched)
        labels.append("T" if grounded else ("P" if len(touched) == 2 else "O"))
    taper, gap, total = float(settings["tent_taper"]), int(settings["tent_post_gap"]), len(ring)
    index = 1  # the first cell is a corner, so never open: every run of open cells has an anchor on each side
    while index < total:
        if labels[index] != "O":
            index += 1
            continue
        end = index
        while end < total and labels[end] == "O":
            end += 1
        run = list(range(index, end))
        before, after = labels[index - 1], labels[end % total]
        if len(run) >= 2 and before == "T" and stream.random() < taper:
            labels[run[0]] = "L"
            before, run = "L", run[1:]
        if len(run) >= 2 and after == "T" and stream.random() < taper:
            labels[run[-1]] = "L"
            after, run = "L", run[:-1]
        poles = _post_cells(len(run), gap) or ([len(run) // 2] if before in "TL" and after in "TL" else [])
        for pole in poles:
            labels[run[pole]] = "P"
        index = end
    masks = {"P": posts, "T": tarp, "L": lift}
    for (y, x), label in zip(ring, labels, strict=True):
        if label in masks:
            masks[label][y, x] = True
    if not posts.any():
        posts[height // 2, width // 2] = True
    return posts, tarp, lift


def _lay_tent(
    grid: np.ndarray,
    pitch: tuple[slice, slice],
    pitched: np.ndarray,
    stream: random.Random,
    settings: dict,
    gear: Weights,
) -> None:
    """Lay the inside of one tent on its ``pitch``: its posts and tarps, bedrolls, bare floor and a little gear.

    ``pitched`` marks the cells of the pitch the tent holds (the road keeps its way). The supports run round the edge
    (:func:`_supports`). The bedding is a random share of the room inside the edge cells, so it never reaches an edge
    and is not always one cell smaller than the tent; gear lies by chance on the floor left over.
    """
    height, width = pitched.shape
    posts, tarp, lift = _supports(height, width, stream, settings)
    posts &= pitched
    tarp &= pitched
    lift &= pitched
    floor = pitched & ~posts & ~tarp & ~lift
    room_h, room_w = height - 2, width - 2
    if room_h >= 1 and room_w >= 1:
        low, high = (float(share) for share in settings["tent_bedding"])
        bed_h = max(1, round(room_h * stream.uniform(low, high)))
        bed_w = max(1, round(room_w * stream.uniform(low, high)))
        top, left = 1 + stream.randint(0, room_h - bed_h), 1 + stream.randint(0, room_w - bed_w)
        bed = np.zeros_like(pitched)
        bed[top : top + bed_h, left : left + bed_w] = True
        bed &= floor
        grid[pitch][bed] = int(Cell.BED)
        floor &= ~bed
    grid[pitch][floor] = _FLOOR
    grid[pitch][tarp] = int(Cell.TARP)
    grid[pitch][lift] = int(Cell.TARP_LIFT)
    grid[pitch][posts] = int(Cell.POST)
    if gear:
        for y, x in np.argwhere(floor).tolist():
            if stream.random() < float(settings["tent_gear"]):
                grid[pitch[0].start + y, pitch[1].start + x] = int(weighted_choice(stream, gear))


@layout("camp")
def build_camp(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray, tuple[SiteBuilding, ...]]]:
    """A camp floor: clearing, campfire, tents, a wagon and supplies, all on dry ground."""
    rows, cols, aspect = ctx.rows, ctx.cols, ctx.aspect
    dry = ctx.patch.dry
    centre = nearest_true(dry, (cols // 2, rows // 2), aspect)
    if centre is None:
        return None
    cx, cy = centre
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    settings = {**ctx.config.get("sites.camp"), **ctx.config.get(f"sites.camp_{ctx.purpose}", {})}
    radius_y = max(2.0, float(settings["clearing"]) * rows)
    radius_x = min(radius_y * aspect, float(settings["clearing"]) * cols)
    ys, xs = np.ogrid[0:rows, 0:cols]
    clearing = ((xs - cx) / max(1.0, radius_x)) ** 2 + ((ys - cy) / max(1.0, radius_y)) ** 2 <= 1.0
    clearing &= dry
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    grid[clearing] = _FLOOR
    grid[cy, cx] = int(Cell.CAMPFIRE)

    tents = int(settings["min_tents"]) + int(clearing.sum()) // int(settings["tent_area_cells"])
    under_canvas = np.zeros(grid.shape, dtype=bool)
    pitches: list[tuple[slice, slice]] = []
    tent_stream = rng.derive(ctx.seed, "site.layout", ctx.floor, "tent")
    for index in range(tents):
        angle = index / max(1, tents) * 2.0 * math.pi + stream.uniform(-0.3, 0.3)
        distance = stream.uniform(0.55, 0.8)
        tent_w, tent_h = stream.choice(settings["tent_cells"])
        tx = round(cx + distance * radius_x * math.cos(angle))
        ty = round(cy + distance * radius_y * math.sin(angle))
        x0, y0 = tx - tent_w // 2, ty - tent_h // 2
        pitch = (slice(max(0, y0), min(rows, max(0, y0 + tent_h))), slice(max(0, x0), min(cols, max(0, x0 + tent_w))))
        pitched = ~ctx.patch.road[pitch]  # the road keeps its way through
        if pitched.size == 0:
            continue
        _lay_tent(grid, pitch, pitched, tent_stream, settings, ctx.weights("tent"))
        under_canvas[pitch] |= pitched
        pitches.append(pitch)
    angle = stream.uniform(0.0, 2.0 * math.pi)
    wx, wy = round(cx + 0.85 * radius_x * math.cos(angle)), round(cy + 0.85 * radius_y * math.sin(angle))
    if 0 <= wx < cols and 0 <= wy < rows:
        grid[wy, wx] = int(Cell.WAGON)

    density = max(0.04, float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.supply_density")))
    table = ctx.weights("supplies")
    furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    in_tents = [(int(x), int(y)) for y, x in np.argwhere(under_canvas).tolist()]  # a tent's gear is its own
    scatter(grid, furnish, free_floor(grid, in_tents), density, lambda r, _x, _y: weighted_choice(r, table))
    grid[~dry] = _VOID  # a tent or wagon that landed on water is gone
    grid[cy, cx] = int(Cell.CAMPFIRE)
    lay_roads(grid, ctx.patch, (_VOID, _FLOOR))  # the road runs through the clearing to the fire
    under_canvas &= ~np.isin(
        grid, (_VOID, int(Cell.WAGON), int(Cell.CAMPFIRE), int(Cell.PATH))
    )  # what a wagon or road took
    outside = grid.copy()
    buildings = tuple(
        _roof_tent(ctx, outside, pitch, under_canvas[pitch]) for pitch in pitches if under_canvas[pitch].any()
    )
    return grid, outside, buildings
