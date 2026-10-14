"""The terrain a site plan is laid out on, and where roads reach it.

The patch is read through the same detail sampler the renderer uses (:mod:`biomegen.sampling`), over the site window,
so a plan agrees exactly with the land, rivers and shore the renderer draws around it. It is cropped to the extent box:
the cells a layout may build on.

Roads are not stored on the site either. The road bed over the box (:func:`biomegen.sampling.roads.road_bed`, the same
raster the renderer draws) says which cells are road, so a plan builds round and onto the road that arrives. A **gate**
is where a run of road cells meets the extent's edge: what makes a door, a street or a wall opening face the road.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config.model import Config
from ..sampling.detail import SCALE_SITE, DetailSampler
from ..sampling.roads import road_bed
from ..sampling.terrain import land_mask, river_mask, water_biomes
from ..world.entities import POI
from ..world.world import World
from .geometry import SiteGeometry


@dataclass(frozen=True)
class Gate:
    """A road's arrival point on the extent's edge, in box cells.

    Attributes:
        col: Column of the gate cell on the box perimeter.
        row: Row of the gate cell on the box perimeter.
        dx: Outward step across the edge, ``-1``, ``0`` or ``1``.
        dy: Outward step down across the edge.
    """

    col: int
    row: int
    dx: int
    dy: int


@dataclass(frozen=True)
class SitePatch:
    """The terrain under the extent, in box cells (``rows x cols``).

    Attributes:
        dry: Dry ground inside the world: where a structure can stand.
        water: Water of any kind (sea, lake or river): where a bridge or a hull goes.
        elevation_m: Height above sea level, bilinear.
        road: Cells on the road bed (dry or over water), as the renderer draws it.
        rail: Cells in the railing band beside the bed (a bridge's railings where it lies over water).
        gates: Where roads arrive, nearest the middle first.
    """

    dry: np.ndarray
    water: np.ndarray
    elevation_m: np.ndarray
    road: np.ndarray
    rail: np.ndarray
    gates: tuple[Gate, ...]

    @property
    def rows(self) -> int:
        return int(self.dry.shape[0])

    @property
    def cols(self) -> int:
        return int(self.dry.shape[1])


def window_sampler(
    world: World,
    config: Config,
    geometry: SiteGeometry,
    origin: tuple[int, int] = (0, 0),
    shape: tuple[int, int] | None = None,
) -> DetailSampler:
    """Return the detail sampler over ``geometry``'s window (one sampler cell per plan cell).

    ``origin`` and ``shape`` (``(col, row)`` and ``(rows, cols)``) restrict it to a rectangle of the window's cells.
    """
    return DetailSampler(
        world,
        config,
        geometry.cell_w,
        geometry.cell_h,
        geometry.cam_x,
        geometry.cam_y,
        geometry.tiles_w,
        geometry.tiles_h,
        SCALE_SITE,
        origin,
        shape,
    )


def _runs(line: np.ndarray) -> list[tuple[int, int]]:
    """Return the ``(first, last)`` index of each run of true cells in a one-dimensional mask."""
    padded = np.concatenate(([False], line, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [(int(first), int(last) - 1) for first, last in zip(edges[::2], edges[1::2], strict=True)]


def _find_gates(road: np.ndarray, max_gates: int) -> tuple[Gate, ...]:
    """Return up to ``max_gates`` gates: the middle of each road run on the box's edge, nearest the middle first."""
    rows, cols = road.shape
    found: list[Gate] = []
    for col0, col1 in _runs(road[0]):
        found.append(Gate((col0 + col1) // 2, 0, 0, -1))
    for col0, col1 in _runs(road[rows - 1]):
        found.append(Gate((col0 + col1) // 2, rows - 1, 0, 1))
    for row0, row1 in _runs(road[1 : rows - 1, 0]):
        found.append(Gate(0, (row0 + row1) // 2 + 1, -1, 0))
    for row0, row1 in _runs(road[1 : rows - 1, cols - 1]):
        found.append(Gate(cols - 1, (row0 + row1) // 2 + 1, 1, 0))
    middle = ((cols - 1) / 2.0, (rows - 1) / 2.0)
    found.sort(key=lambda g: (((g.col - middle[0]) / 2.0) ** 2 + (g.row - middle[1]) ** 2, g.row, g.col))
    return tuple(found[:max_gates])


def read_patch(poi: POI, geometry: SiteGeometry, world: World, config: Config) -> SitePatch:
    """Read the terrain and the road bed under ``poi``'s extent and find the gates where roads reach it."""
    sampler = window_sampler(world, config, geometry)
    water_biome = water_biomes(config)
    land = land_mask(sampler, sampler.biome(), water_biome)
    river = river_mask(sampler, world, land, water_biome)
    col0, row0, col1, row1 = geometry.box
    box = (slice(row0, row1), slice(col0, col1))
    dry = (land & ~river)[box]
    water = (sampler.inside & ~(land & ~river))[box]
    elevation = sampler.bilinear(world.elevation_m)[box].astype(np.float32)
    found = road_bed(sampler, world, config)
    road = found.bed[box] if found is not None else np.zeros(dry.shape, dtype=bool)
    rail = found.rail[box] if found is not None else np.zeros(dry.shape, dtype=bool)
    return SitePatch(dry, water, elevation, road, rail, _find_gates(road, int(config.get("sites.max_gates"))))
