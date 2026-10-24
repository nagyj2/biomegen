"""Solid structures: a dungeon that descends, a tower that rises and a ruin that has fallen in.

**Dungeon.** The ground floor (floor 0) is a gatehouse on the surface: one hall with a street door facing the road and
the stairs down. Every floor below is underground: the whole extent is solid rock with passages carved out of it, thin
walls round the rooms (or bare cave floor), and stairs that line up from floor to floor. Shallow floors are rooms
joined by corridors; the deepest of a tall dungeon is a cave. Loot grows with depth.

**Tower.** A keep that tapers as it rises: each floor is one room, a little smaller than the one below, with the stairs
standing in the same column all the way up. Floor 0 has the street door; the top floor is an open lookout.

**Ruin.** A building (rooms, doors, a street door) that has fallen in: stretches of wall are breached, some rooms have
lost their roof, floors are rubble and trees have grown in. Seen from outside only the standing rooms have a roof. The
longer ago it fell (``SiteContext.age_years``) the more has collapsed, up to ``sites.ruin_erosion``.

**Shrine.** One small walled room with a street door and an altar at its middle.

Everything outside a structure is void, so the terrain shows round it; underground floors have no terrain, only rock.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .building import Building, Spec, build_building
from .carve import (
    Point,
    Rect,
    carve_corridor,
    carve_room,
    connect_floor_components,
    fit_rect,
    largest_component,
    room_center,
)
from .circulation import floor_links, force_floor_access, stamp_stairs
from .furnish import Weights, adjacent, keep_reachable, scatter, weighted_choice
from .kinds import lay_roof, roof_cell
from .layout import SiteBuilding, SiteContext, layout
from .partition import bsp_rooms
from .shapes import SHAPES
from .streets import lay_roads, lay_street

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)
_DOOR = int(Cell.DOOR)
_PATH = int(Cell.PATH)
_SOLID = int(Cell.SOLID)
_STONE = int(Cell.STONE)
_RUBBLE = int(Cell.RUBBLE)
Built = tuple[np.ndarray, np.ndarray, tuple[SiteBuilding, ...]]  # inside, sky view and the buildings that stand
_MIN_STAIR_GAP = 4  # cells between two staircases, so they never touch


def _buildable(ctx: SiteContext) -> np.ndarray:
    """Return the dry ground a structure may stand on, pulled back from the water by ``coast_margin_rows``."""
    rows = int(ctx.setting("coast_margin_rows"))
    if rows <= 0:
        return ctx.patch.dry
    structure = np.ones((2 * rows + 1, 2 * rows * ctx.vertical_width + 1), dtype=bool)
    return ndimage.binary_erosion(ctx.patch.dry, structure=structure, border_value=1)


def _spec(ctx: SiteContext, roles: tuple[str, ...], density: float, **kwargs: object) -> Spec:
    return Spec(
        int(ctx.setting("room_rows")[0]),
        ctx.aspect,
        roles,
        {role: ctx.weights(role) for role in roles},
        density,
        **kwargs,  # type: ignore[arg-type]
    )


def _gate_target(ctx: SiteContext, rect: Rect) -> Point:
    """The point a structure's street door faces, in the rectangle's own coordinates.

    The first road gate when a road arrives; otherwise a seeded side, so a structure always has a way in.
    """
    if ctx.patch.gates:
        gate = ctx.patch.gates[0]
        return gate.col - rect[0], gate.row - rect[1]
    x, y, w, h = rect
    side = rng.derive(ctx.seed, "site.layout", "door").randint(0, 3)
    return ((w // 2, h + 4), (w // 2, -4), (-4, h // 2), (w + 4, h // 2))[side]


def _fit(ctx: SiteContext, rows: int, cols: int) -> Optional[Rect]:
    """Fit a ``rows x cols`` rectangle on buildable ground near the middle, shrinking it a little at a time."""
    mask = _buildable(ctx)
    middle = (ctx.cols // 2, ctx.rows // 2)
    min_rows = int(ctx.setting("room_rows")[0]) + 2
    min_cols = math.ceil((min_rows - 2) * ctx.aspect) + 2
    while rows >= min_rows and cols >= min_cols:
        rect = fit_rect(mask, rows, cols, middle, ctx.aspect)
        if rect is not None:
            return rect
        rows, cols = rows - 1, cols - max(1, round(ctx.aspect))
    return None


def _stamp(grid: np.ndarray, building: Building, rect: Rect) -> None:
    x, y, w, h = rect
    inside = building.cells != _VOID
    grid[y : y + h, x : x + w][inside] = building.cells[inside]


def _approach(ctx: SiteContext, grid: np.ndarray, building: Building, rect: Rect) -> None:
    """Lay the road round the building and join its street door to it with a short street."""
    lay_roads(grid, ctx.patch)
    if building.front is None:
        return
    front = (rect[0] + building.front[0], rect[1] + building.front[1])
    if not (0 <= front[0] < ctx.cols and 0 <= front[1] < ctx.rows) or grid[front[1], front[0]] != _VOID:
        return
    road = np.argwhere(ctx.patch.road & ctx.patch.dry & (grid == _PATH))
    if len(road) == 0:
        return
    nearest = min(
        ((int(x), int(y)) for y, x in road.tolist()),
        key=lambda p: (((p[0] - front[0]) / ctx.aspect) ** 2 + (p[1] - front[1]) ** 2, p[1], p[0]),
    )
    grid[front[1], front[0]] = _PATH
    lay_street(grid, ctx.patch.dry, nearest, front, ctx.street_rules)


def _stair_links(ctx: SiteContext, area: np.ndarray, pinned: Optional[Point] = None) -> list[Point]:
    """One cell per adjacent floor pair, drawn from ``area``; the last is ``pinned`` when given (the surface stairs).

    The list depends only on the seed and the floor-independent ``area``, so every floor rebuilds the same links and the
    shafts line up.
    """
    count = ctx.floor_count - 1
    if count <= 0:
        return []
    stream = rng.derive(ctx.seed, "site.shaft")
    candidates = [(int(x), int(y)) for y, x in np.argwhere(ndimage.binary_erosion(area, iterations=2)).tolist()]
    candidates = candidates or [(int(x), int(y)) for y, x in np.argwhere(area).tolist()]
    links: list[Point] = [pinned] if pinned is not None else []
    free = count - len(links)
    chosen: list[Point] = []
    for _ in range(free):
        far = [
            c
            for c in candidates
            if all(max(abs(c[0] - q[0]), abs(c[1] - q[1])) >= _MIN_STAIR_GAP for q in chosen + links)
        ]
        chosen.append(stream.choice(far or candidates))
    return chosen + links


def _furnish_room_set(
    grid: np.ndarray, cells: list[Point], stream: random.Random, table: Weights, density: float
) -> None:
    if table and cells:
        scatter(grid, stream, cells, density, lambda r, _x, _y: weighted_choice(r, table))


# --------------------------------------------------------------------------------------------------------- dungeon
def _gatehouse(ctx: SiteContext) -> Optional[Rect]:
    rows = max(7, round(ctx.rows * 0.42))
    cols = max(round(rows * ctx.aspect * 1.2), round(ctx.cols * 0.3))
    return _fit(ctx, min(rows, ctx.rows - 2), min(cols, ctx.cols - 2))


def _gatehouse_stairs(rect: Rect) -> Point:
    """The cell of the gatehouse hall where the stairs down stand: inside, off the walls."""
    x, y, w, h = rect
    return x + w // 2 + w // 5, y + h // 2


def _underground(ctx: SiteContext, links: list[Point], cave: bool, stream: random.Random) -> np.ndarray:
    """One underground floor: rock with rooms and corridors (or a cave) carved out and the stairs reachable."""
    rows, cols = ctx.rows, ctx.cols
    grid = np.full((rows, cols), _SOLID, dtype=np.uint8)
    width = ctx.vertical_width
    up, down = floor_links(links, ctx.floor, ctx.lowest_floor, ctx.floor_count)
    access = [c for c in (up, down) if c is not None]
    carved = np.zeros((rows, cols), dtype=bool)
    if cave:
        shape = SHAPES["cellular"](rng.derive(ctx.seed, "site.shape", ctx.floor), cols, rows)
        carved = largest_component(shape)
        grid[carved] = _FLOOR
        rooms: list[Rect] = []
    else:
        room_rows = ctx.setting("room_rows")
        rooms = bsp_rooms(stream, cols, rows, (int(room_rows[0]), int(room_rows[1])), ctx.aspect, 2)
        for room in rooms:
            carve_room(grid, room)
        centres = [room_center(r) for r in rooms]
        for a, b in zip(centres, centres[1:], strict=False):
            carve_corridor(grid, a, b, width)
        for _ in range(int(len(centres) * float(ctx.setting("extra_corridors")["dungeon"]))):
            i, j = stream.randint(0, len(centres) - 1), stream.randint(0, len(centres) - 1)
            if i != j:
                carve_corridor(grid, centres[i], centres[j], width)
    for cell in access:
        force_floor_access(grid, cell, rooms or [(cell[0], cell[1], 1, 1)], width)
    connect_floor_components(grid, width)
    floor = grid == _FLOOR
    if not cave:
        walls = ndimage.binary_dilation(floor, structure=np.ones((3, 3), bool)) & ~floor
        grid[walls] = _WALL
    reserved = stamp_stairs(grid, up, down)
    depth = 0.0 if ctx.floor_count <= 1 else (ctx.top_floor - ctx.floor) / (ctx.floor_count - 1)
    density = float(ctx.setting("clutter_density")) * (
        1.0 + float(ctx.config.get("sites.furnish.depth_density_gain")) * depth
    )
    gain = float(ctx.config.get("sites.furnish.chest_depth_gain")) * depth
    room_mask = np.zeros(grid.shape, dtype=bool)
    for rx, ry, rw, rh in rooms:
        room_mask[ry : ry + rh, rx : rx + rw] = True
    special = (grid == int(Cell.STAIRS_UP)) | (grid == int(Cell.STAIRS_DOWN))
    near = adjacent(special)
    free = [(int(x), int(y)) for y, x in np.argwhere(grid == _FLOOR).tolist() if (int(x), int(y)) not in reserved]
    vault_limit = 3 * int(ctx.setting("room_rows")[0]) * round(ctx.aspect)
    passages = [c for c in free if not room_mask[c[1], c[0]] or near[c[1], c[0]]]
    inside = [c for c in free if room_mask[c[1], c[0]] and not near[c[1], c[0]]]
    small = {(rx, ry) for rx, ry, rw, rh in rooms if rw * rh <= vault_limit}

    def room_role(cell: Point) -> str:
        for rx, ry, rw, rh in rooms:
            if rx <= cell[0] < rx + rw and ry <= cell[1] < ry + rh:
                return "vault" if (rx, ry) in small else ("cell" if rw * rh < 2 * vault_limit else "hall")
        return "hall"

    stream_furnish = rng.derive(ctx.seed, "site.furnish", ctx.floor)
    by_role: dict[str, list[Point]] = {}
    for cell in inside:
        by_role.setdefault(room_role(cell) if rooms else "hall", []).append(cell)
    for role in sorted(by_role):
        table = [(c, w + (gain if c == Cell.CHEST else 0.0)) for c, w in ctx.weights(role)]
        _furnish_room_set(grid, by_role[role], stream_furnish, table, density)
    _furnish_room_set(grid, passages, stream_furnish, ctx.weights("passage"), density)
    keep_reachable(grid, sorted(reserved))
    return grid


@layout("dungeon")
def build_dungeon(ctx: SiteContext) -> Optional[Built]:
    """A dungeon floor: the surface gatehouse at floor 0, rock with passages below."""
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    house = _gatehouse(ctx)
    if house is None:
        return None
    area = np.zeros((ctx.rows, ctx.cols), dtype=bool)
    area[2:-2, 4:-4] = True
    links = _stair_links(ctx, area, _gatehouse_stairs(house))
    if ctx.floor < 0:
        cave = ctx.floor_count >= 4 and ctx.floor == ctx.lowest_floor
        grid = _underground(ctx, links, cave, stream)
        return grid, np.zeros_like(grid), ()
    x, y, w, h = house
    spec = _spec(ctx, ("hall",), float(ctx.setting("clutter_density")), shapes=("rect",), subdivide=False)
    building = build_building(h, w, stream, spec, _gate_target(ctx, house))
    if building is None:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    _stamp(grid, building, house)
    up, down = floor_links(links, ctx.floor, ctx.lowest_floor, ctx.floor_count)
    reserved = stamp_stairs(grid, up, down)
    keep_reachable(grid, sorted(reserved | set((x + dx, y + dy) for dx, dy in building.doors)))
    _approach(ctx, grid, building, house)
    outside = grid.copy()
    return grid, outside, (lay_roof(ctx.config, outside, "gatehouse", house, building.footprint),)


# ----------------------------------------------------------------------------------------------------------- tower
@layout("tower")
def build_tower(ctx: SiteContext) -> Optional[Built]:
    """A tower floor: one room, each floor a little smaller than the one below, the stairs in a single column.

    An upper floor also shows the ground and the outline of each floor below it as a roof, under its own cells.
    """
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    base_rows = max(7, round(ctx.rows * 0.72))
    base_cols = round(base_rows * ctx.aspect)
    ground = _fit(ctx, min(base_rows, ctx.rows - 2), min(base_cols, ctx.cols - 2))
    if ground is None:
        return None
    gx, gy, gw, gh = ground
    taper_rows, taper_cols = 1, max(1, round(ctx.aspect))
    min_rows = int(ctx.setting("room_rows")[0]) + 2
    rects: list[Rect] = []
    for level in range(ctx.floor_count):
        shrink = min(level, max(0, (gh - min_rows) // (2 * taper_rows)))
        rects.append(
            (
                gx + shrink * taper_cols,
                gy + shrink * taper_rows,
                gw - 2 * shrink * taper_cols,
                gh - 2 * shrink * taper_rows,
            )
        )
    top = rects[-1]
    stair_area = np.zeros((ctx.rows, ctx.cols), dtype=bool)
    stair_area[top[1] + 1 : top[1] + top[3] - 1, top[0] + 1 : top[0] + top[2] - 1] = True
    links = _stair_links(ctx, stair_area)
    rect = rects[ctx.floor - ctx.lowest_floor]
    lookout = ctx.floor == ctx.top_floor and ctx.floor_count > 1
    roles = ("lookout",) if lookout else ("study", "bedroom", "storage")
    density = float(ctx.setting("clutter_density")) * (
        float(ctx.config.get("sites.furnish.lookout_density")) if lookout else 1.0
    )
    spec = _spec(ctx, roles, density, shapes=("rect",), subdivide=False)
    x, y, w, h = rect
    building = build_building(h, w, stream, spec, _gate_target(ctx, rect) if ctx.floor == 0 else None)
    if building is None:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    _stamp(grid, building, rect)
    up, down = floor_links(links, ctx.floor, ctx.lowest_floor, ctx.floor_count)
    reserved = stamp_stairs(grid, up, down)
    keep_reachable(grid, sorted(reserved | set((x + dx, y + dy) for dx, dy in building.doors)))
    if ctx.floor == 0:
        _approach(ctx, grid, building, rect)
    outside = np.full_like(grid, _VOID)
    buildings: tuple[SiteBuilding, ...] = ()
    roof = roof_cell(ctx.config, ctx.kind)
    if ctx.floor == 0:
        outside = grid.copy()
        buildings = (lay_roof(ctx.config, outside, ctx.kind, ground, building.footprint),)
    else:  # the ground view (approach, trees) with every lower floor's outline as a roof, this floor laid over them
        lowest = build_tower(replace(ctx, floor=ctx.lowest_floor))
        shown = lowest[0].copy() if lowest is not None else np.full_like(grid, _VOID)
        for lower_x, lower_y, lower_w, lower_h in rects[: ctx.floor - ctx.lowest_floor]:
            shown[lower_y : lower_y + lower_h, lower_x : lower_x + lower_w] = roof
        shown[grid != _VOID] = grid[grid != _VOID]
        grid = shown
    return grid, outside, buildings


# ------------------------------------------------------------------------------------------------------------ ruin
def breach(grid: np.ndarray, rect: Rect, stream: random.Random, count: int) -> None:
    """Knock gaps in the walls: a run of two to six wall cells each, along a wall."""
    x, y, w, h = rect
    walls = [(int(cx), int(cy)) for cy, cx in np.argwhere(grid[y : y + h, x : x + w] == _WALL).tolist()]
    walls = [(cx + x, cy + y) for cx, cy in walls]
    for _ in range(count):
        if not walls:
            return
        cx, cy = stream.choice(walls)
        length = stream.randint(2, 6)
        step = (1, 0) if grid[cy, min(cx + 1, grid.shape[1] - 1)] == _WALL else (0, 1)
        for i in range(length):
            nx, ny = cx + step[0] * i, cy + step[1] * i
            if 0 <= nx < grid.shape[1] and 0 <= ny < grid.shape[0] and grid[ny, nx] == _WALL:
                grid[ny, nx] = _RUBBLE if stream.random() < 0.6 else _VOID


def _erosion(ctx: SiteContext) -> float:
    """The share of a ruin's walls that have fallen: more the longer ago it fell, the full amount for an undated one."""
    full = float(ctx.setting("ruin_erosion"))
    if ctx.age_years is None:
        return full
    young = float(ctx.setting("ruin_erosion_young"))
    return young + (full - young) * min(1.0, ctx.age_years / max(1.0, float(ctx.setting("ruin_erosion_years"))))


