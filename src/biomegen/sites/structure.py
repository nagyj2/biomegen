"""Solid structures: a dungeon that descends, a tower that rises and a ruin eroded to rubble.

All three share one recipe. Pick an outline (a seeded, floor-independent organic shape kept off water), partition it
into rooms, link them with corridors, plant stair shafts that line up from floor to floor, seal everything in rock and
wall, then dress the floor. The ground floor (floor 0) gets an entrance door, on the wall nearest the road's gate, and a
street from the gate to it. Everything outside the outline is void, so the terrain shows round the structure.
"""

from __future__ import annotations

import math
import random
from typing import Optional

import numpy as np
from scipy import ndimage

from ..util import rng
from ..world.tile import Cell
from .carve import (
    Point,
    Rect,
    add_walls,
    carve_corridor,
    carve_room,
    connect_floor_components,
    fill_enclosed,
    largest_component,
    rect_in_mask,
    room_center,
)
from .circulation import floor_links, force_floor_access, punch_entrance, stair_links, stamp_stairs
from .furnish import Weights, adjacent, free_floor, keep_reachable, scatter, weighted_choice
from .layout import SiteContext, layout
from .partition import bsp_rooms
from .shapes import SHAPES, outline
from .streets import lay_street

_VOID = int(Cell.VOID)
_FLOOR = int(Cell.FLOOR)
_WALL = int(Cell.WALL)


def _table(ctx: SiteContext, chest_bonus: float = 0.0) -> Weights:
    """Return the site's furniture set as ``(Cell, weight)`` pairs, with extra weight on chests."""
    table: Weights = []
    for name, weight in ctx.furniture:
        cell = Cell[name.upper()]
        table.append((cell, weight + (chest_bonus if cell == Cell.CHEST else 0.0)))
    return table


def _buildable(ctx: SiteContext) -> np.ndarray:
    """Return the dry ground a structure may stand on, pulled back from the water by ``coast_margin_rows``."""
    rows = int(ctx.setting("coast_margin_rows"))
    if rows <= 0:
        return ctx.patch.dry
    structure = np.ones((2 * rows + 1, 2 * rows * ctx.vertical_width + 1), dtype=bool)
    return ndimage.binary_erosion(ctx.patch.dry, structure=structure, border_value=1)


def _min_area(ctx: SiteContext) -> int:
    room_rows = ctx.setting("room_rows")
    low = int(room_rows[0])
    return 2 * (math.ceil(low * ctx.aspect) + 2) * (low + 2)


def _outline(ctx: SiteContext, buildable: np.ndarray) -> Optional[np.ndarray]:
    """Return the structure's outline: the seeded shape on buildable ground, or None if there is no room for rooms."""
    stream = rng.derive(ctx.seed, "site.shape")
    area = _min_area(ctx)
    mask = largest_component(outline(str(ctx.setting("shape")), stream, ctx.cols, ctx.rows, area) & buildable)
    if int(mask.sum()) < area:
        mask = largest_component(SHAPES["rectangle"](stream, ctx.cols, ctx.rows) & buildable)
    return mask if int(mask.sum()) >= area else None


def _trim_to_land(grid: np.ndarray, dry: np.ndarray) -> None:
    """Cut away any structure that strayed over water, and keep walls off the water too."""
    grid[~dry & (grid != _VOID)] = _VOID
    add_walls(grid)
    grid[~dry & (grid == _WALL)] = _VOID


def _room_structure(
    ctx: SiteContext, mask: np.ndarray, stream: random.Random, access: list[Point], ratio: float
) -> tuple[np.ndarray, list[Rect]]:
    """Carve rooms and corridors inside ``mask`` and seal them into a solid building; return ``(grid, rooms)``."""
    grid = np.full((ctx.rows, ctx.cols), _VOID, dtype=np.uint8)
    width = ctx.vertical_width
    room_rows = tuple(int(v) for v in ctx.setting("room_rows"))
    candidates = bsp_rooms(stream, ctx.cols, ctx.rows, (room_rows[0], room_rows[1]), ctx.aspect)
    rooms = [r for r in candidates if rect_in_mask(r, mask)]
    if len(rooms) < 2:
        rooms = [r for r in candidates if mask[room_center(r)[1], room_center(r)[0]]] or candidates
    for room in rooms:
        carve_room(grid, room)
    centres = [room_center(r) for r in rooms]
    for a, b in zip(centres, centres[1:], strict=False):
        carve_corridor(grid, a, b, width)
    if len(centres) >= 3:
        for _ in range(int(len(centres) * ratio)):
            i, j = stream.randint(0, len(centres) - 1), stream.randint(0, len(centres) - 1)
            if i != j:
                carve_corridor(grid, centres[i], centres[j], width)
    for cell in access:
        force_floor_access(grid, cell, rooms, width)
    connect_floor_components(grid, width)
    grid[(mask | (grid != _VOID)) & (grid == _VOID)] = _WALL
    add_walls(grid)
    fill_enclosed(grid)
    _trim_to_land(grid, ctx.patch.dry)
    return grid, rooms


def _front(grid: np.ndarray, door: Point) -> Optional[Point]:
    """Return the open cell outside ``door``, where a street reaches it."""
    rows, cols = grid.shape
    x, y = door
    for step_x, step_y in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        nx, ny = x + step_x, y + step_y
        if 0 <= nx < cols and 0 <= ny < rows and int(grid[ny, nx]) == _VOID:
            return nx, ny
    return None


