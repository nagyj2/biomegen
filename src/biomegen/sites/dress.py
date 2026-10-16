"""Dressings: the ground cover and small works laid round a building, and the variants a condition picks from.

A dressing (a row of ``tables.dress``: a field, ...) has variants, each an existing :class:`~biomegen.world.tile.Cell`
or a look of its own with a plan cell in the reserved block ``DRESS_BASE + rank``. A site asks for the dress for its
kind in its condition (a standing site or a ruin) and the table answers by weight, so a standing field is full or
harvested and a ruin's harvested or dead. This module is the data side; the layouts lay the cells.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
from scipy import ndimage

from ..config.model import Config
from ..config.tables import DRESS_WEAR
from ..util import rng
from ..world.tile import DRESS_BASE, DRESS_SLOTS, Cell
from .carve import Rect, fit_rect
from .furnish import weighted_choice
from .layout import SiteContext


def _variants(config: Config, dress: str) -> dict[str, dict]:
    """The variants of ``dress``, by name."""
    return dict(config.get(f"tables.dress.{dress}.variants", {}))


def variant_cell(config: Config, dress: str, variant: str) -> int:
    """Return the plan cell of a variant: its existing ``cell``, else the dress block's base plus its rank."""
    row = _variants(config, dress)[variant]
    if "cell" in row:
        return int(Cell[str(row["cell"]).upper()])
    return DRESS_BASE + int(row["rank"])


def variants_for(config: Config, dress: str, condition: str, kind: str) -> list[tuple[str, float]]:
    """Return ``(variant, weight)`` for each variant of ``dress`` that may appear at POI ``kind`` in ``condition``.

    Variants are in name order; a variant with weight 0 in the condition, or whose ``kinds`` omit ``kind``, is left out.
    """
    rows = _variants(config, dress)
    return [
        (name, float(rows[name][condition]))
        for name in sorted(rows)
        if float(rows[name][condition]) > 0.0 and kind in rows[name].get("kinds", [kind])
    ]


def pick_variant(config: Config, dress: str, condition: str, kind: str, stream: random.Random) -> str:
    """Draw a variant of ``dress`` for a site of POI ``kind`` in ``condition`` (``standing`` or ``ruin``), by weight.

    Raises ``ValueError`` when no variant may appear there.
    """
    table = variants_for(config, dress, condition, kind)
    if not table:
        raise ValueError(f"no variant of dress {dress!r} may appear at a {kind} in the {condition} condition")
    roll = stream.random() * sum(weight for _name, weight in table)
    running = 0.0
    for name, weight in table:
        running += weight
        if roll < running:
            return name
    return table[-1][0]


def variant_of_cell(config: Config, cell: int) -> Optional[tuple[str, str]]:
    """Return ``(dress, variant)`` for a cell of the dress block, or None when ``cell`` is not one."""
    if not DRESS_BASE <= cell < DRESS_BASE + DRESS_SLOTS:
        return None
    rank = cell - DRESS_BASE
    for dress in sorted(config.get("tables.dress")):
        for name, row in sorted(_variants(config, dress).items()):
            if "cell" not in row and int(row["rank"]) == rank:
                return dress, name
    return None


# --- laying a dressing ----------------------------------------------------------------------------------------------
# What a homestead (and later a settlement) lays round a building: a yard, a wheat field or a felled-timber clearing
# beside it, spoil, wagons, supplies and woods. ``rect`` is the building's outer ``(x, y, width, height)``. Every draw
# is on the caller's stream, in a fixed order, so a building and its dressing are a pure function of the site seed.

_VOID = int(Cell.VOID)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_STREET = (_PATH, _BRIDGE)
_SOWN = 0.94  # share of a wheat plot that is sown; the rest stays bare


def yard(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, rect: Rect) -> np.ndarray:
    """Bool grid: the free dry cells within ``sites.homestead.yard_reach`` ``[columns, rows]`` of the building."""
    reach_x, reach_y = (int(v) for v in ctx.config.get("sites.homestead.yard_reach"))
    x, y, width, height = rect
    near = np.zeros(grid.shape, dtype=bool)
    near[max(0, y - reach_y) : y + height + reach_y, max(0, x - reach_x) : x + width + reach_x] = True
    return near & dry & (grid == _VOID)


