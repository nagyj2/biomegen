"""Detail-view frame construction (pure - no curses).

A biome tile is magnified into a block of detail cells. The detail is the biome "floor" plus
deterministic, biome-appropriate **clutter** (trees in forest, scree on mountains, ripples on water,
...). Roads, bridges, POI markers and POI interiors layer on top.

**Roads & bridges.** Roads are not single-tile markers at this scale: a road is a thin meandering
**bed** drawn from the distance of each detail cell to the line joining adjacent road-tile centres
(``_draw_roads``), so it reads like the rivers do - the same shape at zoom and local, a fraction of a
tile wide. Bridges (``_draw_bridges``) are straight decks flanked by walls, drawn from each bridge
POI's stored span endpoints at whatever real angle the crossing has, and over the water they span.

**Biome blending.** To stop the square biome grid from being obvious at the detail scales, each detail
cell does not simply inherit its tile's biome; instead it looks up the biome at its **world position
perturbed by a coherent noise warp**. Because the warp is a pure function of continuous world
coordinates (seeded from ``world.seed``), the boundary between two biomes becomes an irregular,
interleaved transition - and, crucially, the *zoom* and *local* views are just coarse vs fine
samplings of the **same** blend field, so they look like zoomed images of one another. Clutter is
likewise driven by world-space noise fields, so it too is consistent across the two scales.

Setting ``render.blend_strength`` to 0 restores the crisp, per-tile grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from ..config.model import Config
from ..interiors import INTERIOR_BUILDERS, ZOOM_VISIBLE, build_interior, footprint_origin, sample_rect
from ..util import noise, rng
from ..world.overlay import Overlay
from ..world.tile import (
    COLOR_BRIDGE_DECK,
    COLOR_BRIDGE_WALL,
    COLOR_ROAD,
    INTERIOR_COLOR_BASE,
    WATER_BIOMES,
    Biome,
    Cell,
    WaterType,
)
from ..world.world import World
from .glyphs import interior_glyph_table
from .state import SCALE_LOCAL, SCALE_ZOOM, ViewState
from .surface import display_biome

# Per-biome clutter: (list of glyphs, base probability a given detail cell becomes clutter).
_CLUTTER = {
    int(Biome.FOREST): (["t", "T", "t"], 0.22),
    int(Biome.JUNGLE): (["T", "t", "%"], 0.30),
    int(Biome.TAIGA): (["t", "^"], 0.18),
    int(Biome.SWAMP): ([";", '"', "w"], 0.25),
    int(Biome.SNOW): (["."], 0.14),  # snowy highland: '^' floor with '.' clutter
    int(Biome.GRASS): (['"', ","], 0.12),
    int(Biome.SAVANNA): (['"', ".", "t"], 0.10),
    int(Biome.DESERT): ([".", "o"], 0.06),
    int(Biome.TUNDRA): ([",", "."], 0.08),
    int(Biome.BEACH): ([",", "."], 0.06),
}

# Clutter density tracks moisture (more vegetation where wetter) vs elevation (more scree higher up),
# so the scatter reflects the tile's real fields rather than being uniform noise.
_VEGETATION = {
    int(Biome.FOREST),
    int(Biome.JUNGLE),
    int(Biome.TAIGA),
    int(Biome.SWAMP),
    int(Biome.GRASS),
    int(Biome.SAVANNA),
}
_ROCKY = {int(Biome.SNOW)}  # mountains are relief now; phase 4 shades them

# Highland biomes share a '^' floor; everything else is '.'. Water is rendered as '~'.
_HIGHLAND = {int(Biome.SNOW)}
_BASE_GLYPH = {
    int(Biome.DEEP): "~",
    int(Biome.SHALLOW): "~",
    int(Biome.SEAICE): "~",
    int(Biome.LAKE): "~",
    int(Biome.BEACH): ".",
    int(Biome.GRASS): ".",
    int(Biome.SAVANNA): ".",
    int(Biome.FOREST): ".",
    int(Biome.JUNGLE): ".",
    int(Biome.TAIGA): ".",
    int(Biome.DESERT): ".",
    int(Biome.TUNDRA): ".",
    int(Biome.SWAMP): ".",
    int(Biome.SNOW): "^",
}

# Vectorised lookup tables (indexed by biome int) built once at import.
_MAX_BIOME = max(int(b) for b in Biome)
_BASE_DENSITY_LUT = np.zeros(_MAX_BIOME + 1, dtype=np.float64)
for _b, (_glyphs, _density) in _CLUTTER.items():
    _BASE_DENSITY_LUT[_b] = _density
_VEG_ARR = np.array(sorted(_VEGETATION), dtype=np.int64)
_ROCK_ARR = np.array(sorted(_ROCKY), dtype=np.int64)
_WATER_ARR = np.array(sorted(WATER_BIOMES), dtype=np.int64)
_OCEAN = int(Biome.DEEP)


@dataclass
class ZoomFrame:
    """A magnified detail grid plus the cursor (focus tile) rectangle in detail coordinates."""

    cols: int
    rows: int
    cells: List[List[Tuple[str, int]]]  # [row][col] -> (glyph, biome_int_for_colour)
    cursor_rect: Optional[Tuple[int, int, int, int]]  # (x0, y0, x1, y1) detail-cell box, or None
    tiles_w: int
    tiles_h: int


def detail_cell_size(scale: str, config: Config, area_w: int, area_h: int) -> Tuple[int, int]:
    """Return the (cell_w, cell_h) - detail cells per biome tile - for a detail ``scale``.

    Both detail scales are **aspect-corrected**: the cell *height* sets the magnification and the
    *width* is widened by ``cell_aspect`` so a square world tile reads roughly square on the terminal
    (whose character cells are taller than they are wide).

    * ``zoom``  : cell height = ``zoom_scale`` (the mid view).
    * ``local`` : cell height sized so ~``local_rows`` biome tiles fit vertically (the close view).
    """
    aspect = float(config.get("render.cell_aspect"))
    if scale == "local":
        local_rows = max(1, int(config.get("render.local_rows")))
        ch = max(2, area_h // local_rows)
    else:  # "zoom"
        ch = max(1, int(config.get("render.zoom_scale")))
    cw = max(ch, int(round(ch * aspect)))
    return cw, ch


def _scatter01(
    seed_int: int, salt: int, tx: np.ndarray, ty: np.ndarray, scx: np.ndarray, scy: np.ndarray
) -> np.ndarray:
    """Vectorised **uniform** pseudo-random value in [0, 1) per (tile, sub-cell).

    Used for clutter placement and glyph choice. Keyed on the *absolute* world tile plus the
    sub-cell index within that tile - NOT on the smooth blend noise - so:
      * the distribution is uniform (``value < density`` yields exactly ``density`` coverage, with no
        large empty swaths the coherent noise produced), and
      * a tile's clutter is stable as the camera pans (it depends on absolute position, not screen).
    Uses a SplitMix64-style integer mix; uint64 wraps by design.
    """
    with np.errstate(over="ignore"):
        h = tx.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15)
        h ^= ty.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F)
        h ^= scx.astype(np.uint64) * np.uint64(0x165667B19E3779F9)
        h ^= scy.astype(np.uint64) * np.uint64(0x27D4EB2F165667C5)
        h ^= np.uint64((int(seed_int) ^ int(salt)) & 0xFFFFFFFFFFFFFFFF)
        h ^= h >> np.uint64(30)
        h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27)
        h *= np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) * (1.0 / float(1 << 53))


def _warp_coords(world: World, config: Config, fx: np.ndarray, fy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return world coordinates (fx, fy) offset by a coherent noise warp (or unchanged if off).

    The warp is a pure function of world position + seed, so any view that samples a given world
    position gets the same warped coordinate - the basis for zoom/local consistency.
    """
    strength = float(config.get("render.blend_strength"))
    if strength <= 0:
        return fx, fy
    scale = max(1e-6, float(config.get("render.blend_scale")))
    backend = config.get("terrain.noise_backend")
    nx = noise.get_sampler(backend, rng.derive_int(world.seed, "biomeblend.x"))(fx / scale, fy / scale)
    ny = noise.get_sampler(backend, rng.derive_int(world.seed, "biomeblend.y"))(fx / scale, fy / scale)
    return fx + strength * nx, fy + strength * ny


