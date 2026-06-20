"""Detail-view frame construction (pure - no curses).

A biome tile is magnified into a block of detail cells. The detail is the biome "floor" plus
deterministic, biome-appropriate **clutter** (trees in forest, scree on mountains, ripples on water,
...). POI interiors and roads layer on top in later phases.

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
from ..util import noise, rng
from ..world.tile import WATER_BIOMES, Biome
from ..world.world import World
from .state import ViewState

# Per-biome clutter: (list of glyphs, base probability a given detail cell becomes clutter).
_CLUTTER = {
    int(Biome.FOREST): (["t", "T", "t"], 0.22),
    int(Biome.JUNGLE): (["T", "t", "%"], 0.30),
    int(Biome.TAIGA): (["t", "^"], 0.18),
    int(Biome.SWAMP): ([";", '"', "w"], 0.25),
    int(Biome.MOUNTAIN): (["."], 0.22),  # rocky '^' floor with scattered '.' scree
    int(Biome.SNOW): (["."], 0.14),  # snowy highland: '^' floor with '.' clutter
    int(Biome.GRASSLAND): (['"', ","], 0.12),
    int(Biome.SAVANNA): (['"', ".", "t"], 0.10),
    int(Biome.SHRUBLAND): ([";", '"'], 0.14),
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
    int(Biome.GRASSLAND),
    int(Biome.SAVANNA),
    int(Biome.SHRUBLAND),
}
_ROCKY = {int(Biome.MOUNTAIN), int(Biome.SNOW)}

# Highland biomes share a '^' floor; everything else is '.'. Water is rendered as '~'.
_HIGHLAND = {int(Biome.MOUNTAIN), int(Biome.SNOW)}
_BASE_GLYPH = {
    int(Biome.OCEAN): "~",
    int(Biome.LAKE): "~",
    int(Biome.RIVER): "~",
    int(Biome.BEACH): ".",
    int(Biome.GRASSLAND): ".",
    int(Biome.SHRUBLAND): ".",
    int(Biome.SAVANNA): ".",
    int(Biome.FOREST): ".",
    int(Biome.JUNGLE): ".",
    int(Biome.TAIGA): ".",
    int(Biome.DESERT): ".",
    int(Biome.TUNDRA): ".",
    int(Biome.SWAMP): ".",
    int(Biome.MOUNTAIN): "^",
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
_OCEAN = int(Biome.OCEAN)


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
    iwg = np.isin(world.biome, _WATER_ARR).astype(np.float64)
    bgrid = world.biome

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


def build_detail_frame(
    world: World,
    config: Config,
    vs: ViewState,
    area_w: int,
    area_h: int,
    cell_w: int,
    cell_h: int,
) -> ZoomFrame:
    """Build a magnified :class:`ZoomFrame` where each biome tile is a ``cell_h`` x ``cell_w`` block.

    The camera (``vs.cam_x/cam_y``) is the top-left biome tile, assumed already edge-panned for the
    tile-count viewport this cell size implies. The per-cell biome (used for colour, base glyph and
    clutter) comes from the blended world-space lookup, so boundaries are soft and scale-consistent.
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
    warped_biome = world.biome[by, bx]

    is_water, water_biome = _water_blend(world, wfx, wfy, float(config.get("render.water_blend_threshold")))
    # For non-water cells, fall back to an unwarped land biome if the warp happened to land in water.
    land_fallback = world.biome[
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
    elev = world.elevation[by, bx]
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

    # Overlay roads and POI markers on each tile's block centre (markers > roads; POI > biome floor).
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
            glyph = None
            pidx = int(world.poi_index[ty, tx])
            if 0 <= pidx < len(world.pois):
                glyph = markers.get(world.pois[pidx].kind, "?")
            elif world.road[ty, tx]:
                glyph = markers.get("road", "+")
            if glyph is not None:
                cj = tcol * cell_w + cell_w // 2
                cells[ci][cj] = (glyph, cells[ci][cj][1])  # keep the cell's biome colour

    fcol = vs.cx - cam_x
    frow = vs.cy - cam_y
    cursor_rect = None
    if 0 <= fcol < tiles_w and 0 <= frow < tiles_h:
        cursor_rect = (fcol * cell_w, frow * cell_h, fcol * cell_w + cell_w, frow * cell_h + cell_h)

    return ZoomFrame(cols, rows, cells, cursor_rect, tiles_w, tiles_h)
