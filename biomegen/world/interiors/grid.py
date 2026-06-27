"""Core interior-grid construction - the shared toolkit every per-archetype builder uses.

An interior is a 2-D ``uint8`` array of :class:`~biomegen.world.tile.Cell` values, generated **lazily
and deterministically** from a POI's ``interior_seed``. It is produced once at a *canonical*
resolution - ``interiors.cells_per_tile`` detail cells per world tile across the POI footprint - then
the detail renderer samples that single artifact at whatever resolution the active view provides. So
the ``zoom`` and ``local`` views are coarse vs fine samplings of the **same** interior, exactly as the
biome blend makes them coarse/fine samplings of the same world (see :mod:`biomegen.render.zoom_view`).

Builders register themselves by POI kind in :data:`INTERIOR_BUILDERS`. :func:`build_interior` looks one
up, runs it (memoised by :func:`functools.lru_cache` on the cheap scalar inputs so re-opening a POI is
free), and returns the immutable base grid. Runtime edits are layered on top by the caller via
:meth:`biomegen.world.overlay.Overlay.apply_interior`, never by mutating the cached base.

Partitioners are themselves swappable via the :data:`PARTITIONS` registry (``interiors.partition``);
the in-house **BSP** (binary space partition) is the default - the classic roguelike dungeon layout:
recursively cut the area into sub-rectangles, drop a room in each leaf, then connect rooms with
corridors (see e.g. Bjorn Bergsson / RogueBasin "Basic BSP Dungeon generation").
"""

from __future__ import annotations

import functools
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, List, Optional, Tuple

import numpy as np
from scipy import ndimage

from ...config.model import Config
from ...registry import Registry
from ...util import rng
from ..entities import POI
from ..tile import Cell, WaterType

if TYPE_CHECKING:  # avoid a runtime import cycle (world.py never imports the interiors layer)
    from ..world import World

# A rectangle ``(x, y, w, h)`` in interior-grid cells.
Rect = Tuple[int, int, int, int]

# Builders keyed by POI kind ("dungeon", "tower", ...). A kind without an entry has no interior yet
# and falls back to its biome-map marker in the detail views.
INTERIOR_BUILDERS: Registry = Registry("interior_builder")
register_interior = INTERIOR_BUILDERS.register

# Swappable space-partition algorithms (selected by ``interiors.partition``).
PARTITIONS: Registry = Registry("interior_partition")

# Swappable OUTER-BOUNDARY shapes (selected by ``interiors.shape``). A shape is a function
# ``(rgen, grid_w, grid_h) -> np.ndarray[bool]`` returning the cells *inside* the structure, so the
# dungeon's footprint can be an organic blob / cave / diamond / ... instead of the full rectangle.
# See :mod:`biomegen.world.interiors.shapes`. The special selector ``"mixed"`` is resolved by the
# builder to a per-dungeon random pick (so no two dungeons share a shape and none is square).
SHAPES: Registry = Registry("interior_shape")
MIXED_SHAPE = "mixed"  # config value meaning "pick a concrete shape per dungeon"

# The "structure outline" - walls, doors and stairs only. Used by the OVERVIEW biome map, where each
# interior is squeezed into ~one char per world tile and only the wall plan can read at that size.
STRUCTURAL: frozenset = frozenset({int(Cell.WALL), int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)})

# Cells drawn at the ZOOM scale: the whole building *shell* - walls, floor, doors, stairs, water and
# paths - but NOT furniture/clutter (which stays a LOCAL-only detail). Drawing the floor (not just the
# walls) makes the dungeon read as a solid, filled-in structure rather than an outline with terrain
# showing through. The LOCAL scale still draws every non-void cell (the full furnished interior).
ZOOM_VISIBLE: frozenset = STRUCTURAL | frozenset({int(Cell.FLOOR), int(Cell.WATER), int(Cell.PATH)})


@dataclass(frozen=True)
class InteriorCtx:
    """Everything a builder needs for one (POI, floor), as plain hashable scalars.

    Construced by :func:`build_interior` and passed to the registered builder. The fields double as
    the memoisation key, so two opens of the same floor of the same POI reuse one grid.
    """

    kind: str
    interior_seed: int
    floor: int
    lowest_floor: int
    floor_count: int
    grid_w: int
    grid_h: int
    room_min: int
    room_max: int
    clutter_density: float
    partition: str
    shape: str
    ruin_erosion: float = 0.45  # fraction of a ruined structure's walls/floor carved away (ruin only)
    # Packed (grid_h, grid_w) bool mask of BUILDABLE cells (dry land, already eroded by the coast
    # margin) for a coastal POI - water and the coast strip are False so the builder leaves them VOID
    # and the real water/biome shows through. Empty ``b""`` means "unconstrained" (all land): an inland
    # POI builds exactly as before and shares its cache entry with the no-terrain build. Bytes are
    # hashable, so this stays part of the LRU cache key and the build is still a pure function of it.
    land_mask_bytes: bytes = b""
    # Compass direction (sx, sy ∈ {-1,0,1}) the connecting road arrives from, or (0, 0) for none. When
    # set, the entry-floor door is punched on the wall facing this side (instead of a random wall) so the
    # interior entrance lines up with the road. Part of the cache key, so the build stays a pure function.
    entrance_side: Tuple[int, int] = (0, 0)

    @property
    def top_floor(self) -> int:
        """The highest floor index (ground/entry level): dungeons descend, so this is ``0``."""
        return self.lowest_floor + self.floor_count - 1


