"""Where a POI's site lies in the world and how finely it is drawn.

A site is centred on its POI's anchor and measured in world tiles, so it can be smaller than one tile (a tower, a
camp), about one tile (a village) or span several (a capital). Its plan is drawn on a **window**: the whole tiles that
hold the extent plus ``sites.margin_tiles`` of terrain around it. The window is a detail grid of ``cell_w x cell_h``
cells per tile, so a plan cell is one terminal cell and lines up with the detail sampler's cells exactly.

Tile coordinates have tile centres on the integers, as in :mod:`biomegen.sampling`: tile ``t`` spans
``[t - 0.5, t + 0.5)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..config.model import Config
from ..util import rng
from ..world.entities import POI

_MIN_CELLS = 3  # a plan needs room for a wall, a floor cell and a wall


@dataclass(frozen=True)
class SiteGeometry:
    """The extent, window and resolution of one POI's site.

    Attributes:
        kind: The POI kind (its ``tables.sites`` row).
        cell_w: Plan cells per tile across.
        cell_h: Plan cells per tile down.
        cam_x: First tile column of the window.
        cam_y: First tile row of the window.
        tiles_w: Whole tiles across the window.
        tiles_h: Whole tiles down the window.
        extent: ``(left, top, right, bottom)`` of the site in tile coordinates.
        box: ``(col0, row0, col1, row1)`` of the extent in window cells (end exclusive).
    """

    kind: str
    cell_w: int
    cell_h: int
    cam_x: int
    cam_y: int
    tiles_w: int
    tiles_h: int
    extent: tuple[float, float, float, float]
    box: tuple[int, int, int, int]

    @property
    def cols(self) -> int:
        """Window width in cells."""
        return self.tiles_w * self.cell_w

    @property
    def rows(self) -> int:
        """Window height in cells."""
        return self.tiles_h * self.cell_h

    @property
    def box_cols(self) -> int:
        """Extent width in cells."""
        return self.box[2] - self.box[0]

    @property
    def box_rows(self) -> int:
        """Extent height in cells."""
        return self.box[3] - self.box[1]

    def cell_at(self, x: float, y: float) -> tuple[int, int]:
        """Return the ``(col, row)`` of the window cell holding tile position ``(x, y)`` (it may lie off the window)."""
        col = math.floor((x - (self.cam_x - 0.5)) * self.cell_w)
        row = math.floor((y - (self.cam_y - 0.5)) * self.cell_h)
        return col, row

    def position_of(self, col: int, row: int) -> tuple[float, float]:
        """Return the tile position at the centre of window cell ``(col, row)``."""
        return self.cam_x - 0.5 + (col + 0.5) / self.cell_w, self.cam_y - 0.5 + (row + 0.5) / self.cell_h

    def covers_tile(self, tile_x: int, tile_y: int) -> bool:
        """Return whether tile ``(tile_x, tile_y)`` lies under the extent (a tile counts when its centre is within half
        a tile of the extent, so a sub-tile site covers only its own tile)."""
        left, top, right, bottom = self.extent
        return left - 0.5 < tile_x < right + 0.5 and top - 0.5 < tile_y < bottom + 0.5


def site_row_name(config: Config, kind: str, purpose: str = "") -> str:
    """Return the ``tables.sites`` row that draws a POI: ``<kind>_<purpose>`` when that row exists, else ``kind``."""
    named = f"{kind}_{purpose}"
    return named if purpose and config.get(f"tables.sites.{named}", None) is not None else kind


def _scale(poi: POI, config: Config, row: dict) -> float:
    """Return the extent factor for ``poi``: a seeded jitter, times a population factor for growing settlements."""
    jitter = float(config.get("sites.size_jitter"))
    factor = 1.0 + jitter * (2.0 * rng.derive(poi.interior_seed, "site.extent").random() - 1.0)
    if row["grows_with_pop"]:
        lo, hi = config.get(f"tables.tiers.{poi.kind}.pop")
        small, large = config.get("sites.pop_scale")
        share = 0.0 if hi <= lo else min(1.0, max(0.0, (poi.pop - lo) / (hi - lo)))
        factor *= small + (large - small) * share
    return factor


def site_geometry(poi: POI, config: Config) -> Optional[SiteGeometry]:
    """Return ``poi``'s site geometry, or ``None`` when its kind has no site row or the site would be too small."""
    row = config.get(f"tables.sites.{site_row_name(config, poi.kind, poi.purpose)}", None)
    if row is None:
        return None
    factor = _scale(poi, config, row)
    half_w, half_h = row["extent_tiles"][0] * factor / 2.0, row["extent_tiles"][1] * factor / 2.0
    extent = (poi.x - half_w, poi.y - half_h, poi.x + half_w, poi.y + half_h)
    margin = float(config.get("sites.margin_tiles"))
    cam_x = math.floor(extent[0] - margin + 0.5)
    cam_y = math.floor(extent[1] - margin + 0.5)
    tiles_w = math.ceil(extent[2] + margin + 0.5) - cam_x
    tiles_h = math.ceil(extent[3] + margin + 0.5) - cam_y
    cell_h = int(row["rows_per_tile"])
    cell_w = max(cell_h, round(cell_h * float(config.get("render.cell_aspect"))))
    geometry = SiteGeometry(poi.kind, cell_w, cell_h, cam_x, cam_y, tiles_w, tiles_h, extent, (0, 0, 0, 0))
    col0, row0 = geometry.cell_at(extent[0], extent[1])
    col1, row1 = geometry.cell_at(extent[2], extent[3])
    box = (col0, row0, col1, row1)
    if col1 - col0 < _MIN_CELLS or row1 - row0 < _MIN_CELLS:
        return None
    return SiteGeometry(poi.kind, cell_w, cell_h, cam_x, cam_y, tiles_w, tiles_h, extent, box)
