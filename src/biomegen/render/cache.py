"""The render cache: explorer frames drawn over terrain that is worked out once.

Most of a frame is terrain. The layers in :data:`~biomegen.render.layers.CACHEABLE` (terrain up to sites) paint each
cell from its world position alone, so at the detail scales (zoom, local, site) the cache keeps their output in
**chunks**: fixed rectangles of ``render.cache.chunk_cols x chunk_rows`` cells of the scale's whole-world grid. A frame
after a pan reuses every chunk still on screen and draws only the ground that came into view; the rest of the view's
layers (markers, labels, compass, and later anything that moves over the terrain) run on top of it every frame.
Missing chunks are drawn together in one pass over their bounding rectangle.

A chunk is drawn with a one-cell halo, so a layer comparing a cell with its neighbours (``borders``) sees the real
neighbour across a chunk edge: a chunk holds what a draw of the whole world would hold at its cells, wherever the
camera is. At the map scales a whole frame is reused while nothing that draws it changes (the fit map does not move
with the cursor).

What invalidates: a different world or config resets the cache; an :class:`~biomegen.world.overlay.Overlay` edit (its
``revision``) drops everything drawn; :meth:`RenderCache.invalidate` drops what lies in a box of tiles, for a caller
that changes the world's surface some other way (a future simulation). At most ``render.cache.max_cells`` cells are
kept, the least recently shown chunks dropped first.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..config.model import Config
from ..sampling.detail import SCALE_SITE, DetailSampler
from ..sampling.sampler import Sampler
from ..world.overlay import Overlay
from ..world.world import World
from .grid import CellGrid
from .layers import CACHEABLE, LAYERS, LayerContext, Seen, build_grid
from .views import View

_HALO = 1  # cells drawn round a chunk and thrown away: the widest neighbour stencil of a cacheable layer
_GRID_ARRAYS = ("glyph", "fg", "bg", "bold")


@dataclass(frozen=True)
class _Surface:
    """One whole-world grid of cells that chunks are cut from: a view at one scale and cell size.

    ``cam_x`` / ``cam_y`` is the tile at the grid's first cell: the world origin at the zoom and local scales, the site
    window's corner at the site scale (so a site's cells are read exactly as its plan was laid out).
    """

    view: str
    scale: str
    cell_w: int
    cell_h: int
    cam_x: int
    cam_y: int
    tiles_w: int
    tiles_h: int
    ascii_only: bool
    color: bool
    floor: int


@dataclass
class _Chunk:
    """The cacheable layers' output over one chunk, and what the legend needs from it."""

    glyph: np.ndarray
    fg: np.ndarray
    bg: np.ndarray
    bold: np.ndarray
    biome: np.ndarray  # biome per cell (uint8), so later layers and the legend need no second biome lookup
    cell_map: Optional[np.ndarray]  # plan cell per cell (int16, -1 none) where a site was drawn, else None

    @property
    def cells(self) -> int:
        return int(self.glyph.size)


@dataclass
class _MapFrame:
    grid: CellGrid
    seen: Seen = field(default_factory=Seen)


