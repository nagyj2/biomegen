"""Sparse world objects that do not belong in a per-tile array.

POIs, regions, rivers and lakes are few in number but rich in attributes, so they live in plain
dataclasses held in lists on the :class:`~biomegen.world.world.World`. Tiles reference them by index
(e.g. ``world.poi_index[y, x]`` -> ``world.pois[i]``; ``world.region_id[y, x]`` -> ``world.regions[i]``)
and the objects reference back via coordinates. Keeping the heavy attributes here keeps the per-tile
arrays small and cache-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class POI:
    """A point of interest (village, town, city, tower, dungeon, ruin, camp, boat, ...).

    Placement (Phase 4) fills the location/kind/region; the interiors stage (Phase 5) fills the cheap
    metadata (``floor_count``, ``footprint``, ``entrance``) while the actual interior grids are
    generated lazily from ``interior_seed`` and never stored here.
    """

    kind: str  # e.g. "village", "town", "city", "tower", "dungeon", ...
    x: int  # anchor cell on the biome map
    y: int
    interior_seed: int  # per-POI seed minted at placement; deterministic lazy interiors
    name: str = ""
    civilized: bool = False  # towns/villages/cities are "civilized"; towers/dungeons/etc. are not
    region_id: int = -1
    floor_count: int = 1  # >1 for towers (above ground) and dungeons (below ground)
    lowest_floor: int = 0  # 0 for ground-level; negative for dungeons going underground
    footprint: Tuple[int, int] = (0, 0)  # interior footprint in world tiles (w, h), centred on anchor
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # footprint extent in world tiles (x0,y0,x1,y1), clamped
    entrance: Tuple[int, int] = (0, 0)  # door coordinate roads should connect to
    extra: dict = field(default_factory=dict)  # kind-specific data (e.g. boat cargo type)


@dataclass
class Region:
    """A contiguous group of similar-biome tiles, named and given lore.

    ``base_color`` is the per-region colour (a biome base hue perturbed deterministically by region
    id) used for SVG/PNG export and the curses ``init_color`` attempt.
    """

    id: int
    biome_class: int  # the representative Biome (int) of this region
    size: int = 0  # number of tiles
    base_color: Tuple[int, int, int] = (0, 0, 0)  # RGB 0-255
    name: str = ""
    lore: List[str] = field(default_factory=list)  # 1-4 generated lore sentences
    poi_indices: List[int] = field(default_factory=list)
    bbox: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (x0, y0, x1, y1) inclusive
    centroid: Tuple[float, float] = (0.0, 0.0)


@dataclass
class River:
    """A traced freshwater channel from a highland source toward the sea."""

    id: int
    path: List[Tuple[int, int]] = field(default_factory=list)  # ordered upstream→downstream cells
    name: str = ""
    length: int = 0  # number of channel cells in ``path``
    mouth: Optional[Tuple[int, int]] = None  # where it meets ocean/lake (None if it dries out inland)
    source: Tuple[int, int] = (0, 0)  # first (most upstream) cell of ``path``
    length_km: float = 0.0  # length along ``path`` in km (aspect-aware step lengths)


@dataclass
class Lake:
    """A standing water body. ``salt`` is True only if connected to the open sea."""

    id: int
    tiles: List[Tuple[int, int]] = field(default_factory=list)
    name: str = ""
    area: int = 0  # number of cells
    salt: bool = False
    area_km2: float = 0.0
    surface_m: float = 0.0  # height of the flat water surface (the depression's spill level)
