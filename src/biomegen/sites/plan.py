"""Site plans: the layout of one floor of one POI, built lazily and cached.

``site_plan`` is a pure function of the POI, the floor, the config and the world's terrain around the anchor. Same
inputs, same plan. Plans are never stored in the world: they live in a bounded cache keyed by the world, so a fresh
world starts with none. The cached arrays are read-only; runtime edits go through
:meth:`biomegen.world.overlay.Overlay.apply_interior`.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, replace
from typing import Optional

import numpy as np

from ..config.model import Config
from ..world.entities import POI
from ..world.manifest import SiteManifest
from ..world.tile import Cell
from ..world.world import World
from . import battlefield, boat, camp, homestead, settlement, structure  # noqa: F401  (imported for their @layout registrations)
from .cells import VOID
from .geometry import SiteGeometry, site_floor_range, site_geometry, site_roof_floor, site_row_for
from .homestead import homestead_lot
from .kinds import family_weights, tier_centre
from .layout import LAYOUTS, Fall, SiteBuilding, SiteContext
from .manifest import site_manifest
from .patch import read_patch
from .potential import plan_tier
from .settlement import Lot
from .streets import clear_roads
from .surroundings import settlement_kinds


@dataclass(frozen=True)
class SitePlan:
    """One floor of one site.

    Attributes:
        geometry: The site's extent, window and resolution.
        floor: The floor this plan shows.
        cells: ``Cell`` values over the extent box (``box_rows x box_cols``, read-only), seen from inside; void shows
            the terrain.
        outside: The same box seen from outside (the map, zoom and local scales): buildings as roofs, walls solid.
        buildings: The buildings that stand in the plan (kind and rectangle), in lot order; empty for a site with none.
    """

    geometry: SiteGeometry
    floor: int
    cells: np.ndarray
    outside: np.ndarray
    buildings: tuple[SiteBuilding, ...] = ()

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


def _furniture(config: Config, row: dict) -> dict[str, list[tuple[Cell, float]]]:
    """The furniture weights of a site row's family, per room role."""
    return family_weights(config, str(row["furniture"]))


def _fall(config: Config, row: dict, age_years: Optional[int]) -> Fall:
    """How far a ruin of the tier ``row`` has fallen at ``age_years`` (an undated ruin counts as old)."""
    progress = (
        1.0 if age_years is None else min(1.0, age_years / max(1.0, float(config.get("sites.ruin_erosion_years"))))
    )

    def along(young: float, old: float) -> float:
        return young + (old - young) * progress

    return Fall(
        standing=along(*(float(v) for v in row["ruin_standing"])),
        wall=along(*(float(v) for v in row["ruin_wall_fall"])),
        erosion=along(float(config.get("sites.ruin_erosion_young")), float(config.get("sites.ruin_erosion"))),
    )


def _grown_lot(poi: POI, manifest: SiteManifest, config: Config, world: World, geometry: SiteGeometry) -> Optional[Lot]:
    """Return the building of the homestead ``poi`` grew from, in the cells of ``poi``'s own plan, or None.

    The homestead is drawn as the twin of ``poi`` (same cell, seed, tags and potential) with the style the manifest
    names; its building is the lot :func:`~biomegen.sites.homestead.homestead_lot` finds, moved by the difference
    between the two windows. The cells line up because a growing homestead is drawn on its potential's grid
    (``resolution_row``); with a different grid, or no room for the homestead, there is nothing to carry over.
    """
    twin = replace(poi, kind="homestead", civilized=False, ruin_of="", purpose="", style=manifest.grown_from)
    before = site_geometry(twin, config)
    if before is None or (before.cell_w, before.cell_h) != (geometry.cell_w, geometry.cell_h):
        return None
    row = config.get(f"tables.sites.{site_row_for(config, twin)}")
    context = SiteContext(
        kind="homestead",
        seed=int(poi.interior_seed),
        floor=0,
        lowest_floor=0,
        floor_count=1,
        patch=read_patch(twin, before, world, config),
        furniture=_furniture(config, row),
        plaza_rows=0,
        walled=False,
        config=config,
        tags=tuple(poi.tags),
        dress=str(row.get("dress", "")),
        style=manifest.grown_from,
    )
    lot = homestead_lot(context)
    if lot is None:
        return None
    dx = (before.cam_x - geometry.cam_x) * geometry.cell_w + before.box[0] - geometry.box[0]
    dy = (before.cam_y - geometry.cam_y) * geometry.cell_h + before.box[1] - geometry.box[1]
    return replace(lot, x=lot.x + dx, y=lot.y + dy)


