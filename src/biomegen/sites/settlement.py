"""Settlements: a street network with buildings on lots facing it, a plaza, trees and, for the big ones, a wall.

The plan is laid out streets first. A **plaza** sits at the middle of the dry ground. **Main streets** run from every
road gate to it (or, with no road, across the extent both ways), bridging water. **Side streets** branch off the mains.
Then **lots** are packed along the streets, nearest the plaza first: each lot is a free rectangle a gap from the street
it faces, filled by a thin-walled building (:mod:`.building`) whose street door faces that street. A building no street
can be joined to is not built. A settlement with a wall (``walled`` in its row) has buildings only inside it, and the
wall has a gate wherever a street crosses it. Trees and bushes fill free ground.

Seen from outside every building is a roof and the wall is solid stone; the streets and trees are as they are.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .building import Spec, build_building
from .carve import Point, nearest_true
from .layout import SiteContext, layout
from .streets import lay_roads, lay_street

_VOID = int(Cell.VOID)
_WALL = int(Cell.WALL)
_DOOR = int(Cell.DOOR)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_STREET = (_PATH, _BRIDGE)
_ROLES = ("hall", "kitchen", "bedroom", "storage")


def _plaza(ctx: SiteContext, centre: Point) -> np.ndarray:
    """Return the plaza: an ellipse about ``centre`` ``plaza_rows`` tall, widened by the cell aspect."""
    ys, xs = np.ogrid[0 : ctx.rows, 0 : ctx.cols]
    radius = max(1, ctx.plaza_rows)
    return ((xs - centre[0]) / (radius * ctx.aspect)) ** 2 + ((ys - centre[1]) / radius) ** 2 <= 1.0


def _axis_end(dry: np.ndarray, centre: Point, step: Point) -> Point:
    """Walk from ``centre`` along ``step`` over dry ground and return the last dry cell before the edge or water."""
    rows, cols = dry.shape
    x, y = centre
    while 0 <= x + step[0] < cols and 0 <= y + step[1] < rows and dry[y + step[1], x + step[0]]:
        x, y = x + step[0], y + step[1]
    return x, y


def _pitch(ctx: SiteContext) -> tuple[int, int]:
    """Return the ``(columns, rows)`` between parallel streets: a building each side of one, back to back."""
    gap_x, gap_y = (int(v) for v in ctx.setting("street_gap"))
    rows_hi = int(ctx.setting("building_rows")[1])
    return round(rows_hi * ctx.aspect * 1.6) + 2 * gap_x + ctx.vertical_width + 1, 2 * rows_hi + 2 * gap_y + 3


def _run(grid: np.ndarray, room: np.ndarray, start: Point, step: Point, width: int) -> int:
    """Paint a straight street from ``start`` along ``step`` while ``room`` allows; return how many cells it painted.

    A street that runs up and down is ``width`` columns wide so it is as thick as a horizontal one.
    """
    rows, cols = grid.shape
    x, y = start
    painted = 0
    while 0 <= x < cols and 0 <= y < rows and room[y, x] and grid[y, x] in (_VOID, _PATH):
        grid[y, x] = _PATH
        if step[0] == 0:
            for extra in range(1, width):
                if x + extra < cols and room[y, x + extra] and grid[y, x + extra] == _VOID:
                    grid[y, x + extra] = _PATH
        painted += 1
        x, y = x + step[0], y + step[1]
    return painted


def _streets(
    ctx: SiteContext, grid: np.ndarray, room: np.ndarray, dry: np.ndarray, centre: Point, stream: random.Random
) -> None:
    """Lay the street network: gates to the plaza, two axes through it, and parallel streets a block apart."""
    rules = ctx.street_rules
    settings = ctx.config.get("sites.settlement")
    width = max(1, round(ctx.aspect))
    gap_x, gap_y = (int(v) for v in ctx.setting("street_gap"))
    pitch_x, pitch_y = _pitch(ctx)
    drop, jitter = float(settings["drop"]), int(settings["jitter"])
    cx, cy = centre
    for gate in ctx.patch.gates:
        end = (gate.col, gate.row)
        if end != centre:
            lay_street(grid, dry, end, centre, rules)
    for step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        _run(grid, room, centre, step, width)
    for direction in (1, -1):
        for k in range(1, 12):
            y = cy + direction * k * pitch_y + stream.randint(-jitter, jitter)
            if 0 <= y < grid.shape[0] and stream.random() >= drop:
                for step in ((1, 0), (-1, 0)):
                    _run(grid, room, (cx + step[0], y), step, width)
            x = cx + direction * k * pitch_x + stream.randint(-jitter, jitter)
            if 0 <= x < grid.shape[1] and stream.random() >= drop:
                for step in ((0, 1), (0, -1)):
                    _run(grid, room, (x, cy + step[1]), step, width)


def _free(blocked: np.ndarray, rect: tuple[int, int, int, int], margin: tuple[int, int]) -> bool:
    """Whether ``rect = (x0, y0, x1, y1)`` (end exclusive) lies on the grid and it and its margin hold no blocked cell.

    The margin (columns, rows) is clipped to the grid: only the building itself has to be on it.
    """
    rows, cols = blocked.shape
    x0, y0, x1, y1 = rect
    if x0 < 0 or y0 < 0 or x1 > cols or y1 > rows:
        return False
    return not blocked[max(0, y0 - margin[1]) : y1 + margin[1], max(0, x0 - margin[0]) : x1 + margin[0]].any()


def _lots(
    ctx: SiteContext, grid: np.ndarray, ground: np.ndarray, centre: Point, stream: random.Random
) -> tuple[np.ndarray, list[Point]]:
    """Pack buildings along the streets; return ``(roof mask, doors' street-side cells)``."""
    settings = ctx.config.get("sites.settlement")
    gap_x, gap_y = (int(v) for v in ctx.setting("street_gap"))
    rows_lo, rows_hi = (int(v) for v in ctx.setting("building_rows"))
    aspect = ctx.aspect
    widest = _pitch(ctx)[0] - 2 * gap_x - ctx.vertical_width - 1  # a lot must fit between two parallel streets
    furniture = {role: ctx.weights(role) for role in _ROLES}
    density = float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.home_density"))
    spec = Spec(int(ctx.setting("room_rows")[0]), aspect, _ROLES, furniture, density)
    rows, cols = grid.shape
    blocked = ~ground | (grid != _VOID)
    roofs = np.zeros(grid.shape, dtype=bool)
    street = np.argwhere(np.isin(grid, _STREET))
    order = sorted(
        (tuple(int(v) for v in cell[::-1]) for cell in street[:: max(1, int(aspect))]),
        key=lambda p: (((p[0] - centre[0]) / aspect) ** 2 + (p[1] - centre[1]) ** 2, p[1], p[0]),
    )
    target = float(settings["fill"]) * int(ground.sum())
    covered = 0
    placed: list[Point] = []
    for sx, sy in order:
        if covered >= target:
            break
        run_x = int(grid[sy, min(sx + 1, cols - 1)] in _STREET) + int(grid[sy, max(sx - 1, 0)] in _STREET)
        run_y = int(grid[min(sy + 1, rows - 1), sx] in _STREET) + int(grid[max(sy - 1, 0), sx] in _STREET)
        sides = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        if run_x > run_y:
            sides = sides[:2]
        elif run_y > run_x:
            sides = sides[2:]
        stream.shuffle(sides)
        for step_x, step_y in sides:
            for attempt in range(int(settings["lot_tries"])):
                height = max(rows_lo, round(stream.randint(rows_lo, rows_hi) * (1.0 - 0.12 * attempt)))
                width = min(widest, max(round(rows_lo * aspect), round(height * aspect * stream.uniform(1.0, 1.4))))
                if step_y:
                    x0 = sx - width // 2 + stream.randint(-width // 4, width // 4)
                    y0 = sy + gap_y + 1 if step_y > 0 else sy - gap_y - height
                else:
                    y0 = sy - height // 2 + stream.randint(-height // 4, height // 4)
                    x0 = sx + gap_x + 1 if step_x > 0 else sx - gap_x - width
                if not _free(blocked, (x0, y0, x0 + width, y0 + height), (gap_x, gap_y)):
                    continue
                toward = (sx - x0, sy - y0)
                building = build_building(height, width, stream, spec, toward)
                if building is None or building.front is None:
                    continue
                front = (x0 + building.front[0], y0 + building.front[1])
                if not _join(grid, front, (sx, sy), (step_x, step_y)):
                    continue
                inside = building.cells != _VOID
                grid[y0 : y0 + height, x0 : x0 + width][inside] = building.cells[inside]
                roofs[y0 : y0 + height, x0 : x0 + width] |= building.footprint
                blocked[max(0, y0 - gap_y) : y0 + height + gap_y, max(0, x0 - gap_x) : x0 + width + gap_x] = True
                covered += int(building.footprint.sum())
                placed.append(front)
                break
            else:
                continue
            break
    return roofs, placed


def _join(grid: np.ndarray, front: Point, street: Point, side: Point) -> bool:
    """Paint the cells from a door's front to the street it faces; False if anything but free ground is between."""
    rows, cols = grid.shape
    x, y = front
    back = (-side[0], -side[1])
    cells = []
    while 0 <= x < cols and 0 <= y < rows and int(grid[y, x]) == _VOID:
        cells.append((x, y))
        x, y = x + back[0], y + back[1]
        if len(cells) > 6:
            return False
    if not (0 <= x < cols and 0 <= y < rows) or int(grid[y, x]) not in _STREET or not cells:
        return False
    for cx, cy in cells:
        grid[cy, cx] = _PATH
    return True


def _wall(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray) -> None:
    """Ring the settlement with a thin wall; a street crossing it makes a gate. Water leaves a gap."""
    inset_x, inset_y = (int(v) for v in ctx.config.get("sites.settlement.wall_inset"))
    rows, cols = grid.shape
    x0, x1, y0, y1 = inset_x, cols - 1 - inset_x, inset_y, rows - 1 - inset_y
    ring = np.zeros(grid.shape, dtype=bool)
    ring[y0 : y1 + 1, x0 : x1 + 1] = True
    ring[y0 + 1 : y1, x0 + 1 : x1] = False
    streets = np.isin(grid, _STREET)
    grid[ring & dry & (grid == _VOID)] = _WALL
    grid[ring & dry & streets] = _DOOR


def _plant(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, roofs: np.ndarray, stream: random.Random) -> None:
    """Scatter trees and bushes over free ground, keeping clear of buildings and streets."""
    share = float(ctx.config.get("sites.settlement.trees"))
    near = ndimage.binary_dilation(roofs | np.isin(grid, _STREET + (_WALL, _DOOR)), iterations=1)
    free = [(int(x), int(y)) for y, x in np.argwhere((grid == _VOID) & dry & ~near).tolist()]
    for x, y in stream.sample(free, min(len(free), int(len(free) * share))):
        grid[y, x] = int(Cell.TREE) if stream.random() < 0.7 else int(Cell.BUSH)


@layout("settlement")
def build_settlement(ctx: SiteContext) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """A settlement floor, seen from inside and from outside."""
    rows, cols = ctx.rows, ctx.cols
    dry = ctx.patch.dry
    ground = ndimage.binary_erosion(dry, structure=np.ones((3, 3), bool), border_value=1)
    centre = nearest_true(ground, (cols // 2, rows // 2), ctx.aspect)
    if centre is None:
        return None
    grid = np.full((rows, cols), _VOID, dtype=np.uint8)
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    lay_roads(grid, ctx.patch)
    grid[_plaza(ctx, centre) & dry] = _PATH
    if ctx.walled:
        inset_x, inset_y = (int(v) for v in ctx.config.get("sites.settlement.wall_inset"))
        inner = np.zeros(grid.shape, dtype=bool)
        inner[inset_y + 1 : rows - inset_y - 1, inset_x + 1 : cols - inset_x - 1] = True
        ground = ground & inner
    _streets(ctx, grid, ground, dry, centre, stream)
    roofs, _fronts = _lots(ctx, grid, ground, centre, stream)
    if ctx.walled:
        _wall(ctx, grid, dry)
    _plant(ctx, grid, dry, roofs, stream)
    outside = grid.copy()
    outside[roofs] = int(Cell.ROOF)
    outside[(grid == _WALL) & ~roofs] = int(Cell.STONE)
    outside[grid == _DOOR] = _PATH
    return grid, outside
