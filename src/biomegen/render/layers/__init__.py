"""Render layers: pure functions that paint one concern onto a :class:`~biomegen.render.grid.CellGrid`.

A view runs its configured layers in order, bottom to top (``render.views``). Each layer reads the world
through the :class:`LayerContext` (never the world arrays directly) and writes only the cells it owns.
Importing this package registers the built-in layers in :data:`LAYERS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Callable, Optional

import numpy as np

from ...config.model import Config
from ...registry import Registry
from ...sampling.sampler import Sampler
from ...sampling.terrain import land_mask, river_mask
from ...util import rng
from ...world.lifespans import visible_pois
from ...world.overlay import Overlay
from ...world.territory import FALLEN_OWNER_BASE, PREDECESSOR_OWNER_BASE, WILD
from ...world.tile import Biome
from ...world.wars import wars_at
from ...world.world import World
from ..colors import (
    BiomeStyle,
    DetailStyle,
    InteriorStyle,
    ReliefStyle,
    biome_style,
    detail_style,
    interior_style,
    relief_style,
)
from ..grid import CellGrid
from ..scatter import scatter01
from ..views import View


@dataclass
class Seen:
    """What a draw put on screen, for legends: the biome and interior-cell integers that appear.

    Attributes:
        biomes: Biome integers under the cells inside the world.
        cells: Interior ``Cell`` integers drawn by the interiors layer.
        cell_map: The interior ``Cell`` integer under each grid cell (``-1`` where none was drawn), or ``None``
            until an interiors layer has drawn.
    """

    biomes: set[int] = field(default_factory=set)
    cells: set[int] = field(default_factory=set)
    cell_map: Optional[np.ndarray] = None


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
        labels: ``"all"`` draws feature names, ``"none"`` leaves them off.
        floor: The floor of a multi-floor interior to draw (clamped to each POI's own floors).
        seen: Filled by the layers with the biomes and interior cells drawn.
        moment: A ``(year, month)`` to draw the political map at (``World.owners_at``), or ``None`` for the present.
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
    labels: str = "all"
    floor: int = 0
    seen: Seen = field(default_factory=Seen)
    moment: Optional[tuple[int, int]] = None

    @cached_property
    def biome_style(self) -> BiomeStyle:
        return biome_style(self.config, self.ascii_only)

    @cached_property
    def relief_style(self) -> ReliefStyle:
        return relief_style(self.config, self.ascii_only)

    @cached_property
    def interior_style(self) -> InteriorStyle:
        return interior_style(self.config, self.ascii_only)

    @cached_property
    def detail_style(self) -> DetailStyle:
        return detail_style(self.config, self.ascii_only)

    @cached_property
    def biome(self) -> np.ndarray:
        """Biome integer per cell."""
        return self.sampler.biome()

    @cached_property
    def land(self) -> np.ndarray:
        """Cells inside the world whose biome is not water."""
        return land_mask(self.sampler, self.biome, self.biome_style.water)

    @cached_property
    def river(self) -> np.ndarray:
        """Land cells covered by a river: fresh water over a land biome (smoothed at the detail scales)."""
        return river_mask(self.sampler, self.world, self.land, self.biome_style.water)

    @cached_property
    def relief(self) -> np.ndarray:
        """Relief integer per cell (read where the biome is, so mountain edges wobble with biome edges)."""
        return self.sampler.blended(self.world.relief)

    @cached_property
    def rocky(self) -> np.ndarray:
        """Detail-scale land cells whose relief replaces the biome's floor (mountains, peaks, volcanoes)."""
        return self.land & self.detail_style.relief_rocky[self.relief]

    @cached_property
    def detail_row(self) -> np.ndarray:
        """Row of the detail style per cell: the biome, or ``biome_count + relief`` on a rocky cell."""
        return np.where(self.rocky, self.detail_style.biome_count + self.relief, self.biome)

    @cached_property
    def detail_floor(self) -> np.ndarray:
        """Floor glyph per cell for the detail scales."""
        style = self.detail_style
        return np.where(self.rocky, style.relief_floor[self.relief], style.floor[self.biome])

    @cached_property
    def owners(self) -> np.ndarray:
        """The ``[y, x]`` owner grid being drawn: ``World.realm_id``, or the owners at :attr:`moment`."""
        return self.world.realm_id if self.moment is None else self.world.owners_at(*self.moment)

    @cached_property
    def realm(self) -> np.ndarray:
        """Palette index per land cell, -1 on wild land and water.

        A realm's index is its id; at a past moment a fallen realm's is ``n + id`` and a predecessor's follows the
        fallen realms (:func:`owner_palette_index`). Read where the biome is read (the warped tile at the detail
        scales), so a border wobbles like a biome edge and zoom and local agree; a land cell whose warped tile holds no
        owner takes the owner of its own tile.
        """
        owners = self.owners
        codes = self.sampler.blended(owners).astype(np.int64)
        codes = np.where((codes < 0) & self.land, self.sampler.nearest(owners), codes)
        return np.where(self.land, owner_palette_index(self.world, codes), -1)

    @cached_property
    def tops(self) -> np.ndarray:
        """Independent power per palette index (realms, then fallen realms and predecessors as themselves); -1 is last.

        At a past moment a vassal tie counts only from its conquest.
        """
        world = self.world
        if self.moment is None:
            tops = [world.top_realm(r.id) for r in world.realms]
        else:
            tops = [world.top_realm_at(r.id, *self.moment) for r in world.realms]
        extra = range(len(world.realms), len(world.realms) + len(world.fallen_realms) + len(world.predecessors))
        return np.array(tops + list(extra) + [-1])

    @cached_property
    def visible_pois(self) -> np.ndarray:
        """A bool per ``World.pois`` entry: whether it stands (all do today; at a past moment those founded by then)."""
        if self.moment is None:
            return np.ones(len(self.world.pois), dtype=bool)
        return visible_pois(self.world, self.config, self.moment)

    @cached_property
    def held_pois(self) -> np.ndarray:
        """A bool per POI: whether a realm (or a fallen one) holds its cell. Today that is ``not poi.free``; at a past
        moment the owner grid says, so a settlement on wild land is free then."""
        pois = self.world.pois
        if self.moment is None:
            return np.array([not poi.free for poi in pois], dtype=bool)
        return np.array([int(self.owners[poi.y, poi.x]) != WILD for poi in pois], dtype=bool)

    @cached_property
    def at_war(self) -> np.ndarray:
        """``bool [n, n]`` over the palette indices (-1 is last): which two independent powers are at war at the moment.

        Empty for the present, whose war fronts are ``World.front``.
        """
        tops = self.tops
        matrix = np.zeros((len(tops), len(tops)), dtype=bool)
        if self.moment is not None:
            for attacker, defender in wars_at(self.world, self.moment):
                first, second = int(tops[attacker]), int(tops[defender])
                if first != second:
                    matrix[first, second] = matrix[second, first] = True
        return matrix

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
        """Return a stable uniform value in [0, 1) per cell, keyed on the world tile, the cell in it and ``labels``."""
        salt = rng.derive_int(self.world.seed, "render", *labels)
        return scatter01(salt, self.sampler.tile_x, self.sampler.tile_y, self.sampler.sub_x, self.sampler.sub_y)

    def biome_is(self, *biomes: Biome) -> np.ndarray:
        """Return a mask of the cells whose biome is any of ``biomes``."""
        return np.isin(self.biome, [int(b) for b in biomes])


