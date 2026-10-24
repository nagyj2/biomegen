"""Sites: the plan you see when you zoom into a point of interest.

A site is a pure, lazily built view of one POI: its extent in world tiles (:mod:`.geometry`), the terrain under it
(:mod:`.patch`) and a layout of walls, streets and furniture on that terrain (:mod:`.plan`). Nothing here is stored in
the :class:`~biomegen.world.world.World`.
"""

from __future__ import annotations

from .cells import NO_WALL, OUTSIDE_PRIORITY, PASSABLE, SHELL, STRUCTURAL, wall_index
from .coverage import site_at, site_place_at, site_places, site_pois
from .geometry import SiteGeometry, site_floor_range, site_geometry, site_roof_floor
from .patch import Gate, SitePatch, read_patch, window_sampler
from .plan import SitePlan, clear_cache, site_plan

__all__ = [
    "NO_WALL",
    "OUTSIDE_PRIORITY",
    "PASSABLE",
    "SHELL",
    "STRUCTURAL",
    "Gate",
    "SiteGeometry",
    "SitePatch",
    "SitePlan",
    "clear_cache",
    "read_patch",
    "site_at",
    "site_floor_range",
    "site_geometry",
    "site_place_at",
    "site_places",
    "site_plan",
    "site_roof_floor",
    "site_pois",
    "wall_index",
    "window_sampler",
]