def sample(mask: np.ndarray, count: int, stream: random.Random) -> list[tuple[int, int]]:
    """Up to ``count`` cells of ``mask`` as ``(x, y)``, drawn from the row-major list so the result is deterministic."""
    cells = [(int(x), int(y)) for y, x in np.argwhere(mask).tolist()]
    return stream.sample(cells, min(count, len(cells)))


def supplies(ctx: SiteContext, grid: np.ndarray, free: np.ndarray, count: int, stream: random.Random) -> None:
    """Scatter barrels, crates and the like (the family's ``yard`` role) over the free cells of ``free``."""
    table = ctx.weights("yard")
    if not table:
        return
    for x, y in sample(free & (grid == _VOID), count, stream):
        grid[y, x] = int(weighted_choice(stream, table))


def plot(
    ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, rect: Rect, size: list[int]
) -> Optional[Rect]:
    """Return the free dry rectangle nearest the building of about ``size`` ``[rows, columns]``, or None.

    It keeps a cell clear of the building and the paths, and shrinks by quarters (down to half) when the full size does
    not fit, so a small extent still gets a smaller plot.
    """
    near = ndimage.binary_dilation(roofs | np.isin(grid, _STREET), iterations=1)
    free = dry & (grid == _VOID) & ~near
    x, y, width, height = rect
    middle = (x + width // 2, y + height // 2)
    for share in (1.0, 0.75, 0.5):
        found = fit_rect(free, max(2, round(size[0] * share)), max(4, round(size[1] * share)), middle, ctx.aspect)
        if found is not None:
            return found
    return None


def field(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    roofs: np.ndarray,
    rect: Rect,
    size: list[int],
    stream: random.Random,
    condition: Optional[str] = None,
) -> None:
    """Sow a field on the plot nearest the building; a few cells are left bare so the edge is not ruled.

    With a ``condition`` (``standing`` or ``ruin``) each row of the field is one variant of ``tables.dress.field``,
    for the site's kind (full or harvested, or in a ruin harvested or dead); without, every row is full wheat.
    """
    found = plot(ctx, grid, dry, roofs, rect, size)
    if found is None:
        return
    x0, y0, width, height = found
    for y in range(y0, y0 + height):
        cell = int(Cell.WHEAT)
        if condition is not None:
            cell = variant_cell(ctx.config, "field", pick_variant(ctx.config, "field", condition, ctx.kind, stream))
        for x in range(x0, x0 + width):
            if stream.random() < _SOWN:
                grid[y, x] = cell


def clearing(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    roofs: np.ndarray,
    rect: Rect,
    size: list[int],
    logs: int,
    stream: random.Random,
) -> None:
    """Clear a working area for felled timber: bare ground with ``logs`` felled trunks lying along its rows."""
    found = plot(ctx, grid, dry, roofs, rect, size)
    if found is None:
        return
    x0, y0, width, height = found
    grid[y0 : y0 + height, x0 : x0 + width] = int(Cell.FLOOR)
    rows = stream.sample(range(y0, y0 + height), min(logs, height))
    for y in sorted(rows):
        length = stream.randint(max(2, width // 3), max(3, width - 2))
        start = x0 + stream.randint(0, width - length)
        grid[y, start : start + length] = int(Cell.LOG)


def spoil(grid: np.ndarray, free: np.ndarray, count: int, stream: random.Random) -> None:
    """Heap spoil (rock and rubble) in a cluster on one side of the free cells of ``free``."""
    cells = [(int(x), int(y)) for y, x in np.argwhere(free & (grid == _VOID)).tolist()]
    if not cells:
        return
    ax, ay = stream.choice(cells)
    cells.sort(key=lambda c: ((c[0] - ax) / 2.0) ** 2 + (c[1] - ay) ** 2)
    for x, y in cells[:count]:
        grid[y, x] = int(Cell.ROCK) if stream.random() < 0.5 else int(Cell.RUBBLE)


def wagon(grid: np.ndarray, free: np.ndarray, stream: random.Random) -> None:
    """Park one wagon on a free cell."""
    for x, y in sample(free & (grid == _VOID), 1, stream):
        grid[y, x] = int(Cell.WAGON)


def woods(grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, share: float, stream: random.Random) -> None:
    """Plant trees and bushes over ``share`` of the free ground, clear of the buildings and the paths."""
    near = ndimage.binary_dilation(roofs | np.isin(grid, _STREET), iterations=1)
    free = dry & (grid == _VOID) & ~near
    for x, y in sample(free, int(free.sum() * share), stream):
        grid[y, x] = int(Cell.TREE) if stream.random() < 0.7 else int(Cell.BUSH)


class Dressing:
    """The cells each dressing laid, by dress name (``tables.dress`` row): what a ruin's fall pass wears."""

    def __init__(self, shape: tuple[int, int]) -> None:
        self.shape = shape
        self.cells: dict[str, np.ndarray] = {}

    def add(self, name: str, mask: np.ndarray) -> None:
        """Note the cells of ``mask`` as laid by the dressing ``name``."""
        self.cells[name] = self.cells.get(name, np.zeros(self.shape, dtype=bool)) | mask

    def note(self, name: str, before: np.ndarray, grid: np.ndarray, only: Optional[tuple[int, ...]] = None) -> None:
        """Note the cells of ``grid`` that differ from ``before`` (and, with ``only``, hold one of those cells)."""
        changed = grid != before
        self.add(name, changed if only is None else changed & np.isin(grid, only))


def wear_dress(ctx: SiteContext, grid: np.ndarray, dressing: Dressing) -> None:
    """Wear every dressing of a ruin: each of its cells goes bare, to rubble or overgrown by the dress row's ``wear``.

    The shares are those of full wear (``tables.dress.<name>.wear``) times how far the ruin has worn (its erosion over
    ``sites.ruin_erosion``). Bare ground shows the natural terrain, so a worn dressing fades back into it; overgrown
    cells become trees and bushes. Draws are on their own streams (``site.erode`` ``dress``), so nothing else moves.
    """
    fall = ctx.fall
    assert fall is not None
    wear = min(1.0, fall.erosion / float(ctx.config.get("sites.ruin_erosion")))
    for name in sorted(dressing.cells):
        shares = ctx.config.get(f"tables.dress.{name}.wear", {})
        void, rubble, grown = (float(shares.get(key, 0.0)) * wear for key in DRESS_WEAR)
        stream = rng.derive_numpy(ctx.seed, "site.erode", "dress", name)
        roll, pick = stream.random(grid.shape), stream.random(grid.shape)
        mask = dressing.cells[name]
        gone = mask & (roll < void)
        fallen = mask & (roll >= void) & (roll < void + rubble)
        grew = mask & (roll >= void + rubble) & (roll < void + rubble + grown)
        grid[gone] = _VOID
        grid[fallen] = int(Cell.RUBBLE)
        grid[grew] = np.where(pick[grew] < 0.7, int(Cell.TREE), int(Cell.BUSH))


def lay_dress(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    roofs: np.ndarray,
    rect: Rect,
    stream: random.Random,
    *,
    condition: Optional[str] = None,
    plant: bool = True,
    dressing: Optional[Dressing] = None,
) -> None:
    """Dress a building for its style: ``ctx.dress`` names a row of ``sites.homestead.dress``.

    ``condition`` (``standing`` or ``ruin``) picks the field's variants (None: full wheat); ``plant`` False leaves the
    woods out (a settlement plants its own); ``dressing`` notes the cells each element laid, for a ruin's wear.
    """
    settings = ctx.config.get("sites.homestead.dress").get(ctx.dress, {})
    before = grid.copy() if dressing is not None else grid
    if "field" in settings:
        field(ctx, grid, dry, roofs, rect, settings["field"], stream, condition)
        if dressing is not None:
            dressing.note("field", before, grid)
            before = grid.copy()
    if "clearing" in settings:
        clearing(ctx, grid, dry, roofs, rect, settings["clearing"], int(settings.get("logs", 0)), stream)
        if dressing is not None:
            dressing.note("clearing", before, grid)
            before = grid.copy()
    free = yard(ctx, grid, dry, rect)
    if int(settings.get("spoil", 0)):
        spoil(grid, free, int(settings["spoil"]), stream)
        if dressing is not None:
            dressing.note("spoil", before, grid)
            before = grid.copy()
    for _ in range(int(settings.get("wagons", 0))):
        wagon(grid, free, stream)
    if dressing is not None:
        dressing.note("wagon", before, grid)
        before = grid.copy()
    supplies(ctx, grid, yard(ctx, grid, dry, rect), int(settings.get("supplies", 0)), stream)
    if dressing is not None:
        dressing.note("supplies", before, grid)
    if plant:
        share = float(settings.get("trees", ctx.config.get("sites.homestead.trees")))
        woods(grid, dry, roofs, share, stream)
