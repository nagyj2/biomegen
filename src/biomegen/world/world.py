"""The central in-memory world model: an immutable struct-of-arrays.

The pipeline fills a single :class:`World`; renderers and exporters read it. Per-tile data is stored
as parallel **numpy 2-D arrays** indexed ``[y, x]`` (row-major), which is memory-efficient, fast to
operate on in bulk, and trivial to fingerprint for the golden-world reproducibility test. Sparse
objects (POIs, regions, realms, rivers, lakes) live in lists in :mod:`biomegen.world.entities`.

"Immutable" here is a contract, not enforced object freezing: once :func:`biomegen.pipeline.generate`
returns, generation never writes the arrays again. All *runtime* changes (gameplay edits to
structures, overlays) go through a separate :class:`~biomegen.world.overlay.Overlay` and are
composited at read time. The base biome in particular is never mutated.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..util.units import GridScale, grid_scale
from .entities import POI, GeoFeature, Lake, Realm, Region, Relation, River
from .tile import Biome, Relief, TileView, WaterType


class World:
    """Struct-of-arrays container for one generated island.

    Field arrays (all shape ``(height, width)``):

    ====================  =========  =====================================================
    field                 dtype      meaning
    ====================  =========  =====================================================
    ``elevation_m``       float64    height above sea level in metres (negative = sea depth)
    ``temperature_c``     float64    mean annual temperature in °C
    ``rain_mm``           float64    annual rainfall in mm
    ``moisture``          float64    normalised moisture in [0, 1] (wet=1)
    ``biome``             uint8      a :class:`Biome` value
    ``relief``            uint8      a :class:`Relief` value (orthogonal to the biome)
    ``landmass_id``       int32      connected landmass index (-1 = water or unassigned)
    ``region_id``         int32      index into ``regions`` (-1 = unassigned / ocean)
    ``realm_id``          int16      index into ``realms`` (-1 = wild, unclaimed or water)
    ``front``             bool       a war border cell between two warring powers
    ``water_type``        uint8      a :class:`WaterType` value
    ``road``              uint8      0/1 flag: a road passes through this tile
    ``road_tier``         uint8      0=none, 1=trunk (MST backbone), 2=spur (offshoot to trunk)
    ``dist_to_ocean``     float32    Euclidean distance (km) to the nearest ocean tile
    ``flow_accum``        float64    hydrological flow accumulation (drainage area proxy)
    ``poi_index``         int32      index into ``pois`` (-1 = none)
    ====================  =========  =====================================================

    Scale metadata (not per-tile, so not part of :meth:`fingerprint`): ``scale`` is the
    :class:`~biomegen.util.units.GridScale` that places the grid in km and on the globe;
    ``km_per_col``, ``km_per_row``, ``lat_top`` and ``lon_left`` read through to it.
    """

    #: Names of the per-tile arrays, in a fixed order. Used by :meth:`fingerprint` so the golden test
    #: hashes every field deterministically, and by any code that wants to iterate fields generically.
    FIELDS: tuple[str, ...] = (
        "elevation_m",
        "temperature_c",
        "rain_mm",
        "moisture",
        "biome",
        "relief",
        "landmass_id",
        "region_id",
        "realm_id",
        "front",
        "water_type",
        "road",
        "road_tier",
        "dist_to_ocean",
        "flow_accum",
        "poi_index",
    )

    def __init__(self, width: int, height: int, seed: int, scale: Optional[GridScale] = None) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"world dimensions must be positive, got {width}x{height}")
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        # Without an explicit scale a bare World has 1 km square cells centred on 0N 0E.
        self.scale: GridScale = scale or grid_scale(self.width, self.height, (self.width, self.height), 0.0, 0.0)
        self.master_seed: int = int(seed)  # original (pre-regen) master seed, for echoing / naming continuity
        shape = (self.height, self.width)

        # Continuous scalar fields.
        self.elevation_m = np.zeros(shape, dtype=np.float64)
        self.temperature_c = np.zeros(shape, dtype=np.float64)
        self.rain_mm = np.zeros(shape, dtype=np.float64)
        self.moisture = np.zeros(shape, dtype=np.float64)

        # Discrete / classified fields.
        self.biome = np.full(shape, int(Biome.DEEP), dtype=np.uint8)
        self.relief = np.full(shape, int(Relief.NONE), dtype=np.uint8)
        self.landmass_id = np.full(shape, -1, dtype=np.int32)
        self.region_id = np.full(shape, -1, dtype=np.int32)
        self.realm_id = np.full(shape, -1, dtype=np.int16)
        self.front = np.zeros(shape, dtype=bool)
        self.water_type = np.full(shape, int(WaterType.NONE), dtype=np.uint8)
        self.road = np.zeros(shape, dtype=np.uint8)
        self.road_tier = np.zeros(shape, dtype=np.uint8)

        # Derived helper fields.
        self.dist_to_ocean = np.zeros(shape, dtype=np.float32)
        self.flow_accum = np.zeros(shape, dtype=np.float64)
        self.poi_index = np.full(shape, -1, dtype=np.int32)

        # Sparse entities (filled by later stages).
        self.pois: list[POI] = []
        self.regions: list[Region] = []
        self.realms: list[Realm] = []  # filled by the realms stage
        self.relations: list[Relation] = []  # filled by the diplomacy stage
        self.rivers: list[River] = []
        self.lakes: list[Lake] = []
        self.features: list[GeoFeature] = []  # filled by the geography stage

        # Terrain style row name (filled by the terrain stage; metadata, not hashed).
        self.terrain_style: str = ""

        # Names (filled by the naming stage).
        self.island_name: str = ""

    # ------------------------------------------------------------------ scale metadata
    @property
    def km_per_col(self) -> float:
        """Width of one cell in km."""
        return self.scale.km_per_col

    @property
    def km_per_row(self) -> float:
        """Height of one cell in km."""
        return self.scale.km_per_row

    @property
    def lat_top(self) -> float:
        """Latitude of the map's top edge in degrees."""
        return self.scale.lat_top

    @property
    def lon_left(self) -> float:
        """Longitude of the map's left edge in degrees."""
        return self.scale.lon_left

    # ------------------------------------------------------------------ access helpers
    def in_bounds(self, x: int, y: int) -> bool:
        """Return whether ``(x, y)`` lies within the map. The single bounds check all callers use."""
        return 0 <= x < self.width and 0 <= y < self.height

    def view(self, x: int, y: int) -> TileView:
        """Gather every field at ``(x, y)`` into an immutable :class:`TileView` for display.

        This reads the *base* world only; the render layer overlays any runtime edits on top.
        """
        return TileView(
            x=x,
            y=y,
            elevation_m=float(self.elevation_m[y, x]),
            temperature_c=float(self.temperature_c[y, x]),
            rain_mm=float(self.rain_mm[y, x]),
            moisture=float(self.moisture[y, x]),
            biome=Biome(int(self.biome[y, x])),
            relief=Relief(int(self.relief[y, x])),
            landmass_id=int(self.landmass_id[y, x]),
            water_type=WaterType(int(self.water_type[y, x])),
            region_id=int(self.region_id[y, x]),
            realm_id=int(self.realm_id[y, x]),
            road=bool(self.road[y, x]),
            road_tier=int(self.road_tier[y, x]),
            dist_to_ocean=float(self.dist_to_ocean[y, x]),
            flow_accum=float(self.flow_accum[y, x]),
            poi_index=int(self.poi_index[y, x]),
        )

    def poi_at(self, x: int, y: int) -> Optional[POI]:
        """Return the :class:`~biomegen.world.entities.POI` whose footprint covers ``(x, y)``, or None."""
        i = int(self.poi_index[y, x])
        return self.pois[i] if 0 <= i < len(self.pois) else None

    def region_at(self, x: int, y: int) -> Optional[Region]:
        """Return the :class:`~biomegen.world.entities.Region` at ``(x, y)``, or None."""
        i = int(self.region_id[y, x])
        return self.regions[i] if 0 <= i < len(self.regions) else None

    def realm_at(self, x: int, y: int) -> Optional[Realm]:
        """Return the :class:`~biomegen.world.entities.Realm` at ``(x, y)``, or None for wild land and water."""
        i = int(self.realm_id[y, x])
        return self.realms[i] if 0 <= i < len(self.realms) else None

    def top_realm(self, index: int) -> int:
        """Return the id of the independent power at the top of realm ``index``'s chain of lieges."""
        while self.realms[index].liege >= 0:
            index = self.realms[index].liege
        return index

    # ------------------------------------------------------------------ reproducibility
    def fingerprint(self) -> str:
        """Return a stable hex digest of all per-tile arrays - the golden-world test's anchor.

        Hashing every field's raw bytes (in the fixed :data:`FIELDS` order, with dtype/shape) means
        any accidental change to generation - a reordered stage, a stray ``hash()`` call, a numpy
        dtype drift - changes the digest and is caught immediately.
        """
        from ..util.rng import hash_bytes

        chunks: list[bytes] = []
        for name in self.FIELDS:
            arr = np.ascontiguousarray(getattr(self, name))
            # Include the field name, dtype and shape so structural changes also alter the hash.
            chunks.append(name.encode("utf-8"))
            chunks.append(str(arr.dtype).encode("utf-8"))
            chunks.append(str(arr.shape).encode("utf-8"))
            chunks.append(arr.tobytes())
        return hash_bytes(*chunks)
