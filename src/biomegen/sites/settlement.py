"""Settlements: an irregular town with winding streets, lots, a plaza, trees and, for the big ones, a wall.

The **outline** is organic: a wobbling closed curve round the middle of the dry ground, stretched along the roads that
reach it. Inside it the street network is laid out as a medieval town grows: a **plaza** at the middle, **spokes**
running from it out to the edge (every road gate is one), partial **rings** round it, and **lanes** from the nearest
street into any ground still too far from one. Then **lots** are packed along the streets, nearest the plaza first:
each lot is a free rectangle a gap from the street it faces, filled by a thin-walled building (:mod:`.building`) whose
street door faces that street. A building no street can be joined to is not built. A settlement with a wall
(``walled`` in its row) is ringed along its outline, with a gate wherever a spoke or the road reaches it. Trees and
bushes fill free ground. A port builds a harbour (a pier, boats and a street to the plaza) where open water lies by the
town, and a river settlement a mill with a water wheel in the river (``sites.settlement.harbour`` and ``mill``).

Seen from outside every building is a roof and the wall is solid stone; the streets and trees are as they are. An upper
floor is the ground view with the buildings in it replaced: the storey of each building that reaches that floor, the
roof of each that does not (the current floor laid over all the lower ones). Streets, trees and the wall stay. The
world's road is laid in first (:func:`.streets.lay_roads`), so the town grows round and onto it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .boat import moor_boat
from .building import Building, Spec, build_building
from .carve import Point, nearest_true
from .layout import SiteContext, layout
from .streets import lay_roads, lay_street
from .structure import breach

_VOID = int(Cell.VOID)
_WALL = int(Cell.WALL)
_DOOR = int(Cell.DOOR)
_PATH = int(Cell.PATH)
_BRIDGE = int(Cell.BRIDGE)
_FLOOR = int(Cell.FLOOR)
_UP = int(Cell.STAIRS_UP)
_DOWN = int(Cell.STAIRS_DOWN)
_STREET = (_PATH, _BRIDGE)
_ROLES = ("hall", "kitchen", "bedroom", "storage")
_MIN_TOWN = 0.2  # a footprint smaller than this share of the extent falls back to the whole extent
_RUBBLE = int(Cell.RUBBLE)
_RING_STEP = 0.5  # radians between the sample points of a ring street
_WHEEL = int(Cell.WHEEL)
_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))
_MILL_TRIES = 40  # candidate spots tried for a mill before giving up
_SLIVER_PASSES = 2  # passes that pave bare strips between streets


@dataclass(frozen=True)
class Lot:
    """A building placed on the ground floor.

    Attributes:
        x: Column of its top-left cell.
        y: Row of its top-left cell.
        width: Its outer width in cells.
        height: Its outer height in cells.
        shape_seed: Seeds its footprint, so every storey of it has the same outline.
        building: Its ground floor.
    """

    x: int
    y: int
    width: int
    height: int
    shape_seed: int
    building: Building


def _spec(ctx: SiteContext) -> Spec:
    """What a settlement building is built to: homes, furnished at the home density."""
    furniture = {role: ctx.weights(role) for role in _ROLES}
    density = float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.home_density"))
    return Spec(int(ctx.setting("room_rows")[0]), ctx.aspect, _ROLES, furniture, density)


def _block(ctx: SiteContext) -> int:
    """Rows between two parallel streets: a lot's depth, its gap to the street, and a lane's width."""
    rows_hi = int(ctx.setting("building_rows")[1])
    return rows_hi + 2 * int(ctx.setting("street_gap")[1]) + 2


def _plaza(ctx: SiteContext, centre: Point, stream: random.Random) -> np.ndarray:
    """Return the plaza: a lumpy ellipse about ``centre`` ``plaza_rows`` tall, widened by the cell aspect."""
    ys, xs = np.ogrid[0 : ctx.rows, 0 : ctx.cols]
    radius = max(1, ctx.plaza_rows)
    u, v = (xs - centre[0]) / ctx.aspect, (ys - centre[1]).astype(float)
    lump = 1.0 + 0.2 * np.sin(3.0 * np.arctan2(v, u) + stream.uniform(0.0, 2.0 * math.pi))
    return np.hypot(u, v) <= radius * lump


def _tidy(town: np.ndarray, centre: Point) -> np.ndarray:
    """Round off thin spurs, keep the piece holding ``centre`` and fill its holes."""
    opened = ndimage.binary_opening(town, structure=np.ones((3, 3), bool))
    labels, count = ndimage.label(opened)
    if count == 0 or labels[centre[1], centre[0]] == 0:
        return town
    return ndimage.binary_fill_holes(labels == labels[centre[1], centre[0]])


def _outline(ctx: SiteContext, centre: Point, inner: np.ndarray, stream: random.Random) -> np.ndarray:
    """Return the settlement's footprint: a wobbling curve round ``centre`` that bulges towards each road gate.

    ``inner`` is where the footprint may lie (inside the extent, a margin in from its edge).
    """
    rows, cols = inner.shape
    cx, cy = centre
    settings = ctx.config.get("sites.settlement")
    ys, xs = np.mgrid[0:rows, 0:cols]
    u, v = (xs - cx) / ctx.aspect, (ys - cy).astype(float)
    theta = np.arctan2(v, u)
    reach_x, reach_y = max(1.0, cols / ctx.aspect / 2.0), max(1.0, rows / 2.0)
    scale = np.ones(inner.shape)
    for harmonic, amplitude in enumerate(settings["wobble"], start=1):
        scale = scale + float(amplitude) * np.sin(harmonic * theta + stream.uniform(0.0, 2.0 * math.pi))
    for gate in ctx.patch.gates:
        delta = (theta - math.atan2(gate.row - cy, (gate.col - cx) / ctx.aspect) + math.pi) % (2.0 * math.pi) - math.pi
        scale = scale + float(settings["road_stretch"]) * np.exp(-((delta / 0.5) ** 2))
    town = np.hypot(u / reach_x, v / reach_y) <= float(settings["radius"]) * scale
    town = _tidy(town & inner, centre)
    return town if int(town.sum()) >= _MIN_TOWN * int(inner.sum()) else inner


def _edge(town: np.ndarray, dry: np.ndarray, centre: Point, angle: float, aspect: float) -> Point:
    """Walk from ``centre`` along ``angle`` while on dry ground in the footprint; return the last cell."""
    rows, cols = town.shape
    last = centre
    for step in range(1, 4 * (rows + cols)):
        x = round(centre[0] + math.cos(angle) * aspect * step * 0.5)
        y = round(centre[1] + math.sin(angle) * step * 0.5)
        if not (0 <= x < cols and 0 <= y < rows and town[y, x] and dry[y, x]):
            break
        last = (x, y)
    return last


def _bend(ctx: SiteContext, centre: Point, end: Point, town: np.ndarray, stream: random.Random) -> Point:
    """Return a waypoint off the line from ``centre`` to ``end`` so a street meanders."""
    du, dv = (end[0] - centre[0]) / ctx.aspect, float(end[1] - centre[1])
    length = math.hypot(du, dv)
    if length < 1.0:
        return end
    offset = stream.uniform(-0.2, 0.2) * length
    mu, mv = 0.5 * du - dv / length * offset, 0.5 * dv + du / length * offset
    x, y = round(centre[0] + mu * ctx.aspect), round(centre[1] + mv)
    if 0 <= x < town.shape[1] and 0 <= y < town.shape[0] and town[y, x]:
        return x, y
    return round(centre[0] + 0.5 * du * ctx.aspect), round(centre[1] + 0.5 * dv)


def _spokes(
    ctx: SiteContext,
    grid: np.ndarray,
    town: np.ndarray,
    dry: np.ndarray,
    centre: Point,
    stream: random.Random,
) -> list[Point]:
    """Lay streets from the plaza out to the footprint's edge, towards every gate and a few more; return their ends."""
    cx, cy = centre
    taken = [math.atan2(g.row - cy, (g.col - cx) / ctx.aspect) for g in ctx.patch.gates]
    low, high = (int(v) for v in ctx.config.get("sites.settlement.spokes"))
    radius = max(1.0, math.sqrt(float(np.count_nonzero(town)) / math.pi / ctx.aspect))  # in rows
    count = min(stream.randint(low, high), max(2, int(2.0 * math.pi * 0.7 * radius / _block(ctx))))
    start = stream.uniform(0.0, 2.0 * math.pi)
    angles = list(taken)
    for index in range(count):
        angle = start + 2.0 * math.pi * index / count + stream.uniform(-0.3, 0.3)
        if all(abs((angle - other + math.pi) % (2.0 * math.pi) - math.pi) > 0.6 for other in angles):
            angles.append(angle)
    ends = []
    for angle in angles:
        end = _edge(town, dry, centre, angle, ctx.aspect)
        if end == centre:
            continue
        _polyline(grid, town & dry, [centre, _bend(ctx, centre, end, town, stream), end], ctx.vertical_width, stream)
        ends.append(end)
    return ends