# --------------------------------------------------------------------------- footprint geometry
def footprint_cells(poi: POI, config: Config) -> Tuple[int, int]:
    """Return the canonical interior grid size ``(w, h)`` in cells for ``poi`` (0,0 if no footprint)."""
    fw, fh = poi.footprint
    if fw <= 0 or fh <= 0:
        return 0, 0
    cpt = max(1, int(config.get("interiors.cells_per_tile")))
    return int(fw) * cpt, int(fh) * cpt


def footprint_origin(poi: POI) -> Tuple[int, int]:
    """Return the top-left world tile of ``poi``'s footprint, centred on its anchor."""
    fw, fh = poi.footprint
    return poi.x - int(fw) // 2, poi.y - int(fh) // 2


# --------------------------------------------------------------------------- terrain-aware buildable area
def buildable_mask_bytes(
    poi: POI, world: "World", grid_w: int, grid_h: int, cells_per_tile: int, coast_margin: int
) -> bytes:
    """Packed buildable-cell mask so a coastal structure forms *around* water instead of over it.

    The footprint's water tiles are upsampled to the canonical cell grid and a ``coast_margin`` ring of
    dry cells beside them is also excluded (so a strip of bare biome floor reads as a little coast, like
    the biome blend). Off-map tiles count as land. Returns ``b""`` when the whole footprint is dry land -
    i.e. *unconstrained* - so an inland POI keeps its exact previous layout and cache entry.
    """
    fw, fh = poi.footprint
    tx0, ty0 = poi.x - int(fw) // 2, poi.y - int(fh) // 2
    # Tile-level land mask over the footprint window; off-map (clipped at the border) stays land.
    land_tiles = np.ones((int(fh), int(fw)), dtype=bool)
    y0, y1 = max(0, ty0), min(world.height, ty0 + int(fh))
    x0, x1 = max(0, tx0), min(world.width, tx0 + int(fw))
    if y1 > y0 and x1 > x0:
        wet = world.water_type[y0:y1, x0:x1] != int(WaterType.NONE)
        land_tiles[y0 - ty0 : y1 - ty0, x0 - tx0 : x1 - tx0] = ~wet
    if land_tiles.all():
        return b""  # no water in range -> unconstrained (identical to the inland build)
    # Upsample tiles -> canonical cells, then pull the buildable area back from the water by the margin.
    land_cells = np.repeat(np.repeat(land_tiles, cells_per_tile, axis=0), cells_per_tile, axis=1)
    land_cells = land_cells[:grid_h, :grid_w]
    if coast_margin > 0:
        # border_value=1: the footprint edge (off-map = land) must not erode the structure inward.
        land_cells = ndimage.binary_erosion(land_cells, iterations=coast_margin, border_value=1)
    return np.ascontiguousarray(land_cells).tobytes()


def ctx_buildable(ctx: InteriorCtx) -> Optional[np.ndarray]:
    """Reconstruct ``ctx``'s buildable-cell bool mask, or ``None`` when unconstrained (all land)."""
    if not ctx.land_mask_bytes:
        return None
    return np.frombuffer(ctx.land_mask_bytes, dtype=bool).reshape(ctx.grid_h, ctx.grid_w)