@layout("ruin")
def build_ruin(ctx: SiteContext) -> Optional[Built]:
    """A ruin: a building fallen in, with breaches, rubble, trees and the rooms that kept their roofs."""
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    rows = max(9, round(ctx.rows * 0.85))
    cols = max(round(rows * ctx.aspect * 1.4), round(ctx.cols * 0.75))
    rect = _fit(ctx, min(rows, ctx.rows - 2), min(cols, ctx.cols - 2))
    if rect is None:
        return None
    x, y, w, h = rect
    spec = _spec(
        ctx,
        ("hall", "debris"),
        float(ctx.setting("clutter_density")) * float(ctx.config.get("sites.furnish.ruin_density")),
    )
    building = build_building(h, w, stream, spec, _gate_target(ctx, rect))
    if building is None:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    _stamp(grid, building, rect)
    erosion = _erosion(ctx)
    breach(grid, rect, stream, max(2, round(erosion * len(building.rooms) * 3)))
    floor = grid == _FLOOR
    roll = rng.derive_numpy(ctx.seed, "site.erode").random(grid.shape)
    crack = erosion * float(ctx.config.get("sites.furnish.ruin_crack"))
    grid[floor & (roll < crack)] = _RUBBLE
    standing = [room for room in building.rooms if stream.random() >= erosion]
    plants = [
        (cx, cy)
        for cy, cx in np.argwhere(grid == _FLOOR).tolist()
        if all(not (rx <= cx - x < rx + rw and ry <= cy - y < ry + rh) for rx, ry, rw, rh in standing)
    ]
    for cx, cy in stream.sample(plants, min(len(plants), len(plants) // 8)):
        grid[cy, cx] = int(Cell.TREE) if stream.random() < 0.5 else int(Cell.BUSH)
    keep_reachable(grid, sorted((x + dx, y + dy) for dx, dy in building.doors))  # a tree never walls a door in
    _approach(ctx, grid, building, rect)
    outside = grid.copy()
    outside[outside == _WALL] = _STONE
    covered = np.zeros((h, w), dtype=bool)
    for rx, ry, rw, rh in standing:
        covered[ry : ry + rh, rx : rx + rw] = True
    buildings = (lay_roof(ctx.config, outside, "ruin", rect, covered),) if covered.any() else ()
    return grid, outside, buildings


# ---------------------------------------------------------------------------------------------------------- shrine
@layout("shrine")
def build_shrine(ctx: SiteContext) -> Optional[Built]:
    """A shrine: one small walled room with its door to the road and an altar, its roof the shrine kind's own colour."""
    stream = rng.derive(ctx.seed, "site.layout", ctx.floor)
    rows = max(7, round(ctx.rows * 0.6))
    rect = _fit(ctx, min(rows, ctx.rows - 2), min(round(rows * ctx.aspect), ctx.cols - 2))
    if rect is None:
        return None
    x, y, w, h = rect
    spec = _spec(ctx, ("altar",), float(ctx.setting("clutter_density")), shapes=("rect",), subdivide=False)
    building = build_building(h, w, stream, spec, _gate_target(ctx, rect))
    if building is None:
        return None
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    _stamp(grid, building, rect)
    centre = (x + w // 2, y + h // 2)
    if grid[centre[1], centre[0]] == _FLOOR:
        grid[centre[1], centre[0]] = int(Cell.HEARTH)  # the altar, whatever else the room was dressed with
    keep_reachable(grid, sorted((x + dx, y + dy) for dx, dy in building.doors))
    _approach(ctx, grid, building, rect)
    outside = grid.copy()
    return grid, outside, (lay_roof(ctx.config, outside, "shrine", rect, building.footprint),)