def split_layers(names: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split a layer list into its longest cacheable prefix and the layers that must run every frame."""
    count = 0
    while count < len(names) and names[count] in CACHEABLE:
        count += 1
    return names[:count], names[count:]


def _copy_grid(grid: CellGrid) -> CellGrid:
    copy = CellGrid(grid.rows, grid.cols)
    for name in _GRID_ARRAYS:
        getattr(copy, name)[...] = getattr(grid, name)
    return copy


def _copy_seen(seen: Seen) -> Seen:
    cell_map = None if seen.cell_map is None else seen.cell_map.copy()
    return Seen(set(seen.biomes), set(seen.cells), cell_map)


def _merge_seen(target: Seen, source: Seen) -> None:
    target.biomes.update(source.biomes)
    target.cells.update(source.cells)
    target.cell_map = None if source.cell_map is None else source.cell_map.copy()


class RenderCache:
    """Draws explorer frames like :func:`~biomegen.render.layers.build_grid`, reusing what earlier frames drew.

    One cache serves one world and config; the explorer keeps one for its whole run.
    """

    def __init__(self, config: Config) -> None:
        cfg = config.get("render.cache")
        self.chunk_cols = max(1, int(cfg["chunk_cols"]))
        self.chunk_rows = max(1, int(cfg["chunk_rows"]))
        self.max_cells = max(0, int(cfg["max_cells"]))
        self.map_frames = max(0, int(cfg["map_frames"]))
        self._chunks: OrderedDict[tuple[_Surface, int, int], _Chunk] = OrderedDict()
        self._maps: OrderedDict[tuple, _MapFrame] = OrderedDict()
        self._cells = 0
        self._world: Optional[World] = None
        self._config: Optional[Config] = None
        self._overlay: Optional[Overlay] = None
        self._revision = -1

    @property
    def cells(self) -> int:
        """Cells held in chunks."""
        return self._cells

    def invalidate(self, box: Optional[tuple[int, int, int, int]] = None) -> None:
        """Forget what was drawn: everything, or only what the tiles ``(x0, y0, x1, y1)`` (exclusive ends) could change.

        A chunk is dropped when its cells read anywhere near the box: the biome blend's warp, a bilinear read and the
        road bed's reach all look a little past a cell's own tile.
        """
        self._maps.clear()
        if box is None:
            self._chunks.clear()
            self._cells = 0
            return
        reach = self._read_reach()
        x0, y0, x1, y1 = box
        for key in [key for key in self._chunks if self._touches(key, (x0, y0, x1, y1), reach)]:
            self._cells -= self._chunks.pop(key).cells

    def draw(
        self,
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
    ) -> CellGrid:
        """Draw ``view`` through ``sampler`` exactly as ``build_grid`` would, from cached chunks where they exist."""
        seen = seen if seen is not None else Seen()
        self._check(world, config, overlay)
        if isinstance(sampler, DetailSampler):
            return self._draw_detail(world, config, view, sampler, overlay, ascii_only, color, labels, floor, seen)
        return self._draw_map(world, config, view, sampler, overlay, ascii_only, color, labels, floor, seen)

    # ------------------------------------------------------------------ validity

    def _check(self, world: World, config: Config, overlay: Optional[Overlay]) -> None:
        """Reset for a new world or config, and drop what an overlay edit could have changed."""
        if world is not self._world or config is not self._config:
            self.invalidate()
            self._world, self._config = world, config
        revision = overlay.revision if overlay is not None else -1
        if overlay is not self._overlay or revision != self._revision:
            self.invalidate()
            self._overlay, self._revision = overlay, revision

    def _read_reach(self) -> int:
        """Tiles past its own that a cell's colour can depend on (warp, road bed, bilinear and shade reads)."""
        assert self._config is not None
        get = self._config.get
        spread = (
            float(get("render.blend_strength")) + float(get("render.road_warp")) + float(get("render.road_meander"))
        )
        return math.ceil(max(spread, 0.0)) + 2

    def _touches(self, key: tuple[_Surface, int, int], box: tuple[int, int, int, int], reach: int) -> bool:
        surface, chunk_col, chunk_row = key
        col0 = chunk_col * self.chunk_cols - _HALO
        row0 = chunk_row * self.chunk_rows - _HALO
        left = surface.cam_x + col0 / surface.cell_w - reach
        right = surface.cam_x + (col0 + self.chunk_cols + 2 * _HALO) / surface.cell_w + reach
        top = surface.cam_y + row0 / surface.cell_h - reach
        bottom = surface.cam_y + (row0 + self.chunk_rows + 2 * _HALO) / surface.cell_h + reach
        x0, y0, x1, y1 = box
        return left < x1 and right > x0 and top < y1 and bottom > y0

    # ------------------------------------------------------------------ map scales: whole frames

    def _draw_map(
        self,
        world: World,
        config: Config,
        view: View,
        sampler: Sampler,
        overlay: Optional[Overlay],
        ascii_only: bool,
        color: bool,
        labels: str,
        floor: int,
        seen: Seen,
    ) -> CellGrid:
        signature = sampler.signature
        if signature is None or self.map_frames == 0:
            return build_grid(world, config, view, sampler, overlay, ascii_only, color, labels, floor, seen)
        key = (view.name, signature, ascii_only, color, labels, floor)
        frame = self._maps.get(key)
        if frame is None:
            drawn = Seen()
            grid = build_grid(world, config, view, sampler, overlay, ascii_only, color, labels, floor, drawn)
            frame = _MapFrame(grid, drawn)
            self._maps[key] = frame
            while len(self._maps) > self.map_frames:
                self._maps.popitem(last=False)
        self._maps.move_to_end(key)
        _merge_seen(seen, frame.seen)
        return _copy_grid(frame.grid)

    # ------------------------------------------------------------------ detail scales: chunks

    def _surface(
        self, world: World, view: View, sampler: DetailSampler, ascii_only: bool, color: bool, floor: int
    ) -> _Surface:
        if sampler.scale == SCALE_SITE:
            cam_x, cam_y, tiles_w, tiles_h, floor_key = (
                sampler.cam_x,
                sampler.cam_y,
                sampler.tiles_w,
                sampler.tiles_h,
                floor,
            )
        else:  # zoom and local read the same positions wherever the camera is: one grid from the world's corner
            cam_x, cam_y, tiles_w, tiles_h, floor_key = 0, 0, world.width, world.height, 0
        return _Surface(
            view.name,
            sampler.scale,
            sampler.cell_w,
            sampler.cell_h,
            cam_x,
            cam_y,
            tiles_w,
            tiles_h,
            ascii_only,
            color,
            floor_key,
        )

    def _draw_detail(
        self,
        world: World,
        config: Config,
        view: View,
        sampler: DetailSampler,
        overlay: Optional[Overlay],
        ascii_only: bool,
        color: bool,
        labels: str,
        floor: int,
        seen: Seen,
    ) -> CellGrid:
        cached, per_frame = split_layers(view.layers_for(True))
        if not cached:
            return build_grid(world, config, view, sampler, overlay, ascii_only, color, labels, floor, seen)
        layers = [LAYERS.get(name) for name in per_frame]  # resolve first so a typo fails before any work
        surface = self._surface(world, view, sampler, ascii_only, color, floor)
        # The sampler's cells within the surface's grid.
        col0 = (sampler.cam_x - surface.cam_x) * sampler.cell_w + sampler.col0
        row0 = (sampler.cam_y - surface.cam_y) * sampler.cell_h + sampler.row0
        rect = (col0, row0, sampler.cols, sampler.rows)
        span = self._chunk_span(rect)
        missing = [(c, r) for r in span[1] for c in span[0] if (surface, c, r) not in self._chunks]
        if missing:
            self._build(world, config, view, surface, cached, overlay, ascii_only, color, labels, floor, missing)
        grid, biome, cell_map = self._assemble(surface, rect, span)
        self._evict()

        if "terrain" in cached:
            seen.biomes.update(np.unique(biome[sampler.inside]).tolist())
        if cell_map is not None:
            drawn = cell_map[cell_map >= 0]
            seen.cells.update(np.unique(drawn).tolist())
            seen.cell_map = cell_map
        context = LayerContext(world, config, view, sampler, overlay, ascii_only, color, labels, floor, seen)
        context.__dict__["biome"] = biome  # the cached biome stands in for the sampler's lookup (a cached_property)
        for layer in layers:
            layer(context, grid)
        return grid

    def _chunk_span(self, rect: tuple[int, int, int, int]) -> tuple[range, range]:
        """Return the chunk columns and rows that a ``(col0, row0, cols, rows)`` rectangle of cells overlaps."""
        col0, row0, cols, rows = rect
        return (
            range(col0 // self.chunk_cols, (col0 + cols - 1) // self.chunk_cols + 1),
            range(row0 // self.chunk_rows, (row0 + rows - 1) // self.chunk_rows + 1),
        )

    def _build(
        self,
        world: World,
        config: Config,
        view: View,
        surface: _Surface,
        names: tuple[str, ...],
        overlay: Optional[Overlay],
        ascii_only: bool,
        color: bool,
        labels: str,
        floor: int,
        missing: list[tuple[int, int]],
    ) -> None:
        """Draw the cacheable layers once over the box round the ``missing`` chunks (with the halo) and keep them."""
        first_col = min(col for col, _ in missing)
        first_row = min(row for _, row in missing)
        last_col = max(col for col, _ in missing)
        last_row = max(row for _, row in missing)
        origin = (first_col * self.chunk_cols - _HALO, first_row * self.chunk_rows - _HALO)
        shape = (
            (last_row - first_row + 1) * self.chunk_rows + 2 * _HALO,
            (last_col - first_col + 1) * self.chunk_cols + 2 * _HALO,
        )
        sampler = DetailSampler(
            world,
            config,
            surface.cell_w,
            surface.cell_h,
            surface.cam_x,
            surface.cam_y,
            surface.tiles_w,
            surface.tiles_h,
            surface.scale,
            origin,
            shape,
        )
        context = LayerContext(world, config, view, sampler, overlay, ascii_only, color, labels, floor, Seen())
        grid = CellGrid(sampler.rows, sampler.cols)
        for name in names:
            LAYERS.get(name)(context, grid)
        biome = context.biome.astype(np.uint8)
        cell_map = context.seen.cell_map
        for col, row in missing:
            top = _HALO + (row - first_row) * self.chunk_rows
            left = _HALO + (col - first_col) * self.chunk_cols
            cut = (slice(top, top + self.chunk_rows), slice(left, left + self.chunk_cols))
            plan = None
            if cell_map is not None and (cell_map[cut] >= 0).any():
                plan = cell_map[cut].copy()
            chunk = _Chunk(
                grid.glyph[cut].copy(),
                grid.fg[cut].copy(),
                grid.bg[cut].copy(),
                grid.bold[cut].copy(),
                biome[cut].copy(),
                plan,
            )
            self._chunks[(surface, col, row)] = chunk
            self._cells += chunk.cells

    def _assemble(
        self, surface: _Surface, rect: tuple[int, int, int, int], span: tuple[range, range]
    ) -> tuple[CellGrid, np.ndarray, Optional[np.ndarray]]:
        """Copy the chunks' cells inside ``rect`` into a grid of the rectangle's size."""
        col0, row0, cols, rows = rect
        grid = CellGrid(rows, cols)
        biome = np.zeros((rows, cols), dtype=np.uint8)
        cell_map: Optional[np.ndarray] = None
        for row in span[1]:
            for col in span[0]:
                key = (surface, col, row)
                chunk = self._chunks[key]
                self._chunks.move_to_end(key)
                left, top = col * self.chunk_cols, row * self.chunk_rows
                x0, x1 = max(col0, left), min(col0 + cols, left + self.chunk_cols)
                y0, y1 = max(row0, top), min(row0 + rows, top + self.chunk_rows)
                target = (slice(y0 - row0, y1 - row0), slice(x0 - col0, x1 - col0))
                source = (slice(y0 - top, y1 - top), slice(x0 - left, x1 - left))
                for name in _GRID_ARRAYS:
                    getattr(grid, name)[target] = getattr(chunk, name)[source]
                biome[target] = chunk.biome[source]
                if chunk.cell_map is not None:
                    if cell_map is None:
                        cell_map = np.full((rows, cols), -1, dtype=np.int16)
                    cell_map[target] = chunk.cell_map[source]
        if cell_map is not None and not (cell_map >= 0).any():
            cell_map = None
        return grid, biome, cell_map

    def _evict(self) -> None:
        """Drop the least recently shown chunks until the cache holds at most ``max_cells`` cells."""
        while self._cells > self.max_cells and self._chunks:
            _key, chunk = self._chunks.popitem(last=False)
            self._cells -= chunk.cells