def _rings(
    ctx: SiteContext,
    grid: np.ndarray,
    town: np.ndarray,
    dry: np.ndarray,
    centre: Point,
    stream: random.Random,
) -> None:
    """Lay partial ring streets round the plaza, each a run of arcs that wander in and out a little."""
    settings = ctx.config.get("sites.settlement")
    radius = math.sqrt(float(np.count_nonzero(town)) / math.pi / ctx.aspect)  # the footprint's mean radius, in rows
    fractions, last = [], float(ctx.plaza_rows)
    for fraction in (float(f) for f in settings["rings"]):
        if fraction * radius - last >= _block(ctx) and (1.0 - fraction) * radius >= _block(ctx) / 2.0:
            fractions.append(fraction)
            last = fraction * radius
    for fraction in fractions:
        start = stream.uniform(0.0, _RING_STEP)
        points: list[Optional[Point]] = []
        angle = start
        while angle < start + 2.0 * math.pi:
            edge = _edge(town, dry, centre, angle, ctx.aspect)
            f = fraction * stream.uniform(0.9, 1.1)
            point = (round(centre[0] + f * (edge[0] - centre[0])), round(centre[1] + f * (edge[1] - centre[1])))
            inside = 0 <= point[0] < town.shape[1] and 0 <= point[1] < town.shape[0]
            points.append(point if inside and town[point[1], point[0]] and dry[point[1], point[0]] else None)
            angle += _RING_STEP
        for a, b in zip(points, points[1:], strict=False):
            if a is not None and b is not None and stream.random() >= float(settings["ring_gap"]):
                _polyline(grid, town & dry, [a, b], ctx.vertical_width, stream)


def _segment(grid: np.ndarray, room: np.ndarray, a: Point, b: Point, width: int) -> None:
    """Paint an axis-aligned street from ``a`` to ``b`` (columns ``width`` wide when it runs up and down).

    Only free ground in ``room`` is painted: a street runs through existing streets and stops at anything else.
    """
    rows, cols = grid.shape
    (ax, ay), (bx, by) = a, b
    for y in range(min(ay, by), max(ay, by) + 1):
        for x in range(min(ax, bx), max(ax, bx) + 1):
            for extra in range(width if ax == bx and ay != by else 1):
                cx = x + extra
                if 0 <= cx < cols and 0 <= y < rows and room[y, cx] and grid[y, cx] == _VOID:
                    grid[y, cx] = _PATH


