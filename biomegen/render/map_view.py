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
from typing import List, Optional, Tuple

from ..world.tile import Biome
from ..world.world import World
from .state import ViewState

Coord = Tuple[int, int]

# Feature priority for fit-to-screen reduction: a block shows its highest-priority tile. Landmarks
# and water beat plain land so small but important features (a lone lake, a river thread) survive.
_BIOME_PRIORITY = {
    int(Biome.OCEAN): 5,
    int(Biome.DESERT): 28,
    int(Biome.GRASSLAND): 30,
    int(Biome.SHRUBLAND): 30,
    int(Biome.SAVANNA): 30,
    int(Biome.TUNDRA): 35,
    int(Biome.FOREST): 40,
    int(Biome.TAIGA): 40,
    int(Biome.JUNGLE): 42,
    int(Biome.BEACH): 48,
    int(Biome.SWAMP): 50,
    int(Biome.MOUNTAIN): 58,
    int(Biome.SNOW): 60,
    int(Biome.LAKE): 75,
    int(Biome.RIVER): 80,
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


def feature_priority(world: World, x: int, y: int) -> int:
    """Return how salient tile ``(x, y)`` is for down-sampling (higher wins within a block)."""
    if world.poi_index[y, x] >= 0:
        return _POI_PRIORITY
    if world.road[y, x]:
        return _ROAD_PRIORITY
    return _BIOME_PRIORITY.get(int(world.biome[y, x]), 20)


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


def build_biome_frame(world: World, vs: ViewState, area_w: int, area_h: int) -> Frame:
    """Build the biome-map :class:`Frame` for the current view mode and camera."""
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
        return Frame(cols, rows, tiles, cursor, block_w=bw, block_h=bh)

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
    return Frame(area_w, area_h, pan_tiles, pan_cursor)
