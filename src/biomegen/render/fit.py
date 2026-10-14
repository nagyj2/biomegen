"""The fit-to-screen map scale: each cell covers a block of tiles and shows the block's most salient tile.

A plain stride would drop a lone lake, a river thread or a road when it falls between sampled tiles. Choosing
the highest-priority tile of each block keeps coastlines and landmarks legible on a small screen, which an
average would smear. Priorities come from the ``priority`` columns of ``tables.biomes`` and ``tables.relief`` and
``render.fit_priority`` (points of interest, roads, rivers).
"""

from __future__ import annotations

import math

import numpy as np

from ..config.model import Config
from ..world.tile import BIOME_NAME, Biome, Relief, WaterType
from ..world.world import World
from .sampler import Sampler


def fit_blocks(world_w: int, world_h: int, area_w: int, area_h: int) -> tuple[int, int, int, int]:
    """Return ``(block_w, block_h, cols, rows)`` for fitting a world into an ``area_w x area_h`` grid."""
    block_w = max(1, math.ceil(world_w / max(1, area_w)))
    block_h = max(1, math.ceil(world_h / max(1, area_h)))
    return block_w, block_h, math.ceil(world_w / block_w), math.ceil(world_h / block_h)


def tile_priority(world: World, config: Config) -> np.ndarray:
    """Return the fit-to-screen salience of every tile (higher wins within a block)."""
    biomes = config.get("tables.biomes")
    reliefs = config.get("tables.relief")
    by_biome = np.zeros(max(int(b) for b in Biome) + 1, dtype=np.int64)
    for biome in Biome:
        by_biome[int(biome)] = biomes[BIOME_NAME[int(biome)]]["priority"]
    by_relief = np.zeros(max(int(r) for r in Relief) + 1, dtype=np.int64)
    for relief in Relief:
        by_relief[int(relief)] = reliefs[relief.name.lower()]["priority"]
    fixed = config.get("render.fit_priority")
    water = np.array([bool(biomes[BIOME_NAME[int(b)]]["water"]) for b in sorted(Biome)])
    priority = np.maximum(by_biome[world.biome], by_relief[world.relief])
    river = (world.water_type == int(WaterType.FRESH)) & ~water[world.biome]
    priority = np.where(river, np.maximum(priority, int(fixed["river"])), priority)
    priority = np.where(world.road > 0, np.maximum(priority, int(fixed["road"])), priority)
    return np.where(world.poi_index >= 0, np.maximum(priority, int(fixed["poi"])), priority)


class FitSampler(Sampler):
    """A sampler whose cell ``(row, col)`` reads the most salient tile of the ``block_w x block_h`` block it covers.

    Attributes:
        block_w: Tiles per cell across.
        block_h: Tiles per cell down.
    """

    def __init__(self, world: World, config: Config, area_w: int, area_h: int) -> None:
        self.block_w, self.block_h, cols, rows = fit_blocks(world.width, world.height, area_w, area_h)
        padded_h, padded_w = rows * self.block_h, cols * self.block_w
        priority = np.full((padded_h, padded_w), -1, dtype=np.int64)  # padding never wins
        priority[: world.height, : world.width] = tile_priority(world, config)
        blocks = priority.reshape(rows, self.block_h, cols, self.block_w).transpose(0, 2, 1, 3)
        best = blocks.reshape(rows, cols, self.block_h * self.block_w).argmax(axis=2)  # first max, row-major
        tile_x = np.arange(cols)[np.newaxis, :] * self.block_w + best % self.block_w
        tile_y = np.arange(rows)[:, np.newaxis] * self.block_h + best // self.block_w
        super().__init__(world, tile_x.astype(np.float64), tile_y.astype(np.float64))

    def cell_coords(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the cell whose block contains tile ``(x, y)``."""
        return int(x) // self.block_w, int(y) // self.block_h