def sample_rect(grid: np.ndarray, r0: int, c0: int, span_rows: int, span_cols: int, max_rows: int, max_cols: int):
    """Nearest-neighbour sample ``grid`` into a ``span_rows x span_cols`` screen rect at ``(r0, c0)``.

    Yields ``(row, col, cell_int)`` for each rect cell that lands within ``[0, max_rows) x
    [0, max_cols)`` (the rect may start off-screen / overflow; those cells are skipped). This is the one
    place the canonical interior artifact is down-sampled to a view's resolution, shared by the biome-map
    and zoom/local stamps so they agree on the mapping (see the module docstring on coarse/fine sampling).
    """
    gh, gw = grid.shape
    for dr in range(span_rows):
        r = r0 + dr
        if 0 <= r < max_rows:
            sy = min(dr * gh // span_rows, gh - 1)
            for dc in range(span_cols):
                c = c0 + dc
                if 0 <= c < max_cols:
                    sx = min(dc * gw // span_cols, gw - 1)
                    yield r, c, int(grid[sy, sx])


# --------------------------------------------------------------------------- BSP partition
# Tuning knobs for the recursive split. Lower stop probability + deeper recursion => more (smaller)
# leaves => more rooms and corridors. Bumped for Phase 5 dungeons (denser warrens).
_BSP_MAX_DEPTH = 6  # recursion ceiling (was 5)
_BSP_STOP_PROB = 0.12  # chance a small-enough leaf stops splitting early (was 0.3)


def _split(rgen, x: int, y: int, w: int, h: int, room_min: int, room_max: int, depth: int, out: List[Rect]) -> None:
    """Recursively cut ``(x, y, w, h)`` into leaves no smaller than ``room_min`` per side."""
    min_leaf = room_min + 1  # a leaf must hold a room plus a little slack for an interior wall border
    can_v = w >= 2 * min_leaf  # room to cut along the x axis (two side-by-side children)
    can_h = h >= 2 * min_leaf  # room to cut along the y axis (two stacked children)
    small_enough = w <= room_max and h <= room_max
    if depth >= _BSP_MAX_DEPTH or not (can_v or can_h) or (small_enough and rgen.random() < _BSP_STOP_PROB):
        if w >= room_min and h >= room_min:
            out.append((x, y, w, h))
        return
    # Prefer cutting the longer axis so leaves stay roughly square.
    cut_vertical = can_v if not can_h else (w >= h if can_v else False)
    if cut_vertical:
        cut = rgen.randint(min_leaf, w - min_leaf)
        _split(rgen, x, y, cut, h, room_min, room_max, depth + 1, out)
        _split(rgen, x + cut, y, w - cut, h, room_min, room_max, depth + 1, out)
    else:
        cut = rgen.randint(min_leaf, h - min_leaf)
        _split(rgen, x, y, w, cut, room_min, room_max, depth + 1, out)
        _split(rgen, x, y + cut, w, h - cut, room_min, room_max, depth + 1, out)


@PARTITIONS.register("bsp")
def bsp_rooms(rgen, grid_w: int, grid_h: int, room_min: int, room_max: int) -> List[Rect]:
    """Binary space partition: carve the grid (inside a 1-cell border) into leaf rooms.

    Returns a list of room rectangles. A 1-cell border is reserved on every side so the wall pass
    always has a void cell to turn into the outer wall.
    """
    leaves: List[Rect] = []
    inner_w, inner_h = grid_w - 2, grid_h - 2
    if inner_w < room_min or inner_h < room_min:
        return [(1, 1, max(1, inner_w), max(1, inner_h))]
    _split(rgen, 1, 1, inner_w, inner_h, room_min, room_max, 0, leaves)
    rooms: List[Rect] = []
    for lx, ly, lw, lh in leaves:
        rw = rgen.randint(room_min, min(room_max, lw))
        rh = rgen.randint(room_min, min(room_max, lh))
        rx = lx + rgen.randint(0, lw - rw)
        ry = ly + rgen.randint(0, lh - rh)
        rooms.append((rx, ry, rw, rh))
    return rooms or [(1, 1, inner_w, inner_h)]


# --------------------------------------------------------------------------- carving primitives
def room_center(room: Rect) -> Tuple[int, int]:
    rx, ry, rw, rh = room
    return rx + rw // 2, ry + rh // 2


def carve_room(grid: np.ndarray, room: Rect, cell: int = int(Cell.FLOOR)) -> None:
    rx, ry, rw, rh = room
    grid[ry : ry + rh, rx : rx + rw] = cell


def carve_corridor(grid: np.ndarray, a: Tuple[int, int], b: Tuple[int, int], cell: int = int(Cell.FLOOR)) -> None:
    """Carve an L-shaped corridor between cell centres ``a`` and ``b`` (horizontal then vertical)."""
    (ax, ay), (bx, by) = a, b
    grid[ay, min(ax, bx) : max(ax, bx) + 1] = cell
    grid[min(ay, by) : max(ay, by) + 1, bx] = cell


def add_walls(grid: np.ndarray) -> None:
    """Turn every VOID cell touching a non-void cell (8-neighbourhood) into a WALL, in place."""
    occupied = grid != int(Cell.VOID)
    # 8-connected dilation; border_value=0 keeps structure on one edge from leaking across to the other.
    dil = ndimage.binary_dilation(occupied, structure=np.ones((3, 3), bool), border_value=0)
    grid[dil & ~occupied] = int(Cell.WALL)


def force_floor_access(grid: np.ndarray, cell: Tuple[int, int], rooms: List[Rect]) -> None:
    """Guarantee ``cell`` is reachable FLOOR: carve a 3x3 pocket and a corridor to the nearest room.

    Used to plant the aligned stair shafts: their positions are fixed across floors, so each floor
    must accommodate them regardless of where its own BSP rooms landed.
    """
    cx, cy = cell
    h, w = grid.shape
    x0, x1 = max(1, cx - 1), min(w - 1, cx + 2)
    y0, y1 = max(1, cy - 1), min(h - 1, cy + 2)
    grid[y0:y1, x0:x1] = int(Cell.FLOOR)
    if rooms:
        nearest = min(rooms, key=lambda r: (room_center(r)[0] - cx) ** 2 + (room_center(r)[1] - cy) ** 2)
        carve_corridor(grid, (cx, cy), room_center(nearest))


def flood_components(mask: np.ndarray) -> List[List[Tuple[int, int]]]:
    """Return the 4-connected components of the True cells of ``mask`` as lists of ``(y, x)``.

    The single connected-components primitive the interior toolkit is built on (floor regions, shape
    masks, exterior void). Components are discovered in row-major order and each is filled depth-first,
    so the output order is deterministic - callers (e.g. :func:`connect_floor_components`) may rely on
    it. (The world-scale pipeline uses :func:`biomegen.util.geometry.label_by_value`; this stays local
    because it must preserve that exact DFS ordering and operates on these small canonical grids.)
    """
    h, w = mask.shape
    seen = np.zeros_like(mask)
    comps: List[List[Tuple[int, int]]] = []
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            comp: List[Tuple[int, int]] = []
            stack = [(sy, sx)]
            while stack:
                y, x = stack.pop()
                if not (0 <= y < h and 0 <= x < w) or seen[y, x] or not mask[y, x]:
                    continue
                seen[y, x] = True
                comp.append((y, x))
                stack += [(y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)]
            comps.append(comp)
    return comps


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Return only the largest 4-connected True component of ``mask`` (drops detached fragments)."""
    labels, n = ndimage.label(mask)  # 4-connectivity (default cross structure), labelled in scan order
    if n == 0:
        return np.zeros_like(mask)
    # Biggest label by pixel count; bincount index 0 is the background, so offset past it.
    return labels == int(np.bincount(labels.ravel())[1:].argmax()) + 1


def connect_floor_components(grid: np.ndarray) -> None:
    """Carve corridors until every FLOOR cell is reachable from every other, in place.

    Carving rooms/corridors inside an organic boundary can leave a room or stair pocket cut off from
    the rest (the shape pinches between them). This joins each stray component to the largest one with
    a straight L-corridor through the intervening rock, guaranteeing the whole dungeon is traversable
    regardless of the boundary shape. A no-op when the floor is already one component.
    """
    comps = flood_components(grid == int(Cell.FLOOR))
    if len(comps) <= 1:
        return
    comps.sort(key=len, reverse=True)
    main = list(comps[0])  # grow the largest component, linking every other component into it
    for comp in comps[1:]:
        cy, cx = comp[len(comp) // 2]  # a representative cell of the stray component
        ny, nx = min(main, key=lambda p: (p[0] - cy) ** 2 + (p[1] - cx) ** 2)  # nearest main cell
        carve_corridor(grid, (cx, cy), (nx, ny))
        main.extend(comp)


def stair_links(interior_seed: int, grid_w: int, grid_h: int, floor_count: int) -> List[Tuple[int, int]]:
    """Return one cell position per **adjacent floor pair** (``floor_count - 1`` of them).

    Link ``i`` connects the lower floor ``lowest_floor + i`` (its STAIRS_UP) to the upper floor
    ``lowest_floor + i + 1`` (its STAIRS_DOWN) - so a staircase you descend lands exactly on the
    up-staircase of the floor below (adjacent floors match) while *different* pairs use *different*
    cells (stairs aren't pinned to one shared column for the whole dungeon). The whole sequence is a
    pure function of ``interior_seed``, so every floor rebuilds the identical set of links and the
    shared cells line up. :func:`force_floor_access` later makes each link reachable on both its floors.
    """
    sr = rng.derive(interior_seed, "interior.shaft")
    margin = 2
    lo_x, hi_x = margin, max(margin, grid_w - 1 - margin)
    lo_y, hi_y = margin, max(margin, grid_h - 1 - margin)

    def pick() -> Tuple[int, int]:
        return sr.randint(lo_x, hi_x), sr.randint(lo_y, hi_y)

    links: List[Tuple[int, int]] = []
    used: set = set()
    for _ in range(max(0, floor_count - 1)):
        pos = pick()
        tries = 0
        # Keep every link on its own cell so no two staircases ever overlap (and within a floor the
        # up- and down-stairs - two consecutive links - are guaranteed distinct).
        while pos in used and tries < 50:
            pos = pick()
            tries += 1
        used.add(pos)
        links.append(pos)
    return links


def border_void(grid: np.ndarray) -> np.ndarray:
    """Return the boolean mask of VOID cells reachable from the grid border (4-connectivity).

    This is the structure's "exterior" - the open terrain around it. VOID *not* in this set is a
    pocket fully ringed by the structure.
    """
    void = grid == int(Cell.VOID)
    # Seed from the border VOID cells and flood through VOID (4-connected): the exterior is exactly the
    # VOID reachable from an edge; any VOID left unmarked is an enclosed pocket.
    seed = np.zeros_like(void)
    seed[0, :] = seed[-1, :] = seed[:, 0] = seed[:, -1] = True
    return ndimage.binary_propagation(seed & void, mask=void)


def fill_enclosed(grid: np.ndarray) -> None:
    """Turn VOID that is *walled off* from the exterior into solid WALL, in place.

    Any VOID cell not reachable from the border (:func:`border_void`) is an interior pocket fully
    ringed by walls; it becomes WALL so the renderer draws solid masonry there instead of letting the
    surrounding terrain show through an inaccessible gap. The exterior VOID is left untouched, so
    terrain still shows *around* the structure's organic outline.
    """
    void = grid == int(Cell.VOID)
    grid[void & ~border_void(grid)] = int(Cell.WALL)


_PASSABLE: frozenset = frozenset(
    {int(Cell.FLOOR), int(Cell.RUBBLE), int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)}
)


def clear_blocking_furniture(grid: np.ndarray, specials: List[Tuple[int, int]]) -> None:
    """Clear any furniture that blocks the route between the ``specials`` (stairs/doors), in place.

    Furniture must never trap a stairway or the entrance: while the dungeon is always *structurally*
    connected (carved corridors join every region), a dense furnishing pass can wall off a junction
    with non-passable items. This walks the shortest cell path from the first special to each of the
    others (through anything that is not solid rock/void) and turns any blocking furniture on that path
    back into FLOOR - the minimal edit that guarantees every stair and door is mutually reachable.
    """
    if len(specials) < 2:
        return
    h, w = grid.shape
    solid = (int(Cell.WALL), int(Cell.VOID))
    start = specials[0]
    parent: dict = {start: None}  # BFS tree over non-solid cells -> shortest paths from `start`
    dq = deque([start])
    while dq:
        x, y = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in parent and int(grid[ny, nx]) not in solid:
                parent[(nx, ny)] = (x, y)
                dq.append((nx, ny))
    for sp in specials[1:]:
        node = sp
        while node is not None and node in parent:
            x, y = node
            if int(grid[y, x]) not in _PASSABLE:
                grid[y, x] = int(Cell.FLOOR)  # carve the blocking furniture out of the through-route
            node = parent[node]


def punch_entrance(
    grid: np.ndarray, rooms: List[Rect], rgen, entrance_side: Tuple[int, int] = (0, 0)
) -> Optional[Tuple[int, int]]:
    """Punch an entrance DOOR through the outer wall and tunnel inward to the nearest room.

    With a solid-filled organic dungeon the outer wall is backed by rock (not floor), so a plain
    boundary door would open onto stone. Instead we pick a WALL cell on the exterior boundary (a wall
    adjacent to border-connected VOID, or the grid edge), carve an L-corridor from it to the nearest
    room centre - an entrance passage through the rock - and set the boundary cell to DOOR. Run on the
    entry (top) floor only. Returns the door's ``(x, y)``, or None if there is no boundary wall/room.

    When ``entrance_side`` is a non-zero compass direction, the door is chosen from the boundary walls on
    that side of the structure (the side the connecting road arrives from) rather than uniformly at
    random, so the entrance faces the road; a seeded choice still breaks ties among that side's walls.
    """
    h, w = grid.shape
    wall = int(Cell.WALL)
    exterior = border_void(grid)

    def is_exterior(y: int, x: int) -> bool:
        return not (0 <= y < h and 0 <= x < w) or bool(exterior[y, x])  # off-grid counts as exterior

    candidates: List[Tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if grid[y, x] != wall:
                continue
            if any(is_exterior(y + dy, x + dx) for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))):
                candidates.append((x, y))
    if not candidates or not rooms:
        return None
    candidates.sort()  # stable order so the seeded choice is reproducible
    sx, sy = entrance_side
    if (sx, sy) != (0, 0):
        # Bias toward the road-facing side: keep the candidates furthest in that direction (within a
        # one-cell band of the extreme) and pick among them, so the door faces the road but still varies.
        cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
        proj = {(x, y): (x - cx) * sx + (y - cy) * sy for (x, y) in candidates}
        best = max(proj.values())
        candidates = [c for c in candidates if proj[c] >= best - 1.0]
    x, y = rgen.choice(candidates)
    nearest = min(rooms, key=lambda r: (room_center(r)[0] - x) ** 2 + (room_center(r)[1] - y) ** 2)
    carve_corridor(grid, (x, y), room_center(nearest))  # tunnel through the rock to a room
    grid[y, x] = int(Cell.DOOR)
    return x, y


# --------------------------------------------------------------------------- shaped room-structure
# The generic "rooms inside an organic boundary" recipe every solid structure builder shares. A
# concrete builder (dungeon, and later tower/ruin/...) calls resolve_shape -> build_room_structure,
# then layers its own specifics (vertical circulation, furnishing) on top. Keeping it here means the
# next builder reuses the (subtle, order-sensitive) fill/wall/seal sequence instead of copying it.


def resolve_shape(ctx: InteriorCtx, grid_w: int, grid_h: int) -> np.ndarray:
    """Return the structure's boundary mask for ``ctx`` (floor-independent, so all floors share it).

    ``ctx.shape`` selects the algorithm; :data:`MIXED_SHAPE` picks one per structure (seeded on the
    interior seed alone, never the floor) from every registered shape except the plain rectangle, so no
    two structures look alike and none is square. If the chosen shape is too small to hold a couple of
    rooms for this footprint, fall back to the full rectangle (a consistent, floor-independent choice).
    """
    shape_rgen = rng.derive(ctx.interior_seed, "interior.shape")
    name = ctx.shape
    if name == MIXED_SHAPE:
        name = shape_rgen.choice([n for n in SHAPES.names() if n != "rectangle"])
    mask = SHAPES.get(name)(shape_rgen, grid_w, grid_h)
    # Guarantee enough area for at least two rooms (plus their walls); else use the rectangle.
    if int(mask.sum()) < 2 * (ctx.room_min + 2) ** 2:
        mask = SHAPES.get("rectangle")(shape_rgen, grid_w, grid_h)
    return mask


def rect_in_mask(rect: Rect, mask: np.ndarray) -> bool:
    """Return whether the whole room rectangle lies inside the shape ``mask``."""
    rx, ry, rw, rh = rect
    return bool(mask[ry : ry + rh, rx : rx + rw].all())


def carve_extra_corridors(rgen, grid: np.ndarray, centers: List[Tuple[int, int]], ratio: float) -> None:
    """Carve ``ratio * len(centers)`` extra corridors between random room centres (loops + passages)."""
    n = len(centers)
    if n < 3:
        return
    for _ in range(int(n * ratio)):
        i, j = rgen.randint(0, n - 1), rgen.randint(0, n - 1)
        if i != j:
            carve_corridor(grid, centers[i], centers[j])


def build_room_structure(
    ctx: InteriorCtx,
    mask: np.ndarray,
    rgen,
    access_points: Tuple[Tuple[int, int], ...] = (),
    extra_corridor_ratio: float = 0.0,
) -> Tuple[np.ndarray, List[Rect]]:
    """Carve rooms + corridors inside ``mask`` and seal it into a solid building. Returns ``(grid, rooms)``.

    The shared skeleton for any solid, room-based structure: partition into rooms (kept to those that
    fit inside the boundary so the outline stays organic), connect their centres into one chain plus a
    few extra loops, force-carve any ``access_points`` (e.g. stair cells) reachable, repair connectivity,
    then fill the boundary (and everything carved) solid with WALL and seal it - leaving VOID outside so
    terrain shows around the organic outline. Builders layer their own circulation/furnishing on top.
    """
    gw, gh = ctx.grid_w, ctx.grid_h
    grid = np.full((gh, gw), int(Cell.VOID), dtype=np.uint8)

    # On the coast the structure forms around the water: confine the outline to the largest contiguous
    # buildable (dry) blob so rooms and corridors stay on land and the water shows through as VOID.
    buildable = ctx_buildable(ctx)
    if buildable is not None:
        confined = largest_component(mask & buildable)
        if confined.any():
            mask = confined

    rooms_all = PARTITIONS.get(ctx.partition)(rgen, gw, gh, ctx.room_min, ctx.room_max)
    rooms = [r for r in rooms_all if rect_in_mask(r, mask)]
    if len(rooms) < 2:  # rare: shape didn't admit two full rooms - keep by centre (lets them shape it)
        rooms = [r for r in rooms_all if mask[room_center(r)[1], room_center(r)[0]]] or rooms_all
    for room in rooms:
        carve_room(grid, room)
    centers = [room_center(r) for r in rooms]
    for a, b in zip(centers, centers[1:], strict=False):
        carve_corridor(grid, a, b)
    carve_extra_corridors(rgen, grid, centers, extra_corridor_ratio)

    for cell in access_points:
        force_floor_access(grid, cell, rooms)
    connect_floor_components(grid)  # the boundary can pinch regions apart - rejoin before sealing

    # Fill the structure solid: the shape plus everything carved becomes the extent; interior VOID
    # turns to rock. Then ring exposed floor with wall and seal any enclosed pocket.
    extent = mask | (grid != int(Cell.VOID))
    grid[extent & (grid == int(Cell.VOID))] = int(Cell.WALL)
    add_walls(grid)
    fill_enclosed(grid)
    return grid, rooms


# --------------------------------------------------------------------------- vertical circulation
# Shared by every stacked, multi-floor builder (dungeon descends, tower ascends). The two functions
# bracket build_room_structure: floor_links() picks this floor's stair cells up front (so they can be
# passed as access_points and force-carved reachable), and stamp_circulation() writes them in - plus
# the exterior entrance - once the floor is sealed.


def floor_links(ctx: InteriorCtx) -> Tuple[Optional[Tuple[int, int]], Optional[Tuple[int, int]]]:
    """Return this floor's ``(up, down)`` stair cells (either may be None) for a stacked structure.

    ``up`` links to the floor above (``floor + 1``), ``down`` to the one below (``floor - 1``), both
    drawn from the per-pair :func:`stair_links` list so adjacent floors share a cell and the shafts
    line up vertically. The topmost floor has no up-stair; the lowest has no down-stair.
    """
    links = stair_links(ctx.interior_seed, ctx.grid_w, ctx.grid_h, ctx.floor_count)
    i = ctx.floor - ctx.lowest_floor  # 0 at the deepest/lowest floor
    up = links[i] if ctx.floor < ctx.top_floor else None
    down = links[i - 1] if ctx.floor > ctx.lowest_floor else None
    return up, down


def stamp_circulation(
    ctx: InteriorCtx,
    grid: np.ndarray,
    rooms: List[Rect],
    up: Optional[Tuple[int, int]],
    down: Optional[Tuple[int, int]],
) -> set:
    """Stamp the stair cells and (ground/entry floor only) punch the exterior door; return reserved cells.

    Called after :func:`build_room_structure` has carved and sealed the floor (the stair cells having
    been force-carved reachable via its ``access_points``). The ground/entry level is **floor 0** by the
    :func:`biomegen.pipeline.poi_rules.floors_for` convention - dungeons descend to negative floors and
    towers rise to positive ones, so floor 0 is the level you walk in at either way - and that is where
    the exterior entrance is punched (a door on the now-final outer wall, tunnelled to the nearest
    room). The returned ``(x, y)`` set (stairs + door) is what the furnishing pass must keep clear.
    """
    reserved: set = set()
    if up is not None:
        grid[up[1], up[0]] = int(Cell.STAIRS_UP)
        reserved.add(up)
    if down is not None:
        grid[down[1], down[0]] = int(Cell.STAIRS_DOWN)
        reserved.add(down)
    if ctx.floor == 0:  # ground/entry level (the top floor for dungeons, the bottom one for towers)
        door = punch_entrance(grid, rooms, rng.derive(ctx.interior_seed, "interior.door"), ctx.entrance_side)
        if door is not None:
            reserved.add(door)
    return reserved


# --------------------------------------------------------------------------- furnishing primitives
# The shared scatter machinery every builder's furnishing pass is built on: enumerate the free floor,
# pick a (reproducible) sample of it, and dress each picked cell from a weighted table. Each builder
# supplies only its own furniture weights and any cells to protect.


def adjacent_mask(mask: np.ndarray) -> np.ndarray:
    """Return the 4-neighbourhood of ``mask`` (cells orthogonally adjacent to a True cell).

    Used to protect aprons: the floor cells next to a door or stairway that furnishing should leave
    clear so the opening stays passable.
    """
    out = np.zeros_like(mask)
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def free_floor_cells(grid: np.ndarray, reserved: Iterable[Tuple[int, int]] = ()) -> List[Tuple[int, int]]:
    """Return the sorted ``(x, y)`` FLOOR cells of ``grid`` not in ``reserved`` (stable sample order)."""
    keep = set(reserved)
    ys, xs = np.nonzero(grid == int(Cell.FLOOR))
    free = [(int(x), int(y)) for x, y in zip(xs, ys, strict=True) if (int(x), int(y)) not in keep]
    free.sort()  # stable order so a seeded sample over these cells is reproducible
    return free


def weighted_choice(rgen, table: List[Tuple[Cell, float]]) -> Cell:
    """Pick one :class:`Cell` from a list of ``(cell, weight)`` pairs (the weights need not sum to 1)."""
    total = sum(w for _c, w in table)
    r = rgen.random() * total
    acc = 0.0
    for cell, w in table:
        acc += w
        if r < acc:
            return cell
    return table[0][0]


def scatter_furniture(
    grid: np.ndarray,
    rgen,
    cells: List[Tuple[int, int]],
    density: float,
    chooser: Callable[[object, int, int], Optional[Cell]],
) -> None:
    """Furnish a seeded ``density`` fraction of ``cells`` via ``chooser(rgen, x, y) -> Optional[Cell]``.

    The shared scatter loop for every builder: it fixes *how many* cells are dressed and in what
    (reproducible) order, leaving each builder to supply only the per-cell choice. A chooser returning
    None leaves that cell untouched (e.g. a corridor that should only sometimes collect rubble).
    """
    n = int(len(cells) * density)
    if n <= 0:
        return
    for x, y in rgen.sample(cells, min(n, len(cells))):
        cell = chooser(rgen, x, y)
        if cell is not None:
            grid[y, x] = int(cell)


# --------------------------------------------------------------------------- open-plan settlement helpers
# Settlements (city/town/village) are NOT one solid mass: several small buildings sit in the footprint
# with open streets between them (terrain shows through the gaps). These helpers wall and door an
# individual building and lay PATH streets without the blanket fill/wall the dungeon recipe applies.


def wall_ring(grid: np.ndarray, rect: Rect) -> None:
    """Set the 1-cell border around ``rect`` to WALL, but only where it is currently VOID.

    Walls one building at a time (unlike :func:`add_walls`, which would also wall the open streets).
    Overwriting only VOID leaves neighbouring buildings and any PATH streets intact.
    """
    rx, ry, rw, rh = rect
    h, w = grid.shape
    for x in range(rx - 1, rx + rw + 1):
        for y in (ry - 1, ry + rh):
            if 0 <= x < w and 0 <= y < h and grid[y, x] == int(Cell.VOID):
                grid[y, x] = int(Cell.WALL)
    for y in range(ry - 1, ry + rh + 1):
        for x in (rx - 1, rx + rw):
            if 0 <= x < w and 0 <= y < h and grid[y, x] == int(Cell.VOID):
                grid[y, x] = int(Cell.WALL)


def building_door(grid: np.ndarray, rect: Rect, toward: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Punch a DOOR in ``rect``'s wall on the side facing ``toward``; return the exterior front cell.

    Scans the building's wall ring for the cell nearest ``toward`` that has the building's FLOOR on its
    inner side and an open (VOID/PATH) cell on its outer side, turns it into a DOOR, and returns the
    outer cell - the street stub the door opens onto - so the caller can wire it into the street
    network. Returns None for a degenerate building with no such wall.
    """
    h, w = grid.shape
    rx, ry, rw, rh = rect
    tx, ty = toward
    wall, floor, openable = int(Cell.WALL), int(Cell.FLOOR), (int(Cell.VOID), int(Cell.PATH))
    best: Optional[Tuple[int, Tuple[int, int], Tuple[int, int]]] = None
    for y in range(max(0, ry - 1), min(h, ry + rh + 1)):
        for x in range(max(0, rx - 1), min(w, rx + rw + 1)):
            if grid[y, x] != wall:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ix, iy, ox, oy = x - dx, y - dy, x + dx, y + dy  # inner / outer sides of the wall
                if not (0 <= ix < w and 0 <= iy < h and 0 <= ox < w and 0 <= oy < h):
                    continue
                if grid[iy, ix] == floor and grid[oy, ox] in openable:
                    cand = ((x - tx) ** 2 + (y - ty) ** 2, (x, y), (ox, oy))
                    if best is None or cand < best:
                        best = cand
                    break
    if best is None:
        return None
    _d, (dxc, dyc), front = best
    grid[dyc, dxc] = int(Cell.DOOR)
    return front


def carve_path_guarded(grid: np.ndarray, a: Tuple[int, int], b: Tuple[int, int]) -> None:
    """Carve an L-shaped PATH street from ``a`` to ``b``, but only over VOID (never through structure).

    Streets thread the open ground between buildings; guarding on VOID means a street stops at a
    building wall rather than tunnelling through it, so buildings stay intact (the street simply skips
    the cells it cannot claim).
    """
    (ax, ay), (bx, by) = a, b
    void, p = int(Cell.VOID), int(Cell.PATH)
    for x in range(min(ax, bx), max(ax, bx) + 1):
        if grid[ay, x] == void:
            grid[ay, x] = p
    for y in range(min(ay, by), max(ay, by) + 1):
        if grid[y, bx] == void:
            grid[y, bx] = p


# --------------------------------------------------------------------------- public entry + cache
def build_interior(poi: POI, floor: int, config: Config, world: Optional["World"] = None) -> Optional[np.ndarray]:
    """Return the (immutable, cached) base interior grid for ``poi`` at ``floor`` - or None.

    None means this POI kind has no interior builder yet (render falls back to its marker) or the
    footprint is degenerate. The returned array is read-only; layer runtime edits via the Overlay.

    When ``world`` is supplied (the render paths always do) the structure is built **terrain-aware**:
    any footprint cell over water - plus a coast margin beside it - is excluded so the structure forms
    *around* the coast (``boat`` is exempt: it floats on water by design). Inland POIs are unaffected and
    share their cache entry with the no-``world`` build; tests may omit ``world`` for a pure-land layout.
    """
    if not INTERIOR_BUILDERS.has(poi.kind):
        return None
    gw, gh = footprint_cells(poi, config)
    if gw < 3 or gh < 3:
        return None
    land_mask_bytes = b""
    if world is not None and poi.kind != "boat":
        cpt = max(1, int(config.get("interiors.cells_per_tile")))
        margin = max(0, int(config.get("interiors.coast_margin")))
        land_mask_bytes = buildable_mask_bytes(poi, world, gw, gh, cpt, margin)
    # Door faces the connecting road: derive the side from where the entrance sits relative to the anchor
    # (the roads + interiors stages place it on the road-facing perimeter). Unset/at-anchor -> no bias.
    ex, ey = poi.entrance
    if (ex, ey) in ((0, 0), (poi.x, poi.y)):
        entrance_side = (0, 0)
    else:
        entrance_side = ((ex > poi.x) - (ex < poi.x), (ey > poi.y) - (ey < poi.y))
    ctx = InteriorCtx(
        kind=poi.kind,
        interior_seed=int(poi.interior_seed),
        floor=int(floor),
        lowest_floor=int(poi.lowest_floor),
        floor_count=int(poi.floor_count),
        grid_w=int(gw),
        grid_h=int(gh),
        room_min=int(config.get("interiors.room_min")),
        room_max=int(config.get("interiors.room_max")),
        clutter_density=float(config.get("interiors.clutter_density")),
        partition=str(config.get("interiors.partition")),
        shape=str(config.get("interiors.shape")),
        ruin_erosion=float(config.get("interiors.ruin_erosion")),
        land_mask_bytes=land_mask_bytes,
        entrance_side=entrance_side,
    )
    return _build_base(ctx)


@functools.lru_cache(maxsize=512)
def _build_base(ctx: InteriorCtx) -> np.ndarray:
    """Memoised builder dispatch, keyed on the frozen (hashable) ``ctx`` - its fields ARE the cache key."""
    grid = INTERIOR_BUILDERS.get(ctx.kind)(ctx)
    grid.setflags(write=False)  # the cached base must never be mutated; edits go through the Overlay
    return grid


def clear_cache() -> None:
    """Drop the interior cache (used by tests; a fresh world keeps the same deterministic results)."""
    _build_base.cache_clear()