def _polyline(grid: np.ndarray, room: np.ndarray, points: list[Point], width: int, stream: random.Random) -> None:
    """Paint a street through ``points``, joining each pair with an L (across then up or down, or the other way)."""
    for a, b in zip(points, points[1:], strict=False):
        corner = (b[0], a[1]) if stream.random() < 0.5 else (a[0], b[1])
        _segment(grid, room, a, corner, width)
        _segment(grid, room, corner, b, width)


def _lanes(ctx: SiteContext, grid: np.ndarray, ground: np.ndarray, town: np.ndarray, stream: random.Random) -> None:
    """Branch lanes off the nearest street into any ground too far from one for a lot to face it.

    A lane runs from the street cell nearest the farthest bit of ground out to that spot, so lanes fan into the gaps
    like the side streets of an old town. Lots need ``building_rows`` deep of ground beside a street, so ground
    farther than the shallowest building is served.
    """
    rows_lo = int(ctx.setting("building_rows")[0])
    reach = float(rows_lo + int(ctx.setting("street_gap")[1]) + 1)  # in rows
    street = np.isin(grid, _STREET)
    if not street.any():
        return
    sampling = (1.0, 1.0 / ctx.aspect)
    distance, nearest = ndimage.distance_transform_edt(~street, sampling=sampling, return_indices=True)
    far = np.where(ground, distance, 0.0)
    room = town & (grid == _VOID) | street
    for _ in range(int(ctx.config.get("sites.settlement.max_lanes"))):
        y, x = np.unravel_index(int(np.argmax(far)), far.shape)
        if far[y, x] <= reach:
            return
        start = (int(nearest[1][y, x]), int(nearest[0][y, x]))
        _polyline(grid, room, [start, (int(x), int(y))], ctx.vertical_width, stream)
        y0, y1 = max(0, y - int(2 * reach) - 4), min(far.shape[0], y + int(2 * reach) + 5)
        x0, x1 = max(0, x - int(4 * reach * ctx.aspect)), min(far.shape[1], x + int(4 * reach * ctx.aspect) + 1)
        near = np.isin(grid[y0:y1, x0:x1], _STREET)
        if near.any():
            local = ndimage.distance_transform_edt(~near, sampling=sampling)
            far[y0:y1, x0:x1] = np.minimum(far[y0:y1, x0:x1], local)
        far[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (
            0.0  # never retry this spot, whether or not the lane got there
        )


def _fit_lot(
    blocked: np.ndarray,
    streets: np.ndarray,
    step: int,
    anchor: Point,
    along: tuple[int, int, int],
    depth: tuple[int, int, int],
    stream: random.Random,
) -> Optional[tuple[int, int, int, int]]:
    """Fit a lot into the free ground beside the street cell ``anchor``: ``(start, edge, length, depth)`` or None.

    Everything is in the street's own frame: ``blocked`` and ``streets`` are indexed ``[across, along]`` (a lot on a
    street that runs up and down is seen transposed), the lot lies on the ``step`` side of the street, ``along`` is
    ``(shortest, longest, gap)`` for its length along the street and ``depth`` the same for how deep it reaches. The lot
    is as long and as deep as it can be up to its random target, and ``None`` when the free ground is too small: so
    it packs a gap rather than failing in it.

    Returns the lot's first cell along the street, its near edge across the street (its first row when ``step`` is 1,
    one past its last when ``step`` is -1), its length and its depth.
    """
    across, at = anchor
    rows, cols = blocked.shape
    short, long_, gap_along = along
    shallow, deep, gap_across = depth
    band = streets[max(0, across - 3) : across + 4, max(0, at - short // 2) : at + short // 2 + 1]
    hits = np.nonzero(band.any(axis=1))[0] + max(0, across - 3)
    edge = across if len(hits) == 0 else int(hits.max() if step > 0 else hits.min())
    edge = edge + step * (gap_across + 1) if step > 0 else edge - gap_across
    near, far = (edge, edge + shallow + gap_across) if step > 0 else (edge - shallow - gap_across, edge)
    if near < 0 or far > rows:
        return None
    strip = blocked[near:far].any(axis=0)
    if strip[at]:
        return None
    first, last = at, at
    while first > 0 and not strip[first - 1]:
        first -= 1
    while last < cols - 1 and not strip[last + 1]:
        last += 1
    room = last - first + 1 - 2 * gap_along
    if room < short:
        return None
    length = min(room, stream.randint(short, long_))
    start = first + gap_along + stream.randint(0, room - length)
    reach = stream.randint(shallow, deep)
    free = shallow
    while free < reach:
        row = edge + free if step > 0 else edge - free - 1
        guard = row + gap_across if step > 0 else row - gap_across
        if (
            not (0 <= row < rows and 0 <= guard < rows)
            or blocked[min(row, guard) : max(row, guard) + 1, start : start + length].any()
        ):
            break
        free += 1
    return start, edge, length, free


_OPPOSITES = (((0, -1), (0, 1)), ((-1, 0), (1, 0)))  # (dx, dy) pairs: above and below, left and right


def _join_roads(grid: np.ndarray, dry: np.ndarray, road: np.ndarray, aspect: float, reach: float) -> None:
    """Run every street that passes close beside the world road into it, so no bare strip is left between them.

    A street cell within ``reach`` rows of a road cell of ``road``, but not touching it, is joined to the nearest road
    cell by a straight run of street over the free dry cells between (the world road itself is laid into the grid as
    street at this point, so the run ends on it).
    """
    road = road & dry
    if not road.any():
        return
    distance, nearest = ndimage.distance_transform_edt(~road, sampling=(1.0, 1.0 / aspect), return_indices=True)
    touching = ndimage.binary_dilation(road, structure=np.ones((3, 3), bool))
    street = np.isin(grid, _STREET) & ~road & ~touching & (distance <= reach)
    for y, x in np.argwhere(street).tolist():
        end_y, end_x = int(nearest[0][y, x]), int(nearest[1][y, x])
        steps = max(abs(end_x - x), abs(end_y - y))
        for i in range(1, steps):
            cx, cy = round(x + (end_x - x) * i / steps), round(y + (end_y - y) * i / steps)
            if grid[cy, cx] == _VOID and dry[cy, cx]:
                grid[cy, cx] = _PATH


def _close_slivers(grid: np.ndarray, dry: np.ndarray) -> None:
    """Pave the bare cells squeezed between two street or road cells, so streets close up beside each other.

    A lane or spoke can run a cell away from another street or from the road (laid into the grid as street), and the
    ground would show through the strip between. A free dry cell with street on two opposite sides (above and below,
    or left and right) becomes street; a second pass closes the slivers the first leaves at a bend. The inside of a
    street corner has street on two adjacent sides only and stays bare.
    """
    rows, cols = grid.shape
    for _ in range(int(_SLIVER_PASSES)):
        street = np.pad(np.isin(grid, _STREET), 1)
        closing = np.zeros(grid.shape, dtype=bool)
        for (ax, ay), (bx, by) in _OPPOSITES:
            first = street[1 + ay : 1 + ay + rows, 1 + ax : 1 + ax + cols]
            second = street[1 + by : 1 + by + rows, 1 + bx : 1 + bx + cols]
            closing |= first & second
        closing &= (grid == _VOID) & dry
        if not closing.any():
            return
        grid[closing] = _PATH


def _lots(
    ctx: SiteContext,
    grid: np.ndarray,
    ground: np.ndarray,
    centre: Point,
    stream: random.Random,
    preplaced: Optional[list[Lot]] = None,
) -> tuple[np.ndarray, list[Lot]]:
    """Pack buildings along the streets; return ``(roof mask, the lots)``.

    ``preplaced`` are lots already stamped into ``grid`` (a mill): they count as built and keep their gap clear.
    """
    settings = ctx.config.get("sites.settlement")
    gap_x, gap_y = (int(v) for v in ctx.setting("street_gap"))
    rows_lo, rows_hi = (int(v) for v in ctx.setting("building_rows"))
    aspect = ctx.aspect
    widest = round(rows_hi * aspect * 1.6)  # the widest a building may be
    narrowest = round(0.8 * rows_lo * aspect)
    spec = _spec(ctx)
    rows, cols = grid.shape
    blocked = ~ground | (grid != _VOID)
    roofs = np.zeros(grid.shape, dtype=bool)
    target = float(settings["fill"]) * int(ground.sum())
    covered = 0
    placed: list[Lot] = list(preplaced or [])
    for lot in placed:
        roofs[lot.y : lot.y + lot.height, lot.x : lot.x + lot.width] |= lot.building.footprint
        blocked[
            max(0, lot.y - gap_y) : lot.y + lot.height + gap_y, max(0, lot.x - gap_x) : lot.x + lot.width + gap_x
        ] = True
        covered += int(lot.building.footprint.sum())
    stride = max(1, round(aspect))
    street = np.argwhere(np.isin(grid, _STREET))
    order = sorted(
        (tuple(int(v) for v in cell[::-1]) for cell in street[::stride]),
        key=lambda p: (((p[0] - centre[0]) / aspect) ** 2 + (p[1] - centre[1]) ** 2, p[1], p[0]),
    )
    streets = np.isin(grid, _STREET)
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
            if step_y:  # a lot above or below an east-west street: its length is columns, its depth rows
                fit = _fit_lot(
                    blocked, streets, step_y, (sy, sx), (narrowest, widest, gap_x), (rows_lo, rows_hi, gap_y), stream
                )
                if fit is None:
                    continue
                x0, y0, width, height = fit[0], fit[1] - (fit[3] if step_y < 0 else 0), fit[2], fit[3]
            else:  # beside a north-south street: its length is rows, its depth columns
                fit = _fit_lot(
                    blocked.T,
                    streets.T,
                    step_x,
                    (sx, sy),
                    (rows_lo, rows_hi, gap_y),
                    (narrowest, widest, gap_x),
                    stream,
                )
                if fit is None:
                    continue
                y0, x0, height, width = fit[0], fit[1] - (fit[3] if step_x < 0 else 0), fit[2], fit[3]
            if height < rows_lo or width < narrowest:
                continue
            shape_seed = stream.getrandbits(32)
            building = build_building(height, width, stream, spec, (sx - x0, sy - y0), random.Random(shape_seed))
            if building is None or building.front is None:
                continue
            front = (x0 + building.front[0], y0 + building.front[1])
            if not _join(grid, front, (sx, sy), (step_x, step_y)):
                continue
            inside = building.cells != _VOID
            grid[y0 : y0 + height, x0 : x0 + width][inside] = building.cells[inside]
            roofs[y0 : y0 + height, x0 : x0 + width] |= building.footprint
            blocked[max(0, y0 - gap_y) : y0 + height + gap_y, max(0, x0 - gap_x) : x0 + width + gap_x] = True
            streets = np.isin(grid, _STREET)
            covered += int(building.footprint.sum())
            placed.append(Lot(x0, y0, width, height, shape_seed, building))
            break
    return roofs, placed


def _storeys(
    ctx: SiteContext, grid: np.ndarray, lots: list[Lot], centre: Point, stream: random.Random
) -> list[np.ndarray]:
    """Raise the buildings: give each lot storeys, stamp the stairs on the ground floor and return the upper floors.

    The nearer the plaza, the taller; at least the lot nearest it reaches the top floor. Every storey has the
    footprint of the ground floor (same ``shape_seed``) and its own rooms, and the stairs stand on a floor cell free on
    both floors. The result holds one full-size grid per floor above the ground (void outside the buildings).
    """
    top = ctx.floor_count
    if top <= 1 or not lots:
        return []
    chance = float(ctx.config.get("sites.settlement.storey_chance"))

    def distance(lot: Lot) -> float:
        return math.hypot((lot.x + lot.width / 2 - centre[0]) / ctx.aspect, lot.y + lot.height / 2 - centre[1])

    reach = max(distance(lot) for lot in lots) or 1.0
    levels = []
    for lot in lots:
        count = 1
        while count < top and stream.random() < chance * (1.0 - 0.7 * distance(lot) / reach):
            count += 1
        levels.append(count)
    levels[min(range(len(lots)), key=lambda i: (distance(lots[i]), i))] = top
    uppers = [np.zeros_like(grid) for _ in range(top - 1)]
    spec = _spec(ctx)
    for index, lot in enumerate(lots):
        floors = [lot.building.cells]
        for storey in range(1, levels[index]):
            upper = build_building(
                lot.height,
                lot.width,
                rng.derive(ctx.seed, "site.layout", "upper", index, storey),
                spec,
                None,
                random.Random(lot.shape_seed),
            )
            if upper is None:
                break
            floors.append(upper.cells)
        stairs: list[Point] = []
        for storey in range(len(floors) - 1):
            doors = (floors[storey] == _DOOR) | (floors[storey + 1] == _DOOR)
            free = (floors[storey] == _FLOOR) & (floors[storey + 1] == _FLOOR)
            free &= ~ndimage.binary_dilation(doors, structure=np.ones((3, 3), bool))
            if stairs:
                free[max(0, stairs[-1][1] - 1) : stairs[-1][1] + 2, max(0, stairs[-1][0] - 1) : stairs[-1][0] + 2] = (
                    False
                )
            candidates = sorted((int(c), int(r)) for r, c in np.argwhere(free))
            if not candidates:
                break
            stairs.append(candidates[stream.randrange(len(candidates))])
        for storey, floor_cells in enumerate(floors[: len(stairs) + 1]):
            layer = floor_cells.copy()
            if storey < len(stairs):
                layer[stairs[storey][1], stairs[storey][0]] = _UP
            if storey > 0:
                layer[stairs[storey - 1][1], stairs[storey - 1][0]] = _DOWN
            window = (slice(lot.y, lot.y + lot.height), slice(lot.x, lot.x + lot.width))
            target = grid if storey == 0 else uppers[storey - 1]
            inside = layer != _VOID
            target[window][inside] = layer[inside]
    return uppers


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


def _shore(still: np.ndarray, free: np.ndarray, step: Point) -> np.ndarray:
    """Return the free cells whose neighbour one ``step`` away is open water."""
    dx, dy = step
    beyond = np.roll(still, (-dy, -dx), axis=(0, 1))
    if dy == 1:
        beyond[-1, :] = False
    elif dy == -1:
        beyond[0, :] = False
    if dx == 1:
        beyond[:, -1] = False
    elif dx == -1:
        beyond[:, 0] = False
    return free & beyond


def _harbour(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, centre: Point) -> None:
    """Build a harbour for a port: a pier into open water from the shore nearest the plaza, boats moored beside it.

    The pier starts on the dry shore nearest the plaza and its landing is joined to the plaza by a street. Nothing is
    built when no open water lies within ``harbour.reach_rows`` of the plaza (the tag is about the coast within reach in
    the world, not within the extent).
    """
    still = ctx.patch.still
    if "port" not in ctx.tags or not still.any():
        return
    cfg = ctx.config.get("sites.settlement.harbour")
    free = dry & (grid == _VOID)
    cx, cy = centre
    options = []
    for index, step in enumerate(_STEPS):
        for y, x in np.argwhere(_shore(still, free, step)).tolist():
            options.append((((x - cx) / ctx.aspect) ** 2 + (y - cy) ** 2, y, x, index))
    if not options:
        return
    nearest, y, x, index = min(options)
    if nearest > float(cfg["reach_rows"]) ** 2:
        return
    dx, dy = _STEPS[index]
    rows, cols = grid.shape
    horizontal = dy == 0
    length = round(int(cfg["pier_rows"]) * (ctx.aspect if horizontal else 1.0))
    width = 1 if horizontal else max(1, round(ctx.aspect))
    reached = 0
    for i in range(1, length + 1):
        px, py = x + dx * i, y + dy * i
        if not (0 <= px < cols and 0 <= py < rows and still[py, px] and grid[py, px] == _VOID):
            break
        for extra in range(1 if horizontal else width):
            qx = px + extra
            if qx < cols and still[py, qx] and grid[py, qx] == _VOID:
                grid[py, qx] = _BRIDGE
        reached = i
    if reached == 0:
        return
    grid[y, x] = _PATH
    if not horizontal:
        for extra in range(1, width):
            if x + extra < cols and dry[y, x + extra] and grid[y, x + extra] == _VOID:
                grid[y, x + extra] = _PATH
    lay_street(grid, dry, (x, y), centre, ctx.street_rules, dry)
    stream = rng.derive(ctx.seed, "site.layout", "harbour")
    length_rows, beam = int(cfg["boat_length"]), int(cfg["boat_beam"])
    boat_rows, boat_cols = (
        (beam, round(length_rows * ctx.aspect)) if horizontal else (length_rows, round(beam * ctx.aspect))
    )
    sides = [1, -1]
    stream.shuffle(sides)
    moored = 0
    for fraction in (0.4, 0.85, 0.65, 0.2):
        for side in sides:
            if moored >= int(cfg["boats"]):
                return
            along = round(fraction * reached)
            if horizontal:
                top, left = y + side * (boat_rows // 2 + 2) - boat_rows // 2, x + dx * along - boat_cols // 2
            else:
                clear = boat_cols // 2 + 2 + (width - 1 if side > 0 else 0)
                top, left = y + dy * along - boat_rows // 2, x + side * clear - boat_cols // 2
            moored += moor_boat(grid, still, left, top, boat_rows, boat_cols, stream)


_AXLE = {(1, 0): int(Cell.AXLE_H), (-1, 0): int(Cell.AXLE_H), (0, 1): int(Cell.AXLE_V), (0, -1): int(Cell.AXLE_V)}


def _wheel_geometry(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    river: np.ndarray,
    rect: tuple[int, int, int, int],
    side: Point,
    wheel_rows: int,
    gap: int,
) -> Optional[tuple[list[Point], list[Point]]]:
    """Plan a water wheel for the house ``rect`` ``(x, y, width, height)`` on its ``side``: ``(axle cells, rim cells)``.

    The axle runs from just outside the middle of that wall, over at most ``gap`` cells of free bank, into the river
    and on to the hub, which lies far enough in for the whole wheel to stand in the water with a cell of river between
    it and the bank. The wheel is an ellipse ``wheel_rows`` rows tall and as many columns as make it round; its rim is
    the cells on its edge, the rest is left as water. ``None`` when the bank, the river or the free cells do not allow.
    """
    x0, y0, width, height = rect
    dx, dy = side
    start = (x0 + width // 2, y0 + height) if dy > 0 else (x0 + width // 2, y0 - 1) if dy < 0 else None
    if start is None:
        start = (x0 + width, y0 + height // 2) if dx > 0 else (x0 - 1, y0 + height // 2)
    rows, cols = grid.shape
    wheel_cols = round(wheel_rows * ctx.aspect)
    reach_x, reach_y = wheel_cols / 2.0, wheel_rows / 2.0
    inset = (wheel_cols // 2 if dx else wheel_rows // 2) + 1
    k = 0
    while True:  # the bank: free dry cells up to the river
        x, y = start[0] + dx * k, start[1] + dy * k
        if not (0 <= x < cols and 0 <= y < rows):
            return None
        if river[y, x]:
            break
        if k >= gap or not (dry[y, x] and grid[y, x] == _VOID):
            return None
        k += 1
    hub = (start[0] + dx * (k + inset), start[1] + dy * (k + inset))
    disc = []
    for y in range(hub[1] - wheel_rows, hub[1] + wheel_rows + 1):
        for x in range(hub[0] - wheel_cols, hub[0] + wheel_cols + 1):
            if ((x - hub[0]) / reach_x) ** 2 + ((y - hub[1]) / reach_y) ** 2 <= 1.0:
                disc.append((x, y))
    if any(not (0 <= x < cols and 0 <= y < rows and river[y, x] and grid[y, x] == _VOID) for x, y in disc):
        return None
    axle = [(start[0] + dx * i, start[1] + dy * i) for i in range(k + inset + 1)]
    if any(
        not (0 <= x < cols and 0 <= y < rows) or grid[y, x] != _VOID or not (river[y, x] or dry[y, x]) for x, y in axle
    ):
        return None
    inside = set(disc)
    rim = [(x, y) for x, y in disc if any((x + i, y + j) not in inside for i in (-1, 0, 1) for j in (-1, 0, 1))]
    return axle, rim


def _try_house(
    ctx: SiteContext,
    grid: np.ndarray,
    dry: np.ndarray,
    ground: np.ndarray,
    rect: tuple[int, int, int, int],
    street: Point,
    stream: random.Random,
    spec: Spec,
) -> Optional[tuple[np.ndarray, Lot]]:
    """Build a house on ``rect`` with its door joined to ``street``: ``(the grid with it stamped, its lot)`` or None.

    The grid given is not changed; the caller takes the returned copy if it keeps the house. The door's approach and
    the street to ``street`` are laid over free ground.
    """
    x0, y0, width, height = rect
    shape_seed = stream.getrandbits(32)
    building = build_building(height, width, stream, spec, (street[0] - x0, street[1] - y0), random.Random(shape_seed))
    if building is None or building.front is None:
        return None
    front = (x0 + building.front[0], y0 + building.front[1])
    if not (0 <= front[0] < grid.shape[1] and 0 <= front[1] < grid.shape[0]) or grid[front[1], front[0]] != _VOID:
        return None
    trial = grid.copy()
    inside = building.cells != _VOID
    trial[y0 : y0 + height, x0 : x0 + width][inside] = building.cells[inside]
    trial[front[1], front[0]] = _PATH
    if lay_street(trial, dry, front, street, ctx.street_rules, ground | np.isin(trial, _STREET)) is None:
        return None
    return trial, Lot(x0, y0, width, height, shape_seed, building)


def _ensure_house(
    ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, ground: np.ndarray, centre: Point
) -> Optional[Lot]:
    """Build one house for a settlement whose lots found no room: the smallest, on free dry ground nearest the plaza.

    A settlement with a small footprint (a village on a shore) can have no stretch of ground deep enough beside a street
    for a lot. A settlement is always at least one house, so the house goes on any free dry ground that fits it, ground
    in the footprint first, its door joined to the nearest street. Returns the lot, or None if nothing fits.
    """
    streets = np.isin(grid, _STREET)
    if not streets.any():
        return None
    height = int(ctx.setting("building_rows")[0])
    width = round(0.8 * height * ctx.aspect)
    free = dry & (grid == _VOID)
    sampling = (1.0, 1.0 / ctx.aspect)
    fits = ndimage.minimum_filter(free.astype(np.uint8), size=(height, width), mode="constant", cval=0) > 0
    cx, cy = centre
    spots = sorted(
        (not ground[y, x], ((x - cx) / ctx.aspect) ** 2 + (y - cy) ** 2, y, x) for y, x in np.argwhere(fits).tolist()
    )[:_MILL_TRIES]
    _, street_at = ndimage.distance_transform_edt(~streets, sampling=sampling, return_indices=True)
    stream = rng.derive(ctx.seed, "site.layout", "house")
    spec = _spec(ctx)
    for _, _, mid_y, mid_x in spots:
        rect = (mid_x - width // 2, mid_y - height // 2, width, height)
        street = (int(street_at[1][mid_y, mid_x]), int(street_at[0][mid_y, mid_x]))
        placed = _try_house(ctx, grid, dry, ground, rect, street, stream, spec)
        if placed is not None:
            grid[:] = placed[0]
            return placed[1]
    return None


def _mill(ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, ground: np.ndarray, centre: Point) -> Optional[Lot]:
    """Build a mill for a river settlement: a house beside the river, a water wheel set into it and an axle between.

    The house goes on the free ground nearest the plaza within ``mill.reach`` rows of the river, its door joined to the
    nearest street, and the wheel turns in the river on whichever side of the house the bank allows (see
    :func:`_wheel_geometry`). Returns the house as a lot (so it is roofed and may have storeys), or None when the extent
    has no river beside free ground that takes a wheel.
    """
    river = ctx.patch.river
    streets = np.isin(grid, _STREET)
    if "river" not in ctx.tags or not river.any() or not streets.any():
        return None
    cfg = ctx.config.get("sites.settlement.mill")
    height = int(ctx.setting("building_rows")[0])
    width = round(height * ctx.aspect * float(cfg["width"]))
    wheel_rows = int(cfg["wheel_rows"])
    free = ground & dry & (grid == _VOID)
    sampling = (1.0, 1.0 / ctx.aspect)
    near_river = ndimage.distance_transform_edt(~river, sampling=sampling)
    fits = ndimage.minimum_filter(free.astype(np.uint8), size=(height, width), mode="constant", cval=0) > 0
    touches = ndimage.minimum_filter(near_river, size=(height, width), mode="nearest") <= float(cfg["reach"])
    cx, cy = centre
    spots = sorted(
        (((x - cx) / ctx.aspect) ** 2 + (y - cy) ** 2, y, x) for y, x in np.argwhere(fits & touches).tolist()
    )[:_MILL_TRIES]
    _, street_at = ndimage.distance_transform_edt(~streets, sampling=sampling, return_indices=True)
    stream = rng.derive(ctx.seed, "site.layout", "mill")
    spec = _spec(ctx)
    for _, mid_y, mid_x in spots:
        x0, y0 = mid_x - width // 2, mid_y - height // 2
        rect = (x0, y0, width, height)
        plans = []
        for side in _STEPS:
            gap = max(1, round(float(cfg["reach"]) * (ctx.aspect if side[0] else 1.0)))
            found = _wheel_geometry(ctx, grid, dry, river, rect, side, wheel_rows, gap)
            if found is not None:
                plans.append((len(found[0]), side, found))
        if not plans:
            continue
        street = (int(street_at[1][mid_y, mid_x]), int(street_at[0][mid_y, mid_x]))
        placed = _try_house(ctx, grid, dry, ground, rect, street, stream, spec)
        if placed is None:
            continue
        trial, lot = placed
        for _, side, (axle, rim) in sorted(plans, key=lambda p: (p[0], _STEPS.index(p[1]))):
            if any(trial[y, x] != _VOID for x, y in axle + rim):
                continue  # the street or the door's approach is in the way: try another side
            for x, y in rim:
                trial[y, x] = _WHEEL
            for x, y in axle:
                trial[y, x] = _AXLE[side]
            grid[:] = trial
            return lot
    return None


def _wall(
    ctx: SiteContext, grid: np.ndarray, dry: np.ndarray, town: np.ndarray, ends: list[Point]
) -> tuple[list[Point], list[Point]]:
    """Ring the footprint with a thin wall; the road and each spoke crossing it make a gate. Water leaves a gap.

    Returns the ``(x, y)`` cells of the wall and of its gates, each in row-major order.
    """
    ring = ndimage.binary_dilation(town, structure=np.ones((3, 3), bool)) & ~town & dry
    streets = np.isin(grid, _STREET)
    grid[ring & (grid == _VOID)] = _WALL
    grid[ring & streets] = _DOOR
    rows, cols = grid.shape
    for x, y in ends:
        for step_x, step_y in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            gx, gy = x + step_x, y + step_y
            if 0 <= gx < cols and 0 <= gy < rows and ring[gy, gx]:
                grid[gy, gx] = _DOOR
    cells = [(int(x), int(y)) for y, x in np.argwhere(ring & (grid == _WALL)).tolist()]
    gates = [(int(x), int(y)) for y, x in np.argwhere(ring & (grid == _DOOR)).tolist()]
    return cells, gates


def _crack(grid: np.ndarray, lot: Lot, share: float, ctx: SiteContext, index: int) -> None:
    """Crack ``share`` of a lot's floor cells into rubble (a draw per cell, keyed on the lot)."""
    window = grid[lot.y : lot.y + lot.height, lot.x : lot.x + lot.width]
    roll = rng.derive_numpy(ctx.seed, "site.erode", "settlement", index).random(window.shape)
    window[(window == _FLOOR) & (roll < share)] = _RUBBLE


def _fall(
    ctx: SiteContext,
    grid: np.ndarray,
    roofs: np.ndarray,
    lots: list[Lot],
    wall: tuple[list[Point], list[Point]],
) -> None:
    """Let a ruined settlement fall: most buildings fall in, a few stand, the wall breaks and its gates open.

    A building stands with chance ``ctx.fall.standing`` (the lot a seeded draw picks always does). A fallen one has
    breaches, cracked floors, trees growing in and a roof only over the rooms that kept it; a standing one has a few
    cracks. Wall stretches fall until ``ctx.fall.wall`` of the wall is down, and every gate becomes rubble. The draws
    use their own streams, so the streets and lots are exactly the settlement's.
    """
    fall = ctx.fall
    assert fall is not None
    stream = rng.derive(ctx.seed, "site.erode", "settlement")
    standing = {index for index in range(len(lots)) if stream.random() < fall.standing}
    if lots:
        standing.add(stream.randrange(len(lots)))
    crack = fall.erosion * float(ctx.config.get("sites.furnish.ruin_crack"))
    for index, lot in enumerate(lots):
        if index in standing:
            _crack(grid, lot, crack * float(ctx.config.get("sites.furnish.ruin_standing_crack")), ctx, index)
            continue
        building = lot.building
        breach(
            grid, (lot.x, lot.y, lot.width, lot.height), stream, max(2, round(fall.erosion * len(building.rooms) * 3))
        )
        _crack(grid, lot, crack, ctx, index)
        window = (slice(lot.y, lot.y + lot.height), slice(lot.x, lot.x + lot.width))
        roofs[window][building.footprint] = False
        covered = np.zeros(building.footprint.shape, dtype=bool)
        for rx, ry, rw, rh in building.rooms:
            if stream.random() >= fall.erosion:
                covered[ry : ry + rh, rx : rx + rw] = True
        roofs[window] |= covered & building.footprint
        free = [(cx + lot.x, cy + lot.y) for cy, cx in np.argwhere((grid[window] == _FLOOR) & ~covered).tolist()]
        for cx, cy in stream.sample(free, len(free) // 8):
            grid[cy, cx] = int(Cell.TREE) if stream.random() < 0.5 else int(Cell.BUSH)
    cells, gates = wall
    for gx, gy in gates:
        grid[gy, gx] = _RUBBLE
    remaining = list(cells)
    target = round(fall.wall * len(cells))
    fallen = 0
    while remaining and fallen < target:
        cx, cy = remaining[stream.randrange(len(remaining))]
        reach = stream.randint(2, 4)  # a stretch of wall: this many rows each way, widened by the cell aspect
        near = [c for c in remaining if abs(c[1] - cy) <= reach and abs(c[0] - cx) <= reach * ctx.aspect]
        for wx, wy in near:
            grid[wy, wx] = _RUBBLE if stream.random() < 0.6 else _VOID
        fallen += len(near)
        gone = set(near)
        remaining = [c for c in remaining if c not in gone]


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
    stream = rng.derive(ctx.seed, "site.layout", 0)  # every floor rebuilds the same ground, so the storeys stack
    inset_x, inset_y = (int(v) for v in ctx.config.get("sites.settlement.wall_inset"))
    inner = np.zeros(grid.shape, dtype=bool)
    inner[inset_y + 1 : rows - inset_y - 1, inset_x + 1 : cols - inset_x - 1] = True
    town = _outline(ctx, centre, inner & ground, stream)
    ground = ground & town
    lay_roads(grid, ctx.patch)
    grid[_plaza(ctx, centre, stream) & dry & town] = _PATH
    for gate in ctx.patch.gates:
        if (gate.col, gate.row) != centre:
            lay_street(grid, dry, (gate.col, gate.row), centre, ctx.street_rules, town | np.isin(grid, _STREET))
    ends = _spokes(ctx, grid, town, dry, centre, stream)
    _rings(ctx, grid, town, dry, centre, stream)
    _lanes(ctx, grid, ground, town, stream)
    _harbour(ctx, grid, dry, centre)
    _join_roads(grid, dry, ctx.patch.road, ctx.aspect, float(ctx.config.get("sites.settlement.road_join_rows")))
    _close_slivers(grid, dry)
    mill = _mill(ctx, grid, dry, ground, centre)
    roofs, lots = _lots(ctx, grid, ground, centre, stream, [mill] if mill is not None else [])
    if not lots:  # a settlement is at least one house
        house = _ensure_house(ctx, grid, dry, ground, centre)
        if house is not None:
            lots = [house]
            roofs[house.y : house.y + house.height, house.x : house.x + house.width] |= house.building.footprint
    if ctx.fall is not None and not lots:  # nothing stood here: the caller draws a single fallen building instead
        return None
    uppers = _storeys(ctx, grid, lots, centre, stream)
    wall: tuple[list[Point], list[Point]] = ([], [])
    if ctx.walled:
        wall = _wall(ctx, grid, dry, town, ends)
    _plant(ctx, grid, dry, roofs, stream)
    if ctx.fall is not None:
        _fall(ctx, grid, roofs, lots, wall)
    if ctx.floor > 0:
        layer = uppers[ctx.floor - 1] if ctx.floor - 1 < len(uppers) else np.zeros_like(grid)
        cells = grid.copy()  # the ground as it is: streets, trees, the wall and its gates, the harbour and the mill
        cells[roofs] = int(Cell.ROOF)  # every building is a roof...
        cells[layer != _VOID] = layer[layer != _VOID]  # ...except where it has a storey this high
        return cells, np.zeros_like(layer)
    outside = grid.copy()
    outside[roofs] = int(Cell.ROOF)
    outside[(grid == _WALL) & ~roofs] = int(Cell.STONE)
    outside[(grid == _DOOR) & ~roofs] = _PATH  # a gate in the wall, not a door under a roof
    return grid, outside
