"""Camps: a trampled clearing with a fire, tents round it, a wagon and scattered supplies.

Seen from outside (and at the roof level) a tent is a ``tent`` roof. Under it the inside is bedrolls filling the tent,
with the doorway at the end that faces the fire left as bare floor.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .furnish import free_floor, scatter, weighted_choice
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
        grid[pitch][pitched] = int(Cell.BED)
        door_column = pitch[1].start if cx < (pitch[1].start + pitch[1].stop) / 2 else pitch[1].stop - 1
        door = pitched[:, door_column - pitch[1].start]  # the end that faces the fire is open
        grid[pitch[0], door_column][door] = _FLOOR
        under_canvas[pitch] |= pitched
        pitches.append(pitch)
    angle = stream.uniform(0.0, 2.0 * math.pi)
    wx, wy = round(cx + 0.85 * radius_x * math.cos(angle)), round(cy + 0.85 * radius_y * math.sin(angle))
    if 0 <= wx < cols and 0 <= wy < rows:
        grid[wy, wx] = int(Cell.WAGON)

    density = max(0.04, float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.supply_density")))
    table = ctx.weights("supplies")
    furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(grid, furnish, free_floor(grid), density, lambda r, _x, _y: weighted_choice(r, table))
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
