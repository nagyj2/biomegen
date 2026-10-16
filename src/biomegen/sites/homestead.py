"""Homesteads: one building in a yard, dressed for what its owner does there (farm, mill, mine, lodge, fishery).

A homestead is the smallest site: a short track, one house nearest the middle of the extent with its door joined to the
track (or to the world's road when one passes), and the style's dressing round it: a farm's wheat field and wagon, a
mill's water wheel in the river, a mine's spoil heap, a lodge's scattered trees and felled-timber clearing, a fishery's
pier and boats. A wheat field is open ground, never roofed: seen from outside it stays wheat. It is not a settlement
plan (that would lay a street network round one house).

Every draw comes from ``rng.derive(seed, "site.homestead", ...)``, so the house is a pure function of the site seed: a
later phase can rebuild the same building as the first lot of the hamlet the homestead grows into.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .carve import nearest_true
from .dress import lay_dress
from .layout import SiteContext, layout
from .settlement import Lot, _harbour, _mill, _spec, _try_house
from .streets import lay_roads

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_STREET = (_PATH, _BRIDGE)
_HOUSE_TRIES = 120  # candidate spots tried for the house before giving up


def _track(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, col: int, row: int) -> None:
    """Lay a yard track: a short east-west path through ``(col, row)`` over free dry cells, for a door to join."""
    length = max(2, round(int(ctx.config.get("sites.homestead.track_rows")) * ctx.aspect))
    if not 0 <= row < grid.shape[0]:
        return
    for x in range(col - length, col + length + 1):
        if 0 <= x < grid.shape[1] and dry[row, x] and grid[row, x] == _VOID:
            grid[row, x] = _PATH


def _house(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    ground: np.ndarray,
    centre: tuple[int, int],
    stream: random.Random,
) -> Optional[Lot]:
    """Build the house on free dry ground nearest ``centre`` (inner ground first).

    Each candidate spot gets its own yard track laid a gap row below the house, which its door joins, so the house
    needs no room for a track beside it. When no spot takes the drawn size (a shore or a river takes most of the
    extent) the smallest house is tried, as a settlement always keeps at least one house.
    """
    lo, hi = (int(v) for v in ctx.config.get("sites.homestead.building_rows"))
    height = stream.randint(lo, hi)
    scale = ctx.aspect * float(ctx.config.get("sites.homestead.width"))
    sizes = [(height, round(height * scale)), (lo, round(0.8 * lo * ctx.aspect))]
    cx, cy = centre
    sampling = (1.0, 1.0 / ctx.aspect)
    spec = _spec(ctx)
    for height, width in sizes:
        free = dry & (grid == _VOID)
        fits = ndimage.minimum_filter(free.astype(np.uint8), size=(height, width), mode="constant", cval=0) > 0
        spots = sorted(
            (not ground[y, x], ((x - cx) / ctx.aspect) ** 2 + (y - cy) ** 2, y, x)
            for y, x in np.argwhere(fits).tolist()
        )[:_HOUSE_TRIES]
        for _, _, mid_y, mid_x in spots:
            rect = (mid_x - width // 2, mid_y - height // 2, width, height)
            trial = grid.copy()
            _track(ctx, trial, dry, mid_x, rect[1] + height + 1)
            streets = np.isin(trial, _STREET)
            if not streets.any():
                continue
            _, street_at = ndimage.distance_transform_edt(~streets, sampling=sampling, return_indices=True)
            street = (int(street_at[1][mid_y, mid_x]), int(street_at[0][mid_y, mid_x]))
            placed = _try_house(ctx, trial, dry, ground, rect, street, stream, spec)
            if placed is not None:
                grid[:] = placed[0]
                return placed[1]
    return None


@layout("homestead")
def build_homestead(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A homestead floor, seen from inside and from outside: one house, its track and its dressing."""
    rows, cols = ctx.rows, ctx.cols
    dry = ctx.patch.dry
    ground = ndimage.binary_erosion(dry, structure=np.ones((3, 3), bool), border_value=1)
    centre = nearest_true(ground, (cols // 2, rows // 2), ctx.aspect) or nearest_true(
        dry, (cols // 2, rows // 2), ctx.aspect
    )
    if centre is None:
        return None
    stream = rng.derive(ctx.seed, "site.homestead")  # one stream for the house and its dressing, in a fixed order
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    lay_roads(grid, ctx.patch)
    if ctx.dress == "fishery":
        _harbour(ctx, grid, dry, centre)
    lot = None
    if ctx.dress == "mill":  # the mill joins a street it finds: lay one below the middle first
        tallest = int(ctx.config.get("sites.homestead.building_rows")[1])
        _track(ctx, grid, dry, centre[0], min(rows - 2, centre[1] + tallest // 2 + 2))
        lot = _mill(ctx, grid, dry, ground, centre, stream)
    lot = lot or _house(ctx, grid, dry, ground, centre, stream)
    if lot is None:
        return None
    roofs = np.zeros(grid.shape, dtype=bool)
    roofs[lot.y : lot.y + lot.height, lot.x : lot.x + lot.width] |= lot.building.footprint
    lay_dress(ctx, grid, dry, roofs, (lot.x, lot.y, lot.width, lot.height), stream)
    outside = grid.copy()
    outside[roofs] = int(Cell.ROOF)
    return grid, outside
