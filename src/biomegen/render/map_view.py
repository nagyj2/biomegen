"""Biome-map frame construction (pure - no curses).

Two scalings share one ``Frame`` representation that the app then paints:

* **fit-to-screen**: each screen cell covers a rectangular *block* of world tiles; the block's most
  salient tile (by a fixed feature priority - POIs/roads/water/peaks beat plain land) is shown. This
  "priority mode" reduction keeps coastlines, rivers and landmarks legible at small scale, unlike a
  numeric average which would smear them.
* **1:1 panning**: one screen cell = one world tile, windowed by the camera.

Keeping this logic free of curses means it is unit-testable and reusable by the ASCII preview and the
SVG/PNG export.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from ..config.model import Config
from ..interiors import INTERIOR_BUILDERS, STRUCTURAL, build_interior, footprint_origin, sample_rect
from ..world.overlay import Overlay
from ..world.tile import INTERIOR_COLOR_BASE, Biome
from ..world.world import World
from .glyphs import interior_glyph_table
from .state import ViewState
from .surface import display_biome_at

Coord = Tuple[int, int]
# A stamped interior cell: (glyph, colour-id) where the colour-id is INTERIOR_COLOR_BASE + Cell int.
Override = Tuple[str, int]

# Feature priority for fit-to-screen reduction: a block shows its highest-priority tile. Landmarks
# and water beat plain land so small but important features (a lone lake, a river thread) survive.
_BIOME_PRIORITY = {
    int(Biome.DEEP): 5,
    int(Biome.SHALLOW): 6,
    int(Biome.SEAICE): 7,
    int(Biome.DESERT): 28,
    int(Biome.GRASS): 30,
    int(Biome.SAVANNA): 30,
    int(Biome.TUNDRA): 35,
    int(Biome.FOREST): 40,
    int(Biome.TAIGA): 40,
    int(Biome.JUNGLE): 42,
    int(Biome.BEACH): 48,
    int(Biome.SWAMP): 50,
    int(Biome.SNOW): 60,
    int(Biome.LAKE): 75,  # rivers draw as lake water (render.surface) and share this priority
}
_POI_PRIORITY = 100
_ROAD_PRIORITY = 90


@dataclass
class Frame:
    """A drawable grid of world coordinates plus the cursor's screen position."""

    cols: int
    rows: int
    tiles: List[List[Optional[Coord]]]  # [row][col] -> (world_x, world_y) or None (out of bounds)
    cursor: Optional[Coord]  # (screen_col, screen_row) or None if off-screen
    block_w: int = 1  # fit-mode block dimensions (1 in 1:1 mode)
    block_h: int = 1
    # Per-screen-cell interior stamp: a scaled image of a POI's interior outline drawn over the
    # terrain across its footprint (None where no structure covers that cell). Built only when a
    # ``config`` is supplied to :func:`build_biome_frame`; the app paints it instead of the biome tile.
    overrides: Optional[List[List[Optional[Override]]]] = None


def feature_priority(world: World, x: int, y: int) -> int:
    """Return how salient tile ``(x, y)`` is for down-sampling (higher wins within a block)."""
    if world.poi_index[y, x] >= 0:
        return _POI_PRIORITY
    if world.road[y, x]:
        return _ROAD_PRIORITY
    return _BIOME_PRIORITY.get(display_biome_at(world, x, y), 20)


def fit_blocks(world_w: int, world_h: int, area_w: int, area_h: int) -> Tuple[int, int, int, int]:
    """Return ``(block_w, block_h, cols, rows)`` for fitting a world into an ``area_w x area_h`` grid."""
    area_w = max(1, area_w)
    area_h = max(1, area_h)
    block_w = max(1, math.ceil(world_w / area_w))
    block_h = max(1, math.ceil(world_h / area_h))
    cols = math.ceil(world_w / block_w)
    rows = math.ceil(world_h / block_h)
    return block_w, block_h, cols, rows


def _representative_tile(world: World, x0: int, y0: int, x1: int, y1: int) -> Coord:
    """Return the highest-priority tile coordinate within the block [x0,x1) x [y0,y1)."""
    best: Coord = (x0, y0)
    best_p = -1
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = feature_priority(world, x, y)
            if p > best_p:
                best_p = p
                best = (x, y)
    return best


