"""Sparse world objects that do not belong in a per-tile array.

POIs, regions, realms, rivers, lakes and geographic features are few in number but rich in attributes, so they
live in plain dataclasses held in lists on the :class:`~biomegen.world.world.World`. Tiles reference them by index
(e.g. ``world.poi_index[y, x]`` -> ``world.pois[i]``; ``world.region_id[y, x]`` -> ``world.regions[i]``;
``world.realm_id[y, x]`` -> ``world.realms[i]``) and the objects reference back via coordinates. Keeping the heavy
attributes here keeps the per-tile arrays small and cache-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

REALM_KINDS: Tuple[str, ...] = ("major", "city_state", "tribal")
RELATION_KINDS: Tuple[str, ...] = ("war", "rivalry", "alliance", "trade")


@dataclass
class POI:
    """A point of interest (village, town, city, capital, tower, dungeon, ruin, camp, boat, ...).

    Placement fills the location, kind, region and floors; the plan of each floor is generated lazily from
    ``interior_seed`` (see :mod:`biomegen.sites`) and never stored here.
    """

    kind: str  # "capital", "city", "town", "village", "tower", "dungeon", ...
    x: int  # anchor cell on the biome map
    y: int
    interior_seed: int  # per-POI seed minted at placement; deterministic lazy interiors
    name: str = ""
    civilized: bool = False  # towns/villages/cities are "civilized"; towers/dungeons/etc. are not
    region_id: int = -1
    realm_id: int = -1  # the realm holding the anchor cell (-1 = wild); set by the realms stage
    floor_count: int = 1  # >1 for towers (above ground) and dungeons (below ground)
    lowest_floor: int = 0  # 0 for ground-level; negative for dungeons going underground
    pop: int = 0  # population (settlements only)
    tags: Tuple[str, ...] = ()  # site traits, e.g. "port", "river"
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
class Realm:
    """A political power: a major realm, a city-state or a tribal land.

    ``seat_poi`` indexes ``World.pois`` (-1 for a tribe with no settlement). ``liege`` is the realm id of the
    overlord (-1 when independent); ``vassals`` lists the realms that swore fealty to this one. Names, ruler and
    culture are filled by the naming stage; ``color`` by the diplomacy stage.
    """

    id: int  # index into World.realms
    kind: str  # "major" | "city_state" | "tribal"
    seat_poi: int = -1
    name: str = ""
    short: str = ""
    ruler: str = ""
    culture: str = ""
    area_km2: float = 0.0
    pop: int = 0
    dominant_biome: int = 0  # the Biome (int) covering most of the realm's cells
    highland: bool = False  # more than half of the realm's cells have relief (hills or higher)
    liege: int = -1
    vassals: List[int] = field(default_factory=list)
    color: Tuple[int, int, int] = (0, 0, 0)


@dataclass
class Relation:
    """A diplomatic tie between two independent powers (realm ids ``a`` < ``b``).

    ``why`` is the reason text. Only a war has an ``attacker`` (a or b) and a ``claim_poi`` (index into
    ``World.pois``, -1 if none); ``border_km`` is the length of the shared border (0 across the sea).
    """

    a: int
    b: int
    kind: str  # "war" | "rivalry" | "alliance" | "trade"
    border_km: float = 0.0
    why: str = ""
    attacker: int = -1
    claim_poi: int = -1


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


@dataclass
class GeoFeature:
    """A named physical feature: a landmass, mountain range, sea, lake, river or peak.

    ``ref`` points into the matching per-kind data: the ``landmass_id`` value for a landmass, the index
    into ``World.lakes`` / ``World.rivers`` for a lake or river, and -1 otherwise. ``anchor`` is the
    cell a label or gazetteer entry refers to (a summit, a sea's centre, a river's mouth).
    """

    id: int  # index into World.features
    kind: str  # "landmass" | "range" | "sea" | "lake" | "river" | "peak"
    anchor: Tuple[int, int]
    ref: int = -1
    name: str = ""
    cells: List[Tuple[int, int]] = field(default_factory=list)  # area features only (landmass, range, lake)
    area_km2: float = 0.0
    length_km: float = 0.0  # rivers
    elevation_m: float = 0.0  # summit height (peak, range, landmass) or greatest depth below sea (sea, < 0)
    summit: int = -1  # feature id of the highest peak (landmass, range)
    into: int = -1  # rivers: feature id of the lake or sea at the mouth (-1 if none)
