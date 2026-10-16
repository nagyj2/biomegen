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
from .carve import Rect, fit_rect, nearest_true
from .furnish import weighted_choice
from .layout import SiteContext, layout
from .settlement import Lot, _harbour, _mill, _spec, _try_house
from .streets import lay_roads

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_STREET = (_PATH, _BRIDGE)
_HOUSE_TRIES = 120  # candidate spots tried for the house before giving up
_SOWN = 0.94  # share of a wheat plot that is sown; the rest stays bare


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


def _yard(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, lot: Lot) -> np.ndarray:
    """Bool grid: the free dry cells within ``yard_reach`` ``[columns, rows]`` of the house (its walls excluded)."""
    reach_x, reach_y = (int(v) for v in ctx.config.get("sites.homestead.yard_reach"))
    near = np.zeros(grid.shape, dtype=bool)
    near[
        max(0, lot.y - reach_y) : lot.y + lot.height + reach_y, max(0, lot.x - reach_x) : lot.x + lot.width + reach_x
    ] = True
    return near & dry & (grid == _VOID)


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


def _plot(
    ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, lot: Lot, size: list[int]
) -> Optional[Rect]:
    """Return the free dry rectangle nearest the house of about ``size`` ``[rows, columns]``, or None.

    It keeps a cell clear of the house and the paths, and shrinks by quarters (down to half) when the full size does
    not fit, so a small extent still gets a smaller plot.
    """
    near = ndimage.binary_dilation(roofs | np.isin(grid, _STREET), iterations=1)
    free = dry & (grid == _VOID) & ~near
    middle = (lot.x + lot.width // 2, lot.y + lot.height // 2)
    for share in (1.0, 0.75, 0.5):
        rect = fit_rect(free, max(2, round(size[0] * share)), max(4, round(size[1] * share)), middle, ctx.aspect)
        if rect is not None:
            return rect
    return None


def _field(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    roofs: np.ndarray,
    lot: Lot,
    size: list[int],
    stream: random.Random,
) -> None:
    """Sow a wheat field on the plot nearest the house; a few cells are left bare so the edge is not ruled."""
    rect = _plot(ctx, grid, dry, roofs, lot, size)
    if rect is None:
        return
    x0, y0, width, height = rect
    for y in range(y0, y0 + height):
        for x in range(x0, x0 + width):
            if stream.random() < _SOWN:
                grid[y, x] = int(Cell.WHEAT)


def _clearing(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    roofs: np.ndarray,
    lot: Lot,
    size: list[int],
    logs: int,
    stream: random.Random,
) -> None:
    """Clear a working area for felled timber: bare ground with ``logs`` felled trunks lying along its rows."""
    rect = _plot(ctx, grid, dry, roofs, lot, size)
    if rect is None:
        return
    x0, y0, width, height = rect
    grid[y0 : y0 + height, x0 : x0 + width] = int(Cell.FLOOR)
    rows = stream.sample(range(y0, y0 + height), min(logs, height))
    for y in sorted(rows):
        length = stream.randint(max(2, width // 3), max(3, width - 2))
        start = x0 + stream.randint(0, width - length)
        grid[y, start : start + length] = int(Cell.LOG)


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
    if "field" in settings:
        _field(ctx, grid, dry, roofs, lot, settings["field"], stream)
    if "clearing" in settings:
        _clearing(ctx, grid, dry, roofs, lot, settings["clearing"], int(settings.get("logs", 0)), stream)
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
    _dress(ctx, grid, dry, roofs, lot, stream)
    outside = grid.copy()
    outside[roofs] = int(Cell.ROOF)
    return grid, outside
