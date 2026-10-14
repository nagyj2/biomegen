"""Camps: a trampled clearing with a fire, tents round it, a wagon and scattered supplies."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .furnish import free_floor, scatter, weighted_choice
from .layout import SiteContext, layout
from .streets import lay_street

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)


@layout("camp")
def build_camp(ctx: SiteContext) -> Optional[np.ndarray]:
    """A camp floor: clearing, campfire, tents, a wagon and supplies, all on dry ground."""
    rows, cols, aspect = ctx.rows, ctx.cols, ctx.aspect
    dry = ctx.patch.dry
    centre = nearest_true(dry, (cols // 2, rows // 2), aspect)
    if centre is None:
        return None
    cx, cy = centre
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    settings = ctx.config.get("sites.camp")
    radius_y = max(2.0, float(settings["clearing"]) * rows)
    radius_x = min(radius_y * aspect, float(settings["clearing"]) * cols)
    ys, xs = np.ogrid[0:rows, 0:cols]
    clearing = ((xs - cx) / max(1.0, radius_x)) ** 2 + ((ys - cy) / max(1.0, radius_y)) ** 2 <= 1.0
    clearing &= dry
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    grid[clearing] = _FLOOR
    grid[cy, cx] = int(Cell.CAMPFIRE)

    tents = int(settings["min_tents"]) + int(clearing.sum()) // int(settings["tent_area_cells"])
    for index in range(tents):
        angle = index / max(1, tents) * 2.0 * math.pi + stream.uniform(-0.3, 0.3)
        distance = stream.uniform(0.55, 0.8)
        tent_w, tent_h = stream.choice(settings["tent_cells"])
        tx = round(cx + distance * radius_x * math.cos(angle))
        ty = round(cy + distance * radius_y * math.sin(angle))
        x0, y0 = tx - tent_w // 2, ty - tent_h // 2
        grid[max(0, y0) : max(0, y0 + tent_h), max(0, x0) : max(0, x0 + tent_w)] = int(Cell.TENT)
    angle = stream.uniform(0.0, 2.0 * math.pi)
    wx, wy = round(cx + 0.85 * radius_x * math.cos(angle)), round(cy + 0.85 * radius_y * math.sin(angle))
    if 0 <= wx < cols and 0 <= wy < rows:
        grid[wy, wx] = int(Cell.WAGON)

    density = max(0.04, float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.supply_density")))
    table = [(Cell[name.upper()], weight) for name, weight in ctx.furniture]
    furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    scatter(grid, furnish, free_floor(grid), density, lambda r, _x, _y: weighted_choice(r, table))
    grid[~dry] = _VOID  # a tent or wagon that landed on water is gone
    grid[cy, cx] = int(Cell.CAMPFIRE)
    if ctx.patch.gates:
        gate = ctx.patch.gates[0]
        edge = nearest_true(clearing, (gate.col, gate.row), aspect)
        if edge is not None:
            lay_street(grid, dry, (gate.col, gate.row), edge, ctx.street_rules)
    return grid