def _blended_lookup(world: World, config: Config, fx: np.ndarray, fy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(bx, by)`` tile indices to read the biome from, after domain-warping (fx, fy)."""
    w, h = world.width, world.height
    wfx, wfy = _warp_coords(world, config, fx, fy)
    bx = np.clip(np.floor(wfx).astype(np.int64), 0, w - 1)
    by = np.clip(np.floor(wfy).astype(np.int64), 0, h - 1)
    return bx, by


def _water_blend(world: World, wfx: np.ndarray, wfy: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(is_water, water_biome)`` per cell from a bilinear water-coverage field.

    Tile *centres* sit at integer + 0.5; bilinearly interpolating the 0/1 "is this tile water?" grid
    at (wfx, wfy) gives a smooth coverage in [0, 1]. Thresholding below 0.5 fills the diagonal gap
    between two corner-touching water tiles (coverage there is ~0.5), so rivers/lakes connect instead
    of forming a checkerboard. ``water_biome`` is the biome of the highest-weighted water corner, so a
    bridged cell takes the right water colour (river vs lake vs ocean).
    """
    h, w = world.height, world.width
    bgrid = display_biome(world)
    iwg = np.isin(bgrid, _WATER_ARR).astype(np.float64)

    gx = wfx - 0.5
    gy = wfy - 0.5
    x0 = np.floor(gx).astype(np.int64)
    y0 = np.floor(gy).astype(np.int64)
    tx = gx - x0
    ty = gy - y0
    x0c, x1c = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)

    # Bilinear corner weights.
    a00 = (1 - tx) * (1 - ty)
    a10 = tx * (1 - ty)
    a01 = (1 - tx) * ty
    a11 = tx * ty
    cov = iwg[y0c, x0c] * a00 + iwg[y0c, x1c] * a10 + iwg[y1c, x0c] * a01 + iwg[y1c, x1c] * a11

    # Dominant water corner (max weight x is-water) -> its biome.
    ww = np.stack([a00 * iwg[y0c, x0c], a10 * iwg[y0c, x1c], a01 * iwg[y1c, x0c], a11 * iwg[y1c, x1c]])
    bb = np.stack([bgrid[y0c, x0c], bgrid[y0c, x1c], bgrid[y1c, x0c], bgrid[y1c, x1c]])
    idx = np.argmax(ww, axis=0)
    water_biome = np.take_along_axis(bb, idx[None], axis=0)[0]
    return cov >= threshold, water_biome