def _stamp_map_interiors(
    world: World,
    config: Config,
    overlay: Optional[Overlay],
    rows: int,
    cols: int,
    to_screen: Callable[[int, int], Coord],
) -> Optional[List[List[Optional[Override]]]]:
    """Build a per-screen-cell stamp of each POI interior's structural outline (or None if nothing fits).

    The interior is the same canonical artifact the detail views sample - here it is nearest-neighbour
    sampled down to however many *screen cells* the footprint occupies (often ~one cell per world tile
    on the overview), so the biome map shows a recognisable scaled image of the dungeon's wall plan
    rather than the terrain underneath. Only :data:`~biomegen.interiors.STRUCTURAL` cells (walls,
    doors, stairs) are stamped; everything else is left as None so terrain still shows through the gaps.
    The entry (top) floor is used - the overview is the surface-level view of the structure.
    """
    cell_glyph = interior_glyph_table(config)
    overrides: List[List[Optional[Override]]] = [[None] * cols for _ in range(rows)]
    stamped = False
    for poi in world.pois:
        if not INTERIOR_BUILDERS.has(poi.kind):
            continue
        fw, fh = poi.footprint
        if fw <= 0 or fh <= 0:
            continue
        floor = poi.lowest_floor + poi.floor_count - 1  # entry/top floor = the surface view
        base = build_interior(poi, floor, config, world)  # terrain-aware: outline forms around the coast
        if base is None:
            continue
        grid = overlay.apply_interior(base, poi.interior_seed, floor) if overlay is not None else base
        tx0, ty0 = footprint_origin(poi)
        # Screen-cell rectangle the footprint maps to (its two corners under the active scaling).
        sc0, sr0 = to_screen(tx0, ty0)
        sc1, sr1 = to_screen(tx0 + fw - 1, ty0 + fh - 1)
        span_cols, span_rows = sc1 - sc0 + 1, sr1 - sr0 + 1
        if span_cols <= 0 or span_rows <= 0:
            continue
        # The POI's map marker lives on its anchor's screen cell; never stamp the outline over it, so
        # the marker (drawn from poi_index by the app) always wins over a wall/door of the outline.
        acol, arow = to_screen(poi.x, poi.y)
        for sr, sc, cellv in sample_rect(grid, sr0, sc0, span_rows, span_cols, rows, cols):
            if (sc == acol and sr == arow) or cellv not in STRUCTURAL:
                continue  # marker cell stays clear (POI wins); only structural cells stamp
            overrides[sr][sc] = (cell_glyph.get(cellv, "?"), INTERIOR_COLOR_BASE + cellv)
            stamped = True
    return overrides if stamped else None


def build_biome_frame(
    world: World,
    vs: ViewState,
    area_w: int,
    area_h: int,
    config: Optional[Config] = None,
    overlay: Optional[Overlay] = None,
) -> Frame:
    """Build the biome-map :class:`Frame` for the current view mode and camera.

    When ``config`` is supplied, POIs with an interior builder are stamped onto the frame as a scaled
    outline of their interior (see :func:`_stamp_map_interiors`); without it the frame is terrain-only
    (used by the lightweight ASCII/test paths that don't render interiors).
    """
    if vs.mode == "fit":
        bw, bh, cols, rows = fit_blocks(world.width, world.height, area_w, area_h)
        tiles: List[List[Optional[Coord]]] = []
        for ry in range(rows):
            y0 = ry * bh
            y1 = min(world.height, y0 + bh)
            row: List[Optional[Coord]] = []
            for rx in range(cols):
                x0 = rx * bw
                x1 = min(world.width, x0 + bw)
                row.append(_representative_tile(world, x0, y0, x1, y1))
            tiles.append(row)
            cursor: Optional[Coord] = (vs.cx // bw, vs.cy // bh)
        frame = Frame(cols, rows, tiles, cursor, block_w=bw, block_h=bh)
        if config is not None:
            to_screen_fit: Callable[[int, int], Coord] = lambda wx, wy: (wx // bw, wy // bh)  # noqa: E731
            frame.overrides = _stamp_map_interiors(world, config, overlay, rows, cols, to_screen_fit)
        return frame

    # 1:1 panning: one screen cell per world tile, windowed by the camera (already edge-panned).
    cam_x, cam_y = vs.cam_x, vs.cam_y
    pan_tiles: List[List[Optional[Coord]]] = []
    for sy in range(area_h):
        wy = cam_y + sy
        pan_row: List[Optional[Coord]] = []
        for sx in range(area_w):
            wx = cam_x + sx
            pan_row.append((wx, wy) if 0 <= wx < world.width and 0 <= wy < world.height else None)
        pan_tiles.append(pan_row)
    scx, scy = vs.cx - cam_x, vs.cy - cam_y
    pan_cursor: Optional[Coord] = (scx, scy) if 0 <= scx < area_w and 0 <= scy < area_h else None
    frame = Frame(area_w, area_h, pan_tiles, pan_cursor)
    if config is not None:
        to_screen_pan: Callable[[int, int], Coord] = lambda wx, wy: (wx - cam_x, wy - cam_y)  # noqa: E731
        frame.overrides = _stamp_map_interiors(world, config, overlay, area_h, area_w, to_screen_pan)
    return frame