def site_plan(
    poi: POI, floor: int, config: Config, world: World, manifest: Optional[SiteManifest] = None
) -> Optional[SitePlan]:
    """Return the plan of ``poi``'s ``floor`` (clamped to its floors), or None if its kind has no site or no room.

    A settlement's plan is drawn for its potential and reads what stands from ``manifest`` (default: the one its tier
    and population make, :func:`~biomegen.sites.manifest.site_manifest`), never the tier or population itself.
    """
    lowest, highest = site_floor_range(poi, config)
    floor = max(lowest, min(int(floor), highest))
    cache = _cache(world, config)
    manifest = site_manifest(config, poi) if manifest is None else manifest
    key = (
        poi.kind,
        poi.purpose,
        poi.style,
        poi.ruin_of,
        poi.potential,
        manifest,
        poi.x,
        poi.y,
        poi.interior_seed,
        poi.floor_count,
        poi.lowest_floor,
        tuple(poi.tags),
        poi.fell,
        world.year,
        floor,
    )
    if key in cache:
        return cache[key]
    geometry = site_geometry(poi, config)
    if geometry is None:
        cache[key] = None
        return None
    row = config.get(f"tables.sites.{site_row_for(config, poi)}")
    age_years = None if poi.fell is None else max(0, world.year - poi.fell)
    # Only a settlement lays its own roof level; any other layout is built on the ground floor and seen from outside.
    roof_view = floor == site_roof_floor(poi, config) and row["layout"] != "settlement"
    settled = manifest if row["layout"] == "settlement" else None  # what stands, for a settlement layout only
    # A ruin falls as the tier it was (its own row's numbers), on the plan its potential draws.
    fallen_row = config.get(f"tables.sites.{poi.ruin_of}", row) if poi.kind == "ruin" and poi.ruin_of else row
    context = SiteContext(
        kind=poi.kind,
        seed=int(poi.interior_seed),
        floor=0 if roof_view else floor,
        lowest_floor=int(poi.lowest_floor),
        floor_count=int(poi.floor_count),
        patch=read_patch(poi, geometry, world, config),
        furniture=_furniture(config, row),
        plaza_rows=round(float(row.get("plaza_tiles", 0.0)) * int(row["rows_per_tile"])),
        walled=settled.walled if settled is not None else bool(row.get("walled", False)),
        wall_planned=bool(row.get("walled", False)),
        config=config,
        tags=tuple(poi.tags),
        age_years=age_years,
        purpose=poi.purpose,
        fall=_fall(config, fallen_row, age_years) if poi.kind == "ruin" and "ruin_standing" in fallen_row else None,
        dress=str(row.get("dress", "")),
        potential=plan_tier(config, poi) if settled is not None else "",
        centre=tier_centre(config, settled.tier) if settled is not None else "",
        manifest=settled,
        kinds=tuple(settlement_kinds(world, config, poi)) if settled is not None else (),
        style=poi.style,
        grown=_grown_lot(poi, settled, config, world, geometry) if settled is not None and settled.grown_from else None,
    )
    built = LAYOUTS[row["layout"]](context)
    if built is None and context.fall is not None:  # no room for the settlement: a single fallen building instead
        roof_view = floor == site_roof_floor(poi, config)  # which is no settlement, so it has no roof level of its own
        ruin_row = config.get("tables.sites.ruin")
        built = LAYOUTS[ruin_row["layout"]](
            replace(
                context,
                furniture=_furniture(config, ruin_row),
                plaza_rows=0,
                walled=False,
                wall_planned=False,
                fall=None,
                floor=0 if roof_view else floor,
            )
        )
    plan = None
    if built is not None:
        buildings: tuple[SiteBuilding, ...] = ()
        if not isinstance(built, tuple):
            cells, outside = built, built
        elif len(built) == 3:
            cells, outside, buildings = built
        else:
            cells, outside = built
        if roof_view:
            cells = outside.copy()  # the roof level is the surface: every building as its roof
        cells, outside = clear_roads(cells, context.patch), clear_roads(outside, context.patch)
        cells.setflags(write=False)
        outside.setflags(write=False)
        plan = SitePlan(geometry, floor, cells, outside, buildings)
    if len(cache) >= int(config.get("sites.cache_size")):
        cache.pop(next(iter(cache)))
    cache[key] = plan
    return plan
