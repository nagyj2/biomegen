"""Homesteads: one building in a yard, dressed for what its owner does there (farm, mill, mine, lodge, fishery).

A homestead is the smallest site: a short track, one house nearest the middle of the extent with its door joined to the
track (or to the world's road when one passes), and the style's dressing round it from existing cells only: a farm's
hedge and wagon, a mill's water wheel in the river, a mine's spoil heap, a lodge's woodland, a fishery's pier and boats.
It is not a settlement plan (that would lay a street network round one house).

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
from .furnish import weighted_choice
from .layout import SiteContext, layout
from .settlement import Lot, _harbour, _mill, _spec, _try_house
from .streets import lay_roads

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_STREET = (_PATH, _BRIDGE)
_HOUSE_TRIES = 40  # candidate spots tried for the house before giving up
_HEDGE_GAP_ROWS = 3.0  # clear screen distance (rows) kept in the hedge on each side of the door


def _track(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, centre: tuple[int, int]) -> None:
    """Lay the yard track: a short east-west path through the middle of the extent, the street the house joins."""
    cfg = ctx.config.get("sites.homestead")
    length = max(2, round(int(cfg["track_rows"]) * ctx.aspect))
    cx, cy = centre
    for x in range(cx - length, cx + length + 1):
        if 0 <= x < grid.shape[1] and dry[cy, x] and grid[cy, x] == _VOID:
            grid[cy, x] = _PATH


def _house(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    ground: np.ndarray,
    centre: tuple[int, int],
    stream: random.Random,
) -> Optional[Lot]:
    """Build the house on free dry ground nearest ``centre`` (inner ground first), its door joined to the track."""
    streets = np.isin(grid, _STREET)
    if not streets.any():
        return None
    lo, hi = (int(v) for v in ctx.config.get("sites.homestead.building_rows"))
    height = stream.randint(lo, hi)
    width = round(height * ctx.aspect * float(ctx.config.get("sites.homestead.width")))
    free = dry & (grid == _VOID)
    fits = ndimage.minimum_filter(free.astype(np.uint8), size=(height, width), mode="constant", cval=0) > 0
    cx, cy = centre
    spots = sorted(
        (not ground[y, x], ((x - cx) / ctx.aspect) ** 2 + (y - cy) ** 2, y, x) for y, x in np.argwhere(fits).tolist()
    )[:_HOUSE_TRIES]
    sampling = (1.0, 1.0 / ctx.aspect)
    _, street_at = ndimage.distance_transform_edt(~streets, sampling=sampling, return_indices=True)
    spec = _spec(ctx)
    for _, _, mid_y, mid_x in spots:
        rect = (mid_x - width // 2, mid_y - height // 2, width, height)
        street = (int(street_at[1][mid_y, mid_x]), int(street_at[0][mid_y, mid_x]))
        placed = _try_house(ctx, grid, dry, ground, rect, street, stream, spec)
        if placed is not None:
            grid[:] = placed[0]
            return placed[1]
    return None


def _yard(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, lot: Lot) -> np.ndarray:
    """Bool grid: the free dry cells within ``yard_reach`` ``[columns, rows]`` of the house (its walls excluded)."""
    reach_x, reach_y = (int(v) for v in ctx.config.get("sites.homestead.yard_reach"))
    near = np.zeros(grid.shape, dtype=bool)
    near[
        max(0, lot.y - reach_y) : lot.y + lot.height + reach_y, max(0, lot.x - reach_x) : lot.x + lot.width + reach_x
    ] = True
    return near & dry & (grid == _VOID)


def _put(grid: np.ndarray, cells: list[tuple[int, int]], cell: int) -> None:
    for x, y in cells:
        grid[y, x] = cell


def _sample(mask: np.ndarray, count: int, stream: random.Random) -> list[tuple[int, int]]:
    """Up to ``count`` cells of ``mask`` as ``(x, y)``, drawn from the row-major list so the result is deterministic."""
    cells = [(int(x), int(y)) for y, x in np.argwhere(mask).tolist()]
    return stream.sample(cells, min(count, len(cells)))


def _supplies(ctx: SiteContext, grid: np.ndarray, yard: np.ndarray, count: int, stream: random.Random) -> None:
    """Scatter barrels, crates and the like (the family's ``yard`` role) over the yard."""
    table = ctx.weights("yard")
    if not table:
        return
    for x, y in _sample(yard & (grid == _VOID), count, stream):
        grid[y, x] = int(weighted_choice(stream, table))


def _hedge(ctx: SiteContext, grid: np.ndarray, yard: np.ndarray, lot: Lot, stream: random.Random) -> None:
    """Ring the yard with a hedge of bushes, leaving a gap by the door."""
    outer = yard & ~ndimage.binary_erosion(yard, structure=np.ones((3, 3), bool), border_value=0)
    front = lot.building.front
    for y, x in np.argwhere(outer & (grid == _VOID)).tolist():
        if front is not None:
            fx, fy = lot.x + front[0], lot.y + front[1]
            if (((x - fx) / ctx.aspect) ** 2 + (y - fy) ** 2) ** 0.5 < _HEDGE_GAP_ROWS:
                continue
        if stream.random() < 0.9:
            grid[y, x] = int(Cell.BUSH)


def _spoil(grid: np.ndarray, yard: np.ndarray, count: int, stream: random.Random) -> None:
    """Heap spoil (rock and rubble) in a cluster on one side of the yard."""
    cells = [(int(x), int(y)) for y, x in np.argwhere(yard & (grid == _VOID)).tolist()]
    if not cells:
        return
    ax, ay = stream.choice(cells)
    cells.sort(key=lambda c: ((c[0] - ax) / 2.0) ** 2 + (c[1] - ay) ** 2)
    for x, y in cells[:count]:
        grid[y, x] = int(Cell.ROCK) if stream.random() < 0.5 else int(Cell.RUBBLE)


def _wagon(grid: np.ndarray, yard: np.ndarray, stream: random.Random) -> None:
    for x, y in _sample(yard & (grid == _VOID), 1, stream):
        grid[y, x] = int(Cell.WAGON)


def _woods(grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, share: float, stream: random.Random) -> None:
    """Plant trees and bushes over the free ground, clear of the house and the paths."""
    near = ndimage.binary_dilation(roofs | np.isin(grid, _STREET), iterations=1)
    free = dry & (grid == _VOID) & ~near
    for x, y in _sample(free, int(free.sum() * share), stream):
        grid[y, x] = int(Cell.TREE) if stream.random() < 0.7 else int(Cell.BUSH)


def _dress(
    ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, lot: Lot, stream: random.Random
) -> None:
    """Dress the homestead for its style: ``ctx.dress`` names a row of ``sites.homestead.dress``."""
    settings = ctx.config.get("sites.homestead.dress").get(ctx.dress, {})
    yard = _yard(ctx, grid, dry, lot)
    if settings.get("hedge"):
        _hedge(ctx, grid, yard, lot, stream)
        yard = _yard(ctx, grid, dry, lot)
    if int(settings.get("spoil", 0)):
        _spoil(grid, yard, int(settings["spoil"]), stream)
    for _ in range(int(settings.get("wagons", 0))):
        _wagon(grid, yard, stream)
    _supplies(ctx, grid, _yard(ctx, grid, dry, lot), int(settings.get("supplies", 0)), stream)
    share = float(settings.get("trees", ctx.config.get("sites.homestead.trees")))
    _woods(grid, dry, roofs, share, stream)


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
    _track(ctx, grid, dry, centre)
    if ctx.dress == "fishery":
        _harbour(ctx, grid, dry, centre)
    lot = _mill(ctx, grid, dry, ground, centre, stream) if ctx.dress == "mill" else None
    lot = lot or _house(ctx, grid, dry, ground, centre, stream)
    if lot is None:
        return None
    roofs = np.zeros(grid.shape, dtype=bool)
    roofs[lot.y : lot.y + lot.height, lot.x : lot.x + lot.width] |= lot.building.footprint
    _dress(ctx, grid, dry, roofs, lot, stream)
    outside = grid.copy()
    outside[roofs] = int(Cell.ROOF)
    return grid, outside