def owner_palette_index(world: World, codes: np.ndarray) -> np.ndarray:
    """Map owner values to palette indices: a realm is its id, wild land -1, a fallen realm ``n + id`` and a predecessor
    ``n + fallen realms + id`` (``n`` realms), so one colour table serves every owner."""
    realms, fallen = len(world.realms), len(world.fallen_realms)
    index = codes.copy()
    is_fallen = (codes <= FALLEN_OWNER_BASE) & (codes > PREDECESSOR_OWNER_BASE)
    is_predecessor = codes <= PREDECESSOR_OWNER_BASE
    index[is_fallen] = realms + (FALLEN_OWNER_BASE - codes[is_fallen])
    index[is_predecessor] = realms + fallen + (PREDECESSOR_OWNER_BASE - codes[is_predecessor])
    return index


Layer = Callable[[LayerContext, CellGrid], None]

LAYERS: Registry[Layer] = Registry("render_layer")

# The layers whose every cell depends only on its world position (and its neighbours within one cell), never on where
# the grid's edges or the camera are, nor on anything that changes while the explorer runs except the overlay. The
# render cache keeps their output (see ``render.cache``); a new layer that keeps this rule can be added here.
CACHEABLE: frozenset[str] = frozenset({"terrain", "relief", "tint", "water", "clutter", "borders", "roads", "sites"})


def build_grid(
    world: World,
    config: Config,
    view: View,
    sampler: Sampler,
    overlay: Optional[Overlay] = None,
    ascii_only: bool = False,
    color: bool = True,
    labels: str = "all",
    floor: int = 0,
    seen: Optional[Seen] = None,
    moment: Optional[tuple[int, int]] = None,
) -> CellGrid:
    """Draw ``view`` of ``world`` through ``sampler`` and return the finished grid."""
    # resolve first so a typo fails before any work
    layers = [LAYERS.get(name) for name in view.layers_for(sampler.detailed)]
    context = LayerContext(
        world,
        config,
        view,
        sampler,
        overlay,
        ascii_only,
        color,
        labels,
        floor,
        seen if seen is not None else Seen(),
        moment,
    )
    grid = CellGrid(sampler.rows, sampler.cols)
    for layer in layers:
        layer(context, grid)
    return grid


from . import (  # noqa: E402,F401  (registers the built-in layers)
    borders,
    clutter,
    compass,
    markers,
    names,
    relief,
    roads,
    sites,
    terrain,
    tint,
    water,
)
