"""Render layers: pure functions that paint one concern onto a :class:`~biomegen.render.grid.CellGrid`.

A view runs its configured layers in order, bottom to top (``render.views``). Each layer reads the world
through the :class:`LayerContext` (never the world arrays directly) and writes only the cells it owns.
Importing this package registers the built-in layers in :data:`LAYERS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Callable, Optional

import numpy as np

from ...config.model import Config
from ...registry import Registry
from ...util import rng
from ...world.overlay import Overlay
from ...world.tile import Biome
from ...world.world import World
from ..colors import BiomeStyle, ReliefStyle, biome_style, relief_style
from ..grid import CellGrid
from ..sampler import Sampler
from ..scatter import scatter01
from ..views import View


@dataclass
class LayerContext:
    """Everything a layer reads, with the per-cell fields every layer needs computed once.

    Attributes:
        world: The generated world (read only).
        config: The merged configuration.
        view: The view being drawn.
        sampler: Maps grid cells to world positions.
        overlay: Runtime edits composited over the world, or ``None``.
        ascii_only: Use the ``ascii`` glyph columns of the tables.
        color: Whether the output is coloured. Without colour the glyphs must carry the information, so
            sparse biomes show their glyph on every cell and the sea sparkle is off.
    """

    world: World
    config: Config
    view: View
    sampler: Sampler
    overlay: Optional[Overlay] = None
    ascii_only: bool = False
    color: bool = True

    @cached_property
    def biome_style(self) -> BiomeStyle:
        return biome_style(self.config, self.ascii_only)

    @cached_property
    def relief_style(self) -> ReliefStyle:
        return relief_style(self.config, self.ascii_only)

    @cached_property
    def biome(self) -> np.ndarray:
        """Biome integer per cell."""
        return self.sampler.biome()

    @cached_property
    def land(self) -> np.ndarray:
        """Cells inside the world whose biome is not water."""
        return self.sampler.inside & ~self.biome_style.water[self.biome]

    @cached_property
    def relief(self) -> np.ndarray:
        """Relief integer per cell."""
        return self.sampler.nearest(self.world.relief)

    @cached_property
    def elevation_m(self) -> np.ndarray:
        """Elevation in metres per cell (bilinear)."""
        return self.sampler.bilinear(self.world.elevation_m)

    @cached_property
    def shade(self) -> np.ndarray:
        """Hillshade brightness per cell: lit from the north-west, in ``render.shade`` limits."""
        cfg = self.config.get("render.shade")
        dry = np.maximum(self.world.elevation_m, 0.0)
        rise = self.sampler.bilinear(dry, 1.0, 1.0) - self.sampler.bilinear(dry, -1.0, -1.0)
        return np.clip(1.0 + rise / float(cfg["relief_m"]) * float(cfg["strength"]), cfg["min"], cfg["max"])

    def scatter(self, *labels: object) -> np.ndarray:
        """Return a stable uniform value in [0, 1) per cell, keyed on the world tile and ``labels``."""
        salt = rng.derive_int(self.world.seed, "render", *labels)
        return scatter01(salt, self.sampler.tile_x, self.sampler.tile_y)

    def biome_is(self, *biomes: Biome) -> np.ndarray:
        """Return a mask of the cells whose biome is any of ``biomes``."""
        return np.isin(self.biome, [int(b) for b in biomes])


Layer = Callable[[LayerContext, CellGrid], None]

LAYERS: Registry[Layer] = Registry("render_layer")


def build_grid(
    world: World,
    config: Config,
    view: View,
    sampler: Sampler,
    overlay: Optional[Overlay] = None,
    ascii_only: bool = False,
    color: bool = True,
) -> CellGrid:
    """Draw ``view`` of ``world`` through ``sampler`` and return the finished grid."""
    layers = [LAYERS.get(name) for name in view.layers]  # resolve first so a typo fails before any work
    context = LayerContext(world, config, view, sampler, overlay, ascii_only, color)
    grid = CellGrid(sampler.rows, sampler.cols)
    for layer in layers:
        layer(context, grid)
    return grid


from . import markers, relief, roads, terrain, tint, water  # noqa: E402,F401  (registers the built-in layers)
