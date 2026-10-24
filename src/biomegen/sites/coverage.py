"""Which cells and tiles a site covers, for the layers and the explorer."""

from __future__ import annotations

import weakref
from typing import Optional

from ..config.model import Config
from ..world.entities import POI
from ..world.reader import WorldReader
from ..world.sim_state import SimState
from ..world.world import World
from .geometry import SiteGeometry, site_geometry

# (config, the reader's state, its revision, how many places it had, the sites found)
_Entry = tuple[Config, Optional[SimState], int, int, list[tuple[int, POI, SiteGeometry]]]
_CACHE: "weakref.WeakKeyDictionary[World, dict[int, _Entry]]" = weakref.WeakKeyDictionary()


def site_places(reader: WorldReader, config: Config) -> list[tuple[int, POI, SiteGeometry]]:
    """Return every standing POI that has a site as ``(index, poi, geometry)``, in index order.

    The index is the POI's place in ``reader.places`` (what ``reader.manifest_of`` takes). The list is cached while the
    reader's state, its revision and its number of places are unchanged.
    """
    per_config = _CACHE.setdefault(reader.world, {})
    entry = per_config.get(id(config))
    places = reader.places
    if (
        entry is not None
        and entry[0] is config
        and entry[1] is reader.state
        and entry[2] == reader.revision
        and entry[3] == len(places)
    ):
        return entry[4]
    standing = reader.standing
    found = []
    for index, poi in enumerate(places):
        geometry = site_geometry(poi, config) if standing[index] else None
        if geometry is not None:
            found.append((index, poi, geometry))
    per_config[id(config)] = (config, reader.state, reader.revision, len(places), found)
    return found


def site_pois(world: World, config: Config) -> list[tuple[POI, SiteGeometry]]:
    """Return every POI of the generated ``world`` that has a site, with its geometry, in POI order."""
    return [(poi, geometry) for _, poi, geometry in site_places(WorldReader(world), config)]


def site_at(
    world: World, config: Config, tile_x: int, tile_y: int, reader: Optional[WorldReader] = None
) -> Optional[POI]:
    """Return the POI whose site covers tile ``(tile_x, tile_y)``, or None; the nearest anchor wins an overlap.

    With a ``reader`` the POIs are the simulation's (the ones it minted too); without one, the generated world's.
    """
    best: Optional[tuple[float, POI]] = None
    for _, poi, geometry in site_places(reader if reader is not None else WorldReader(world), config):
        if geometry.covers_tile(tile_x, tile_y):
            distance = (poi.x - tile_x) ** 2 + (poi.y - tile_y) ** 2
            if best is None or distance < best[0]:
                best = (distance, poi)
    return best[1] if best is not None else None