def _road_warp_field(world: World, config: Config, fx: np.ndarray, fy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return road-warped ``(wfx, wfy)`` for the detail grid (or ``fx, fy`` if road warp is off).

    Reuses the biome-blend warp samplers at the ``render.road_warp`` magnitude, so the road bed wobbles
    organically and - being a pure function of world position + seed - identically across the zoom and
    local scales (the same consistency rivers have).
    """
    warp = float(config.get("render.road_warp"))
    if warp <= 0:
        return fx, fy
    scale = max(1e-6, float(config.get("render.blend_scale")))
    backend = config.get("terrain.noise_backend")
    nx = noise.get_sampler(backend, rng.derive_int(world.seed, "biomeblend.x"))(fx / scale, fy / scale)
    ny = noise.get_sampler(backend, rng.derive_int(world.seed, "biomeblend.y"))(fx / scale, fy / scale)
    return fx + warp * nx, fy + warp * ny


def _draw_roads(
    world: World,
    config: Config,
    vs: ViewState,
    cells: List[List[Tuple[str, int]]],
    water: np.ndarray,
    inworld: np.ndarray,
    cl: np.ndarray,
    gl: np.ndarray,
    rows: int,
    cols: int,
    cam_x: int,
    cam_y: int,
    tiles_w: int,
    tiles_h: int,
    cell_w: int,
    cell_h: int,
    wfx: np.ndarray,
    wfy: np.ndarray,
) -> None:
    """Draw the road network as a thin meandering bed onto ``cells`` in place.

    A detail cell is road when its (road-warped) world position lies within ``road_half_width`` tiles of
    the straight line joining two 8-adjacent land-road tile centres. That distance test is a pure function
    of world position, so zoom and local are the same shape at different scales (exactly like rivers). The
    bed is the ``road_glyph`` in the road colour, with small clutter scattered along it (extra fine detail
    at the local scale). Water cells are never drawn over - bridges (drawn separately) carry the crossing.
    """
    half = float(config.get("render.road_half_width"))
    if half <= 0:
        return
    none = int(WaterType.NONE)
    land_road = (world.road > 0) & (world.water_type == none)
    h, w = world.height, world.width
    py0, py1 = max(0, cam_y - 1), min(h, cam_y + tiles_h + 1)
    px0, px1 = max(0, cam_x - 1), min(w, cam_x + tiles_w + 1)
    if py1 <= py0 or px1 <= px0:
        return
    ys, xs = np.nonzero(land_road[py0:py1, px0:px1])
    if len(xs) == 0:
        return

    is_road = np.zeros((rows, cols), dtype=bool)

    def _draw_seg(ax: float, ay: float, bx: float, by: float) -> None:
        c0 = int(np.floor((min(ax, bx) - half - cam_x) * cell_w - 0.5))
        c1 = int(np.ceil((max(ax, bx) + half - cam_x) * cell_w - 0.5))
        r0 = int(np.floor((min(ay, by) - half - cam_y) * cell_h - 0.5))
        r1 = int(np.ceil((max(ay, by) + half - cam_y) * cell_h - 0.5))
        c0, c1 = max(0, c0), min(cols - 1, c1)
        r0, r1 = max(0, r0), min(rows - 1, r1)
        if c1 < c0 or r1 < r0:
            return
        x = wfx[r0 : r1 + 1, c0 : c1 + 1]
        y = wfy[r0 : r1 + 1, c0 : c1 + 1]
        dx, dy = bx - ax, by - ay
        seg_len2 = dx * dx + dy * dy
        if seg_len2 <= 1e-9:
            dist = np.hypot(x - ax, y - ay)
        else:
            t = np.clip(((x - ax) * dx + (y - ay) * dy) / seg_len2, 0.0, 1.0)
            dist = np.hypot(x - (ax + t * dx), y - (ay + t * dy))
        is_road[r0 : r1 + 1, c0 : c1 + 1] |= dist <= half

    neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    for yy, xx in zip(ys.tolist(), xs.tolist(), strict=True):
        tx, ty = px0 + xx, py0 + yy
        ax, ay = tx + 0.5, ty + 0.5
        _draw_seg(ax, ay, ax, ay)  # self-disc covers endpoints / isolated tiles
        for ddx, ddy in neighbours:
            nx, ny = tx + ddx, ty + ddy
            if 0 <= nx < w and 0 <= ny < h and land_road[ny, nx]:
                _draw_seg(ax, ay, nx + 0.5, ny + 0.5)

    # Paint the bed onto the cells, with clutter scattered along it (uniform per-cell hash already in cl/gl).
    road_glyph = str(config.get("render.road_glyph"))
    clutter = config.get("render.road_clutter") or {}
    cl_glyphs = list(clutter.get("glyphs") or [])
    cl_density = float(clutter.get("density", 0.0))
    local = vs.scale == SCALE_LOCAL
    loc = config.get("render.road_clutter_local") or {}
    loc_glyphs = list(loc.get("glyphs") or [])
    loc_density = float(loc.get("density", 0.0))

    ir_l = is_road.tolist()
    water_l = water.tolist()
    iw_l = inworld.tolist()
    cl_l = cl.tolist()
    gl_l = gl.tolist()
    for r in range(rows):
        ir = ir_l[r]
        wr, iw, clr, glr = water_l[r], iw_l[r], cl_l[r], gl_l[r]
        for c in range(cols):
            if not ir[c] or wr[c] or not iw[c]:
                continue
            glyph = road_glyph
            if cl_glyphs and clr[c] < cl_density:
                glyph = cl_glyphs[min(int(glr[c] * len(cl_glyphs)), len(cl_glyphs) - 1)]
            elif local and loc_glyphs and clr[c] < cl_density + loc_density:
                glyph = loc_glyphs[min(int(glr[c] * len(loc_glyphs)), len(loc_glyphs) - 1)]
            cells[r][c] = (glyph, COLOR_ROAD)


def _draw_bridges(
    world: World,
    config: Config,
    cells: List[List[Tuple[str, int]]],
    inworld: np.ndarray,
    rows: int,
    cols: int,
    cam_x: int,
    cam_y: int,
    cell_w: int,
    cell_h: int,
    fx: np.ndarray,
    fy: np.ndarray,
) -> None:
    """Draw each ``bridge`` POI as a straight deck flanked by walls onto ``cells`` in place.

    The deck is the straight span between the two road pieces the bridge joins (``extra['p0']`` ->
    ``extra['p1']``), at whatever real angle that line has. Cells within ``road_half_width`` of the span
    (measured perpendicular, clamped to the span's length so the ends stay flat) are the brown deck; a
    band just beyond it on either long side is the wall/railing. Unlike roads this is drawn over water -
    a bridge crosses it - and uses the un-warped grid so the span reads dead straight.
    """
    bg = config.get("render.bridge_glyphs") or {}
    deck_glyph = str(bg.get("deck", ":"))
    wall_glyph = str(bg.get("wall", "#"))
    deck_half = max(float(config.get("render.road_half_width")), 0.18)
    wall_half = deck_half  # railing band width, beyond the deck on each side
    overhang = float(config.get("render.bridge_overhang"))  # extend the deck past each end onto the road

    for poi in world.pois:
        if poi.kind != "bridge":
            continue
        p0 = poi.extra.get("p0") or [poi.x, poi.y]
        p1 = poi.extra.get("p1") or [poi.x, poi.y]
        ax, ay = p0[0] + 0.5, p0[1] + 0.5
        bx, by = p1[0] + 0.5, p1[1] + 0.5
        reach = deck_half + wall_half + overhang
        c0 = int(np.floor((min(ax, bx) - reach - cam_x) * cell_w - 0.5))
        c1 = int(np.ceil((max(ax, bx) + reach - cam_x) * cell_w - 0.5))
        r0 = int(np.floor((min(ay, by) - reach - cam_y) * cell_h - 0.5))
        r1 = int(np.ceil((max(ay, by) + reach - cam_y) * cell_h - 0.5))
        c0, c1 = max(0, c0), min(cols - 1, c1)
        r0, r1 = max(0, r0), min(rows - 1, r1)
        if c1 < c0 or r1 < r0:
            continue
        x = fx[r0 : r1 + 1, c0 : c1 + 1]
        y = fy[r0 : r1 + 1, c0 : c1 + 1]
        dx, dy = bx - ax, by - ay
        span = float(np.hypot(dx, dy))
        if span <= 1e-6:
            perp = np.hypot(x - ax, y - ay)
            within = np.ones_like(x, dtype=bool)
        else:
            ux, uy = dx / span, dy / span
            rx, ry = x - ax, y - ay
            along = rx * ux + ry * uy
            perp = np.abs(rx * (-uy) + ry * ux)
            # Extend the span a little past both road pieces so the deck overlaps the road bed (no gap).
            within = (along >= -overhang) & (along <= span + overhang)
        deck_mask = within & (perp <= deck_half)
        wall_mask = within & (perp > deck_half) & (perp <= deck_half + wall_half)
        iw = inworld[r0 : r1 + 1, c0 : c1 + 1]
        wall_m = (wall_mask & iw).tolist()
        deck_m = (deck_mask & iw).tolist()
        for dr in range(r1 - r0 + 1):
            wm, dm = wall_m[dr], deck_m[dr]
            for dc in range(c1 - c0 + 1):
                if wm[dc]:
                    cells[r0 + dr][c0 + dc] = (wall_glyph, COLOR_BRIDGE_WALL)
            for dc in range(c1 - c0 + 1):
                if dm[dc]:
                    cells[r0 + dr][c0 + dc] = (deck_glyph, COLOR_BRIDGE_DECK)


def _stamp_interiors(
    world: World,
    config: Config,
    vs: ViewState,
    cells: List[List[Tuple[str, int]]],
    rows: int,
    cols: int,
    cam_x: int,
    cam_y: int,
    tiles_w: int,
    tiles_h: int,
    cell_w: int,
    cell_h: int,
    overlay: Optional[Overlay],
) -> None:
    """Stamp each visible POI's interior onto ``cells`` across its footprint, in place.

    The interior is a single canonical-resolution artifact (built lazily, LRU-cached); here it is
    **nearest-neighbour sampled** into the footprint's detail-cell block, so the ``zoom`` and
    ``local`` scales are coarse vs fine views of the same grid. At ``zoom`` the building shell is drawn
    - walls *and* floor (see :data:`~biomegen.interiors.ZOOM_VISIBLE`) so it reads as filled-in -
    but furniture is suppressed; at ``local`` every non-void cell is drawn (the full furnished
    interior). ``VOID`` cells are skipped so the surrounding terrain shows through the gaps.

    As a hard backstop, no interior cell is ever drawn over a water tile (except for a ``boat``, which
    floats on water by design): the terrain-aware builder already forms each structure around the coast,
    but this guarantees that even a stray corridor clipping the shore renders as water, not masonry.
    """
    shell_only = vs.scale == SCALE_ZOOM
    cell_glyph = interior_glyph_table(config)  # Cell int -> interior glyph (data-driven)
    void = int(Cell.VOID)
    dry = int(WaterType.NONE)

    for poi in world.pois:
        if not INTERIOR_BUILDERS.has(poi.kind):
            continue
        fw, fh = poi.footprint
        if fw <= 0 or fh <= 0:
            continue
        tx0, ty0 = footprint_origin(poi)
        # Skip if the footprint lies entirely outside the visible tile window.
        if tx0 + fw <= cam_x or tx0 >= cam_x + tiles_w or ty0 + fh <= cam_y or ty0 >= cam_y + tiles_h:
            continue
        top = poi.lowest_floor + poi.floor_count - 1
        floor = max(poi.lowest_floor, min(int(vs.floor), top))
        base = build_interior(poi, floor, config, world)
        if base is None:
            continue
        grid = overlay.apply_interior(base, poi.interior_seed, floor) if overlay is not None else base
        guard_water = poi.kind != "boat"  # boats render over water; every other structure forms around it

        # Footprint spans fh*cell_h x fw*cell_w detail cells at this scale; sample the interior into it.
        base_row = (ty0 - cam_y) * cell_h
        base_col = (tx0 - cam_x) * cell_w
        for r, c, cellv in sample_rect(grid, base_row, base_col, fh * cell_h, fw * cell_w, rows, cols):
            if cellv == void:
                continue  # VOID is transparent: terrain shows around the dungeon's organic outline
            is_bridge_cell = cellv in (int(Cell.BRIDGE), int(Cell.BRIDGE_WALL))
            if guard_water and not is_bridge_cell:
                tx, ty = cam_x + c // cell_w, cam_y + r // cell_h
                if 0 <= ty < world.height and 0 <= tx < world.width and world.water_type[ty, tx] != dry:
                    continue  # never lay structure over water: the real water/coast shows through
            if shell_only and cellv not in ZOOM_VISIBLE:
                # Furniture is suppressed at zoom, but it stands ON a floor - draw that floor, not the
                # terrain underneath, so rooms read as solid floorplan (no biome clutter leaks).
                cellv = int(Cell.FLOOR)
            if cellv == int(Cell.BRIDGE):
                color = COLOR_BRIDGE_DECK
            elif cellv == int(Cell.BRIDGE_WALL):
                color = COLOR_BRIDGE_WALL
            else:
                color = INTERIOR_COLOR_BASE + cellv
            cells[r][c] = (cell_glyph.get(cellv, "?"), color)


def build_detail_frame(
    world: World,
    config: Config,
    vs: ViewState,
    area_w: int,
    area_h: int,
    cell_w: int,
    cell_h: int,
    overlay: Optional[Overlay] = None,
) -> ZoomFrame:
    """Build a magnified :class:`ZoomFrame` where each biome tile is a ``cell_h`` x ``cell_w`` block.

    The camera (``vs.cam_x/cam_y``) is the top-left biome tile, assumed already edge-panned for the
    tile-count viewport this cell size implies. The per-cell biome (used for colour, base glyph and
    clutter) comes from the blended world-space lookup, so boundaries are soft and scale-consistent.

    POIs with a registered interior builder are stamped on top of the terrain across their footprint
    (see :func:`_stamp_interiors`): the ``zoom`` scale shows only the structural outline, the
    ``local`` scale the full furnished interior, for ``vs.floor``. ``overlay`` (if given) supplies
    runtime interior edits, composited over the deterministic base.
    """
    tiles_w = max(1, area_w // cell_w)
    tiles_h = max(1, area_h // cell_h)
    cols = tiles_w * cell_w
    rows = tiles_h * cell_h
    cam_x, cam_y = vs.cam_x, vs.cam_y

    # World fractional coordinate at the centre of each detail cell (per column / per row).
    col_i = np.arange(cols)
    row_i = np.arange(rows)
    col_tile = cam_x + col_i // cell_w
    row_tile = cam_y + row_i // cell_h
    fx_col = col_tile + ((col_i % cell_w) + 0.5) / cell_w  # (cols,)
    fy_row = row_tile + ((row_i % cell_h) + 0.5) / cell_h  # (rows,)
    FX = np.broadcast_to(fx_col, (rows, cols))
    FY = np.broadcast_to(fy_row[:, None], (rows, cols))
    inworld = ((row_tile >= 0) & (row_tile < world.height))[:, None] & ((col_tile >= 0) & (col_tile < world.width))[
        None, :
    ]

    # Blended biome per cell (drives colour, base glyph and clutter choice). Land uses the warped
    # nearest-tile lookup; water uses a bilinear coverage field so diagonal water connects.
    wfx, wfy = _warp_coords(world, config, FX, FY)
    bx = np.clip(np.floor(wfx).astype(np.int64), 0, world.width - 1)
    by = np.clip(np.floor(wfy).astype(np.int64), 0, world.height - 1)
    surface = display_biome(world)
    warped_biome = surface[by, bx]

    is_water, water_biome = _water_blend(world, wfx, wfy, float(config.get("render.water_blend_threshold")))
    # For non-water cells, fall back to an unwarped land biome if the warp happened to land in water.
    land_fallback = surface[
        np.clip(np.floor(FY).astype(np.int64), 0, world.height - 1),
        np.clip(np.floor(FX).astype(np.int64), 0, world.width - 1),
    ]
    land_biome = np.where(np.isin(warped_biome, _WATER_ARR), land_fallback, warped_biome)
    biome = np.where(is_water, water_biome, land_biome)

    # Clutter probability + glyph-selection: a uniform per-(tile, sub-cell) hash so coverage matches
    # the configured density everywhere (no empty swaths) and is stable as the camera pans.
    col_sub = col_i % cell_w
    row_sub = row_i % cell_h
    TX = np.broadcast_to(col_tile, (rows, cols))
    TY = np.broadcast_to(row_tile[:, None], (rows, cols))
    SCX = np.broadcast_to(col_sub, (rows, cols))
    SCY = np.broadcast_to(row_sub[:, None], (rows, cols))
    cl = _scatter01(world.seed, 0x01, TX, TY, SCX, SCY)
    gl = _scatter01(world.seed, 0x9E37, TX, TY, SCX, SCY)

    # Per-cell density = per-biome base density * (moisture for vegetation / elevation for rock).
    base_density = _BASE_DENSITY_LUT[biome]
    moist = world.moisture[by, bx]
    elev = np.clip(world.elevation_m[by, bx] / max(1.0, float(world.elevation_m.max())), 0.0, 1.0)  # relative height
    factor = np.ones((rows, cols))
    factor = np.where(np.isin(biome, _VEG_ARR), np.clip(0.4 + 1.4 * moist, 0.25, 1.8), factor)
    factor = np.where(np.isin(biome, _ROCK_ARR), np.clip(0.4 + 1.3 * elev, 0.25, 1.8), factor)
    density = base_density * factor
    water = np.isin(biome, _WATER_ARR)
    clutter = inworld & (~water) & (base_density > 0) & (cl < density)

    # Assemble (glyph, biome) per cell. Convert to Python lists first - far faster than numpy scalar
    # indexing inside the double loop.
    biome_l = biome.tolist()
    gl_l = gl.tolist()
    clutter_l = clutter.tolist()
    inworld_l = inworld.tolist()
    water_l = water.tolist()
    cells: List[List[Tuple[str, int]]] = []
    for r in range(rows):
        b_row, g_row, c_row, iw_row, w_row = biome_l[r], gl_l[r], clutter_l[r], inworld_l[r], water_l[r]
        out: List[Tuple[str, int]] = []
        for c in range(cols):
            if not iw_row[c]:
                out.append((" ", _OCEAN))
                continue
            b = b_row[c]
            if w_row[c]:
                out.append(("~", b))
            elif c_row[c]:
                glyphs = _CLUTTER[b][0]
                gi = int(g_row[c] * len(glyphs))
                out.append((glyphs[min(gi, len(glyphs) - 1)], b))
            else:
                out.append((_BASE_GLYPH.get(b, "?"), b))
        cells.append(out)

    # Roads render as a thin meandering bed (road-warped); bridges as straight decks over the water they
    # cross (un-warped). Both sit on top of terrain but below POI markers and interiors.
    rwfx, rwfy = _road_warp_field(world, config, FX, FY)
    _draw_roads(
        world,
        config,
        vs,
        cells,
        water,
        inworld,
        cl,
        gl,
        rows,
        cols,
        cam_x,
        cam_y,
        tiles_w,
        tiles_h,
        cell_w,
        cell_h,
        rwfx,
        rwfy,
    )
    _draw_bridges(world, config, cells, inworld, rows, cols, cam_x, cam_y, cell_w, cell_h, FX, FY)

    # Overlay POI markers on each tile's block centre (marker > road/bridge bed > biome floor).
    # Keyed on the UNWARPED tile so a marker sits exactly on its POI, not on a blended neighbour.
    markers = config.get("render.markers")
    for trow in range(tiles_h):
        ty = cam_y + trow
        if not (0 <= ty < world.height):
            continue
        ci = trow * cell_h + cell_h // 2
        for tcol in range(tiles_w):
            tx = cam_x + tcol
            if not (0 <= tx < world.width):
                continue
            pidx = int(world.poi_index[ty, tx])
            if 0 <= pidx < len(world.pois):
                glyph = markers.get(world.pois[pidx].kind, "?")
                cj = tcol * cell_w + cell_w // 2
                cells[ci][cj] = (glyph, cells[ci][cj][1])  # keep the cell's biome colour

    # POI interiors overlay the terrain (and any marker) across their footprint. Done last so a
    # structure's outline/interior wins over its single-cell marker at the detail scales.
    _stamp_interiors(world, config, vs, cells, rows, cols, cam_x, cam_y, tiles_w, tiles_h, cell_w, cell_h, overlay)

    fcol = vs.cx - cam_x
    frow = vs.cy - cam_y
    cursor_rect = None
    if 0 <= fcol < tiles_w and 0 <= frow < tiles_h:
        cursor_rect = (fcol * cell_w, frow * cell_h, fcol * cell_w + cell_w, frow * cell_h + cell_h)

    return ZoomFrame(cols, rows, cells, cursor_rect, tiles_w, tiles_h)
