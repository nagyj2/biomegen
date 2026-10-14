"""Which cells and tiles a site covers, for the layers and the explorer."""

from __future__ import annotations

import weakref
from typing import Optional

import numpy as np

from ..config.model import Config
from ..sampling.sampler import Sampler
from ..world.entities import POI
from ..world.world import World
from .geometry import SiteGeometry, site_geometry

_Entry = tuple[Config, int, list[tuple[POI, SiteGeometry]]]
_CACHE: "weakref.WeakKeyDictionary[World, dict[int, _Entry]]" = weakref.WeakKeyDictionary()


def site_pois(world: World, config: Config) -> list[tuple[POI, SiteGeometry]]:
    """Return every POI that has a site, with its geometry, in POI order (cached while the POI list is unchanged)."""
    per_config = _CACHE.setdefault(world, {})
    entry = per_config.get(id(config))
    if entry is not None and entry[0] is config and entry[1] == len(world.pois):
        return entry[2]
    found = []
    for poi in world.pois:
        geometry = site_geometry(poi, config)
        if geometry is not None:
            found.append((poi, geometry))
    per_config[id(config)] = (config, len(world.pois), found)
    return found


def extent_mask(world: World, config: Config, sampler: Sampler) -> np.ndarray:
    """Return the cells of ``sampler``'s grid that lie under any site's extent."""
    mask = np.zeros(sampler.fx.shape, dtype=bool)
    for _poi, geometry in site_pois(world, config):
        left, top, right, bottom = geometry.extent
        mask |= (sampler.fx >= left) & (sampler.fx < right) & (sampler.fy >= top) & (sampler.fy < bottom)
    return mask


def site_at(world: World, config: Config, tile_x: int, tile_y: int) -> Optional[POI]:
    """Return the POI whose site covers tile ``(tile_x, tile_y)``, or None; the nearest anchor wins an overlap."""
    best: Optional[tuple[float, POI]] = None
    for poi, geometry in site_pois(world, config):
        if geometry.covers_tile(tile_x, tile_y):
            distance = (poi.x - tile_x) ** 2 + (poi.y - tile_y) ** 2
            if best is None or distance < best[0]:
                best = (distance, poi)
    return best[1] if best is not None else None
