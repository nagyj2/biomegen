"""Samplers: how a grid cell reads the world.

A layer never indexes the world arrays directly. It asks the :class:`Sampler` for the value under each
grid cell, so the same layer code draws the whole-island map (one cell per tile, or a stride over it)
and, later, the magnified detail scales (many cells per tile, sampled continuously). A sampler is a pure
function of world position, so two scales agree on what lies at the same place.
"""

from __future__ import annotations

import numpy as np

from ..world.world import World


def bilinear_at(field: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Return ``field`` interpolated at tile positions ``(x, y)`` (tile centres on the integers, edge-clamped)."""
    height, width = field.shape
    x = np.clip(x, 0.0, width - 1.0)
    y = np.clip(y, 0.0, height - 1.0)
    x0 = np.minimum(np.floor(x).astype(np.int64), max(width - 2, 0))
    y0 = np.minimum(np.floor(y).astype(np.int64), max(height - 2, 0))
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = x - x0
    ty = y - y0
    top = field[y0, x0] * (1.0 - tx) + field[y0, x1] * tx
    bottom = field[y1, x0] * (1.0 - tx) + field[y1, x1] * tx
    return top * (1.0 - ty) + bottom * ty


class Sampler:
    """Maps every cell of a ``rows x cols`` grid to a continuous world position ``(fx, fy)``.

    World coordinates are in tile units with tile centres on the integers, so ``fx = 3.0`` is the centre of
    column 3. Positions outside the world are flagged in :attr:`inside`; reads there are clamped to the edge
    tile and layers leave those cells blank.

    Attributes:
        sub_x: Index of the cell inside its tile's block of cells (zeros when a cell is a whole tile), so
            decoration can differ cell to cell within one tile. ``sub_y`` is the row equivalent.
    """

    def __init__(self, world: World, fx: np.ndarray, fy: np.ndarray) -> None:
        self._origin: tuple[float, float, float, float] | None = None  # (x0, y0, step_x, step_y) of a viewport
        self.world = world
        self.fx = fx
        self.fy = fy
        self.rows = int(fx.shape[0])
        self.cols = int(fx.shape[1])
        raw_x = np.rint(fx).astype(np.int64)
        raw_y = np.rint(fy).astype(np.int64)
        self.inside = (raw_x >= 0) & (raw_x < world.width) & (raw_y >= 0) & (raw_y < world.height)
        self.tile_x = np.clip(raw_x, 0, world.width - 1)
        self.tile_y = np.clip(raw_y, 0, world.height - 1)
        self.sub_x = np.zeros(fx.shape, dtype=np.int64)
        self.sub_y = np.zeros(fx.shape, dtype=np.int64)

    @classmethod
    def viewport(
        cls,
        world: World,
        rows: int,
        cols: int,
        x0: float = 0.0,
        y0: float = 0.0,
        step_x: float = 1.0,
        step_y: float = 1.0,
    ) -> "Sampler":
        """Return a sampler whose cell ``(row, col)`` reads world position ``(x0 + col*step_x, y0 + row*step_y)``.

        ``step`` 1 is one cell per tile; larger steps stride over the map to fit a small screen.
        """
        fx = x0 + np.arange(cols, dtype=np.float64) * step_x
        fy = y0 + np.arange(rows, dtype=np.float64) * step_y
        grid_x, grid_y = np.meshgrid(fx, fy)
        sampler = cls(world, grid_x, grid_y)
        sampler._origin = (x0, y0, step_x, step_y)
        return sampler

    def cell_of(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the ``(col, row)`` of the grid cell that shows tile ``(x, y)``, or ``None`` if it is off the grid.

        Only viewport samplers can invert their mapping; the warped detail samplers return ``None``.
        """
        if self._origin is None:
            return None
        x0, y0, step_x, step_y = self._origin
        col = round((x - x0) / step_x)
        row = round((y - y0) / step_y)
        return (col, row) if 0 <= col < self.cols and 0 <= row < self.rows else None

    def nearest(self, field: np.ndarray) -> np.ndarray:
        """Return ``field`` read at the nearest tile under each cell."""
        return field[self.tile_y, self.tile_x]

    def bilinear(self, field: np.ndarray, dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
        """Return ``field`` interpolated at each cell's position offset by ``(dx, dy)`` tiles (edge-clamped)."""
        return bilinear_at(field, self.fx + dx, self.fy + dy)

    def blended(self, field: np.ndarray) -> np.ndarray:
        """Return ``field`` read where the biome is read: the nearest tile here, the warped one at detail scales."""
        return self.nearest(field)

    def coverage_mask(self, mask: np.ndarray) -> np.ndarray:
        """Return where the boolean tile ``mask`` holds under each cell (the detail scales smooth its edge)."""
        return self.nearest(mask)

    def biome(self) -> np.ndarray:
        """Return the biome under each cell (the detail scales override this with a blended lookup)."""
        return self.blended(self.world.biome)
