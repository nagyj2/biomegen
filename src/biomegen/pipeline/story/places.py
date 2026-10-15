"""Locality for chronicle text: which settlement an event may name as "near" it.

An event never names a faraway place. A settlement qualifies only when it is on the same landmass as the event's cell
and within ``history.near_km`` of it; otherwise the event uses wording that names no place.
"""

from __future__ import annotations

import math
from collections.abc import Collection

from ...config.model import Config
from ...world.world import World


def nearest_settlement(world: World, config: Config, x: int, y: int, exclude: Collection[int] = ()) -> int:
    """Return the index in ``world.pois`` of the nearest settlement to cell ``(x, y)``, or -1 when none qualifies.

    Only civilized POIs on the same landmass within ``history.near_km`` count, and those in ``exclude`` never do. The
    cell must be on a landmass; the nearest settlement wins, a lower index breaking a tie.
    """
    landmass = int(world.landmass_id[y, x])
    if landmass < 0:
        return -1
    cap_km = float(config.get("history.near_km"))
    best_km, best = math.inf, -1
    for index, poi in enumerate(world.pois):
        if not poi.civilized or index in exclude or int(world.landmass_id[poi.y, poi.x]) != landmass:
            continue
        km = world.scale.distance_km(x, y, poi.x, poi.y)
        if km <= cap_km and km < best_km:
            best_km, best = km, index
    return best
