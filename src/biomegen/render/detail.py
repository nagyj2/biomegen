"""The detail scales: zoom and local magnify tiles into blocks of cells with a continuous, warped lookup.

At map scale a cell is a tile. At ``zoom`` and ``local`` a tile becomes a ``cell_w x cell_h`` block, and each
cell reads the world at its own continuous position, nudged by a coherent noise warp so the square tile grid
does not show: biome borders become irregular and water joins diagonally. The warp is a pure function of world
position and seed, so zoom and local are coarse and fine samplings of the same field (they look like zooms of
one another), and a layer written for the map works unchanged on a detail sampler.

The warp noise is read at the old tile-corner convention (tile ``t`` spans ``[t, t + 1)``), so the shapes match
the curses-era views even though samplers put tile centres on the integers.
"""

from __future__ import annotations

from functools import cached_property

import numpy as np

from ..config.model import Config
from ..util import noise, rng
from ..world.tile import WATER_BIOMES
from ..world.world import World
from .sampler import Sampler, bilinear_at

SCALE_MAP = "map"
SCALE_ZOOM = "zoom"
SCALE_LOCAL = "local"
SCALES = (SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL)

_WATER = np.array(sorted(WATER_BIOMES), dtype=np.int64)


def detail_cell_size(scale: str, config: Config, area_w: int, area_h: int) -> tuple[int, int]:
    """Return the ``(cell_w, cell_h)`` cells per tile for a detail ``scale``.

    Both scales are aspect-corrected: the cell height sets the magnification and the width is widened by
    ``render.cell_aspect`` so a square tile reads roughly square on a terminal whose cells are taller than wide.
    ``zoom`` uses ``render.zoom_scale`` as the height; ``local`` sizes it so about ``render.local_rows`` tiles
    fit the area's height.
    """
    aspect = float(config.get("render.cell_aspect"))
    if scale == SCALE_LOCAL:
        local_rows = max(1, int(config.get("render.local_rows")))
        cell_h = max(2, area_h // local_rows)
    else:
        cell_h = max(1, int(config.get("render.zoom_scale")))
    return max(cell_h, int(round(cell_h * aspect))), cell_h


def _dominant_water_biome(biome: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return the biome of the water tile with the largest bilinear weight around each ``(x, y)``."""
    height, width = biome.shape
    x = np.clip(x, 0.0, width - 1.0)
    y = np.clip(y, 0.0, height - 1.0)
    x0 = np.minimum(np.floor(x).astype(np.int64), max(width - 2, 0))
    y0 = np.minimum(np.floor(y).astype(np.int64), max(height - 2, 0))
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = x - x0
    ty = y - y0
    corners_x = np.stack([x0, x1, x0, x1])
    corners_y = np.stack([y0, y0, y1, y1])
    weights = np.stack([(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty])
    corner_biome = biome[corners_y, corners_x]
    weights = weights * np.isin(corner_biome, _WATER)
    best = np.argmax(weights, axis=0)
    return np.take_along_axis(corner_biome, best[np.newaxis], axis=0)[0]


class DetailSampler(Sampler):
    """A sampler whose cells are sub-tile blocks read through the biome-blend warp.

    Attributes:
        scale: ``"zoom"`` or ``"local"``.
        cell_w: Cells per tile across.
        cell_h: Cells per tile down.
        cam_x: Tile column at the left edge of the grid.
        cam_y: Tile row at the top edge of the grid.
        tiles_w: Whole tiles across the grid.
        tiles_h: Whole tiles down the grid.
    """

    detailed = True

    def __init__(
        self,
        world: World,
        config: Config,
        cell_w: int,
        cell_h: int,
        cam_x: int,
        cam_y: int,
        tiles_w: int,
        tiles_h: int,
        scale: str = SCALE_ZOOM,
    ) -> None:
        self.scale = scale
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.cam_x = cam_x
        self.cam_y = cam_y
        self.tiles_w = tiles_w
        self.tiles_h = tiles_h
        self.config = config
        cols = tiles_w * cell_w
        rows = tiles_h * cell_h
        col_index = np.arange(cols)
        row_index = np.arange(rows)
        fx = cam_x + (col_index + 0.5) / cell_w - 0.5
        fy = cam_y + (row_index + 0.5) / cell_h - 0.5
        grid_x, grid_y = np.meshgrid(fx, fy)
        super().__init__(world, grid_x, grid_y)
        self.sub_x = np.broadcast_to(col_index % cell_w, (rows, cols)).astype(np.int64)
        self.sub_y = np.broadcast_to((row_index % cell_h)[:, np.newaxis], (rows, cols)).astype(np.int64)
        self.anchor = (self.sub_x == cell_w // 2) & (self.sub_y == cell_h // 2)

    @cached_property
    def warp_noise(self) -> tuple[np.ndarray, np.ndarray]:
        """The coherent warp field ``(nx, ny)`` in roughly [-1, 1] per cell, before any strength is applied."""
        scale = max(1e-6, float(self.config.get("render.blend_scale")))
        backend = self.config.get("terrain.noise_backend")
        xs, ys = (self.fx + 0.5) / scale, (self.fy + 0.5) / scale
        nx = noise.get_sampler(backend, rng.derive_int(self.world.seed, "biomeblend.x"))(xs, ys)
        ny = noise.get_sampler(backend, rng.derive_int(self.world.seed, "biomeblend.y"))(xs, ys)
        return nx, ny

    def warped(self, strength: float) -> tuple[np.ndarray, np.ndarray]:
        """Return each cell's position moved by the warp field times ``strength`` tiles (unchanged at 0)."""
        if strength <= 0:
            return self.fx, self.fy
        nx, ny = self.warp_noise
        return self.fx + strength * nx, self.fy + strength * ny

    @cached_property
    def _blend(self) -> tuple[np.ndarray, np.ndarray]:
        """Warped positions under ``render.blend_strength``."""
        return self.warped(float(self.config.get("render.blend_strength")))

    @cached_property
    def warped_tile(self) -> tuple[np.ndarray, np.ndarray]:
        """The ``(tile_x, tile_y)`` each cell reads after warping, clamped to the world."""
        wfx, wfy = self._blend
        return (
            np.clip(np.rint(wfx).astype(np.int64), 0, self.world.width - 1),
            np.clip(np.rint(wfy).astype(np.int64), 0, self.world.height - 1),
        )

    def blended(self, field: np.ndarray) -> np.ndarray:
        """Return ``field`` read at the warped tile under each cell."""
        tile_x, tile_y = self.warped_tile
        return field[tile_y, tile_x]

    def coverage_mask(self, mask: np.ndarray) -> np.ndarray:
        """Return where the boolean tile ``mask`` covers at least ``render.water_blend_threshold`` around each cell.

        A threshold under one half fills the gap between two corner-touching tiles, so diagonal rivers and
        lakes join instead of forming a checkerboard.
        """
        wfx, wfy = self._blend
        threshold = float(self.config.get("render.water_blend_threshold"))
        return bilinear_at(mask.astype(np.float64), wfx, wfy) >= threshold

    def biome(self) -> np.ndarray:
        """Return the blended biome: sea and lake water by coverage, land by the warped tile.

        Water uses :meth:`coverage_mask` over the water biomes, taking the biome of the heaviest water
        neighbour; land uses the warped tile, falling back to the unwarped tile when the warp lands in water.
        Rivers are not a biome here; the water layer draws them over the land biome.
        """
        biome = self.world.biome
        wfx, wfy = self._blend
        is_water = self.coverage_mask(np.isin(biome, _WATER))
        warped = self.blended(biome)
        land = np.where(np.isin(warped, _WATER), self.nearest(biome), warped)
        return np.where(is_water, _dominant_water_biome(biome, wfx, wfy), land)

    def cell_window(self, x_min: float, x_max: float, y_min: float, y_max: float) -> tuple[slice, slice] | None:
        """Return the ``(rows, cols)`` slices of the cells whose unwarped position can lie in the tile box.

        The box is in tile coordinates; ``None`` means it misses the grid entirely.
        """
        col_lo = max(0, int(np.floor((x_min - self.cam_x + 0.5) * self.cell_w - 0.5)))
        col_hi = min(self.cols - 1, int(np.ceil((x_max - self.cam_x + 0.5) * self.cell_w - 0.5)))
        row_lo = max(0, int(np.floor((y_min - self.cam_y + 0.5) * self.cell_h - 0.5)))
        row_hi = min(self.rows - 1, int(np.ceil((y_max - self.cam_y + 0.5) * self.cell_h - 0.5)))
        if col_hi < col_lo or row_hi < row_lo:
            return None
        return slice(row_lo, row_hi + 1), slice(col_lo, col_hi + 1)

    def cell_of(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the ``(col, row)`` of the centre cell of tile ``(x, y)``'s block, or ``None`` if off the grid."""
        col = (round(x) - self.cam_x) * self.cell_w + self.cell_w // 2
        row = (round(y) - self.cam_y) * self.cell_h + self.cell_h // 2
        return (col, row) if 0 <= col < self.cols and 0 <= row < self.rows else None


def detail_sampler(
    world: World, config: Config, scale: str, area_w: int, area_h: int, cam_x: int, cam_y: int
) -> DetailSampler:
    """Return the sampler for ``scale`` over an ``area_w x area_h`` cell area with tile ``(cam_x, cam_y)`` top-left.

    The grid holds whole tiles only (``area // cell`` of each), so its size can be a little under the area.
    """
    cell_w, cell_h = detail_cell_size(scale, config, area_w, area_h)
    return DetailSampler(
        world, config, cell_w, cell_h, cam_x, cam_y, max(1, area_w // cell_w), max(1, area_h // cell_h), scale
    )


def centre_camera(tile: int, tiles: int, world_size: int) -> int:
    """Return the first tile of a ``tiles``-wide window that centres ``tile``, kept inside the world.

    A world smaller than the window is centred in it instead, which gives a negative first tile (the
    outside cells stay blank).
    """
    if world_size <= tiles:
        return -((tiles - world_size) // 2)
    return max(0, min(tile - tiles // 2, world_size - tiles))


def centred_detail_sampler(
    world: World, config: Config, scale: str, area_w: int, area_h: int, at: tuple[int, int]
) -> DetailSampler:
    """Return the sampler for ``scale`` over an ``area_w x area_h`` cell area centred on tile ``at``."""
    cell_w, cell_h = detail_cell_size(scale, config, area_w, area_h)
    tiles_w, tiles_h = max(1, area_w // cell_w), max(1, area_h // cell_h)
    return DetailSampler(
        world,
        config,
        cell_w,
        cell_h,
        centre_camera(at[0], tiles_w, world.width),
        centre_camera(at[1], tiles_h, world.height),
        tiles_w,
        tiles_h,
        scale,
    )
