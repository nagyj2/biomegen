"""Site plans: the layout of one floor of one POI, built lazily and cached.

``site_plan`` is a pure function of the POI, the floor, the config and the world's terrain around the anchor. Same
inputs, same plan. Plans are never stored in the world: they live in a bounded cache keyed by the world, so a fresh
world starts with none. The cached arrays are read-only; runtime edits go through
:meth:`biomegen.world.overlay.Overlay.apply_interior`.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config.model import Config
from ..world.entities import POI
from ..world.tile import Cell
from ..world.world import World
from . import boat, camp, settlement, structure  # noqa: F401  (imported for their @layout registrations)
from .cells import VOID
from .geometry import SiteGeometry, site_geometry
from .layout import LAYOUTS, SiteContext
from .patch import read_patch
from .streets import clear_roads


@dataclass(frozen=True)
class SitePlan:
    """One floor of one site.

    Attributes:
        geometry: The site's extent, window and resolution.
        floor: The floor this plan shows.
        cells: ``Cell`` values over the extent box (``box_rows x box_cols``, read-only), seen from inside; void shows
            the terrain.
        outside: The same box seen from outside (the map, zoom and local scales): buildings as roofs, walls solid.
    """

    geometry: SiteGeometry
    floor: int
    cells: np.ndarray
    outside: np.ndarray

    def window_cells(self, cells: Optional[np.ndarray] = None) -> np.ndarray:
        """Return ``cells`` (default: this plan's) embedded in a window-sized grid, void outside the extent box."""
        window = np.full((self.geometry.rows, self.geometry.cols), VOID, dtype=np.uint8)
        col0, row0, col1, row1 = self.geometry.box
        window[row0:row1, col0:col1] = self.cells if cells is None else cells
        return window


_Cache = tuple[Config, dict[tuple, Optional[SitePlan]]]
_CACHES: "weakref.WeakKeyDictionary[World, dict[int, _Cache]]" = weakref.WeakKeyDictionary()


def _cache(world: World, config: Config) -> dict[tuple, Optional[SitePlan]]:
    per_config = _CACHES.setdefault(world, {})
    entry = per_config.get(id(config))
    if entry is None or entry[0] is not config:  # an id can be reused once its config is gone
        entry = (config, {})
        per_config[id(config)] = entry
    return entry[1]


def clear_cache() -> None:
    """Drop every cached plan (tests; a rebuilt plan is identical)."""
    _CACHES.clear()


def site_plan(poi: POI, floor: int, config: Config, world: World) -> Optional[SitePlan]:
    """Return the plan of ``poi``'s ``floor`` (clamped to its floors), or None if its kind has no site or no room."""
    floor = max(poi.lowest_floor, min(int(floor), poi.lowest_floor + poi.floor_count - 1))
    cache = _cache(world, config)
    key = (poi.kind, poi.x, poi.y, poi.interior_seed, poi.pop, poi.floor_count, poi.lowest_floor, floor)
    if key in cache:
        return cache[key]
    geometry = site_geometry(poi, config)
    if geometry is None:
        cache[key] = None
        return None
    row = config.get(f"tables.sites.{poi.kind}")
    context = SiteContext(
        kind=poi.kind,
        seed=int(poi.interior_seed),
        floor=floor,
        lowest_floor=int(poi.lowest_floor),
        floor_count=int(poi.floor_count),
        patch=read_patch(poi, geometry, world, config),
        furniture={
            role: [(Cell[name.upper()], float(weight)) for name, weight in sorted(weights.items())]
            for role, weights in sorted(config.get(f"tables.furniture.{row['furniture']}").items())
        },
        plaza_rows=round(float(row.get("plaza_tiles", 0.0)) * int(row["rows_per_tile"])),
        walled=bool(row.get("walled", False)),
        config=config,
    )
    built = LAYOUTS[row["layout"]](context)
    plan = None
    if built is not None:
        cells, outside = built if isinstance(built, tuple) else (built, built)
        cells, outside = clear_roads(cells, context.patch), clear_roads(outside, context.patch)
        cells.setflags(write=False)
        outside.setflags(write=False)
        plan = SitePlan(geometry, floor, cells, outside)
    if len(cache) >= int(config.get("sites.cache_size")):
        cache.pop(next(iter(cache)))
    cache[key] = plan
    return plan
