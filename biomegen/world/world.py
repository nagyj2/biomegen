"""The central in-memory world model: an immutable struct-of-arrays.

The pipeline fills a single :class:`World`; renderers and exporters read it. Per-tile data is stored
as parallel **numpy 2-D arrays** indexed ``[y, x]`` (row-major), which is memory-efficient, fast to
operate on in bulk, and trivial to fingerprint for the golden-world reproducibility test. Sparse
objects (POIs, regions, rivers, lakes) live in lists in :mod:`biomegen.world.entities`.

"Immutable" here is a contract, not enforced object freezing: once :func:`biomegen.pipeline.generate`
returns, generation never writes the arrays again. All *runtime* changes (gameplay edits to
structures, overlays) go through a separate :class:`~biomegen.world.overlay.Overlay` and are
composited at read time. The base biome in particular is never mutated.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .entities import POI, Lake, Region, River
from .tile import Biome, TileView, WaterType


class World:
    """Struct-of-arrays container for one generated island.

    Field arrays (all shape ``(height, width)``):

    ====================  =========  =====================================================
    field                 dtype      meaning
    ====================  =========  =====================================================
    ``elevation``         float64    normalised height in [0, 1] (after falloff)
    ``temperature``       float64    normalised temperature in [0, 1] (warm=1)
    ``moisture``          float64    normalised moisture in [0, 1] (wet=1)
    ``biome``             uint8      a :class:`Biome` value
    ``region_id``         int32      index into ``regions`` (-1 = unassigned / ocean)
    ``water_type``        uint8      a :class:`WaterType` value
    ``road``              uint8      0/1 flag: a road passes through this tile
    ``road_tier``         uint8      0=none, 1=trunk (MST backbone), 2=spur (offshoot to trunk)
    ``dist_to_ocean``     float32    Euclidean distance (in tiles) to the nearest ocean tile
    ``flow_accum``        float64    hydrological flow accumulation (drainage area proxy)
    ``poi_index``         int32      index into ``pois`` (-1 = none)
    ====================  =========  =====================================================
    """

    #: Names of the per-tile arrays, in a fixed order. Used by :meth:`fingerprint` so the golden test
    #: hashes every field deterministically, and by any code that wants to iterate fields generically.
    FIELDS: tuple[str, ...] = (
        "elevation",
        "temperature",
        "moisture",
        "biome",
        "region_id",
        "water_type",
        "road",
        "road_tier",
        "dist_to_ocean",
        "flow_accum",
        "poi_index",
    )

    def __init__(self, width: int, height: int, seed: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"world dimensions must be positive, got {width}x{height}")
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        self.master_seed: int = int(seed)  # original (pre-regen) master seed, for echoing / naming continuity
        shape = (self.height, self.width)

        # Continuous scalar fields.
        self.elevation = np.zeros(shape, dtype=np.float64)
        self.temperature = np.zeros(shape, dtype=np.float64)
        self.moisture = np.zeros(shape, dtype=np.float64)

        # Discrete / classified fields.
        self.biome = np.full(shape, int(Biome.OCEAN), dtype=np.uint8)
        self.region_id = np.full(shape, -1, dtype=np.int32)
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
        self.rivers: list[River] = []
        self.lakes: list[Lake] = []

        # Names (filled by the naming stage).
        self.island_name: str = ""

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
            elevation=float(self.elevation[y, x]),
            temperature=float(self.temperature[y, x]),
            moisture=float(self.moisture[y, x]),
            biome=Biome(int(self.biome[y, x])),
            water_type=WaterType(int(self.water_type[y, x])),
            region_id=int(self.region_id[y, x]),
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