def _enter(ctx: SiteContext, grid: np.ndarray, rooms: list[Rect]) -> Optional[Point]:
    """Punch the ground-floor entrance toward the nearest road gate and lay a street to it; return the door."""
    gates = ctx.patch.gates
    target = (gates[0].col, gates[0].row) if gates else None
    door = punch_entrance(grid, rooms, rng.derive(ctx.seed, "site.layout", "door"), target, ctx.vertical_width)
    if door is not None and gates:
        front = _front(grid, door)
        if front is not None:
            lay_street(grid, ctx.patch.dry, (gates[0].col, gates[0].row), front, ctx.street_rules)
    return door


def _build(ctx: SiteContext) -> Optional[tuple[np.ndarray, list[Rect], set[Point]]]:
    """Build one floor's walls, corridors, stairs and entrance; return ``(grid, rooms, reserved cells)``."""
    mask = _outline(ctx, _buildable(ctx))
    if mask is None:
        return None
    links = stair_links(ctx.seed, mask, ctx.floor_count)
    up, down = floor_links(links, ctx.floor, ctx.lowest_floor, ctx.floor_count)
    ratio = float(ctx.setting("extra_corridors")[ctx.kind])
    access = [cell for cell in (up, down) if cell is not None]
    grid, rooms = _room_structure(ctx, mask, rng.derive(ctx.seed, "site.layout", ctx.floor), access, ratio)
    reserved: set[Point] = set()
    if ctx.floor == 0:
        door = _enter(ctx, grid, rooms)
        if door is not None:
            reserved.add(door)
    reserved |= stamp_stairs(grid, up, down)
    return grid, rooms, reserved


def _furnish_stream(ctx: SiteContext) -> random.Random:
    return rng.derive(ctx.seed, "site.furnish", ctx.floor)


def _clutter(ctx: SiteContext) -> float:
    return float(ctx.setting("clutter_density"))


def _furnish_setting(ctx: SiteContext, key: str) -> float:
    return float(ctx.config.get(f"sites.furnish.{key}"))


@layout("dungeon")
def build_dungeon(ctx: SiteContext) -> Optional[np.ndarray]:
    """A dungeon floor: rooms and warrens, with loot growing the deeper you go."""
    built = _build(ctx)
    if built is None:
        return None
    grid, rooms, reserved = built
    room_mask = np.zeros(grid.shape, dtype=bool)
    for rx, ry, rw, rh in rooms:
        room_mask[ry : ry + rh, rx : rx + rw] = True
    special = (grid == int(Cell.DOOR)) | (grid == int(Cell.STAIRS_UP)) | (grid == int(Cell.STAIRS_DOWN))
    protected = (grid == _FLOOR) & (~room_mask | adjacent(special))
    depth = 0.0 if ctx.floor_count <= 1 else (ctx.top_floor - ctx.floor) / (ctx.floor_count - 1)
    density = _clutter(ctx) * (1.0 + _furnish_setting(ctx, "depth_density_gain") * depth)
    table = _table(ctx, _furnish_setting(ctx, "chest_depth_gain") * depth)
    chance = _furnish_setting(ctx, "corridor_rubble_chance")

    def choose(stream: random.Random, x: int, y: int) -> Optional[Cell]:
        if protected[y, x]:
            return Cell.RUBBLE if stream.random() < chance else None
        return weighted_choice(stream, table)

    scatter(grid, _furnish_stream(ctx), free_floor(grid, reserved), density, choose)
    keep_reachable(grid, sorted(reserved))
    return grid


@layout("tower")
def build_tower(ctx: SiteContext) -> Optional[np.ndarray]:
    """A tower floor: quarters with a study, beds and storage; the top floor is a bare lookout."""
    built = _build(ctx)
    if built is None:
        return None
    grid, _rooms, reserved = built
    density = _clutter(ctx) * (_furnish_setting(ctx, "lookout_density") if ctx.floor == ctx.top_floor else 1.0)
    table = _table(ctx)
    scatter(
        grid,
        _furnish_stream(ctx),
        free_floor(grid, reserved),
        density,
        lambda stream, _x, _y: weighted_choice(stream, table),
    )
    keep_reachable(grid, sorted(reserved))
    return grid


@layout("ruin")
def build_ruin(ctx: SiteContext) -> Optional[np.ndarray]:
    """A ruin: a building, eroded into breaches and rubble, strewn with debris."""
    built = _build(ctx)
    if built is None:
        return None
    grid, _rooms, reserved = built
    roll = rng.derive_numpy(ctx.seed, "site.erode").random(grid.shape)
    erosion = float(ctx.setting("ruin_erosion"))
    grid[(grid == _WALL) & (roll < erosion)] = _VOID
    grid[(grid == _FLOOR) & (roll < erosion * _furnish_setting(ctx, "ruin_crack"))] = int(Cell.RUBBLE)
    density = min(0.9, _clutter(ctx) * _furnish_setting(ctx, "ruin_density"))
    table = _table(ctx)
    scatter(
        grid,
        _furnish_stream(ctx),
        free_floor(grid, reserved),
        density,
        lambda stream, _x, _y: weighted_choice(stream, table),
    )
    return grid
