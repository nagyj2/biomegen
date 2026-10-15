"""Locality for text: which settlement an event may name as "near" it, and which feature a reason may name.

Text never names a faraway place. A settlement qualifies only when it is on the same landmass as the event's cell and
within ``history.near_km`` of it; otherwise the event uses wording that names no place. A river, mountain range or sea
named in a relation's reason qualifies the same way, within ``politics.reason_near_km`` of the powers' border.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence

import numpy as np

from ...config.model import Config
from ...world.entities import GeoFeature
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


def _feature_cells(world: World, feature: GeoFeature) -> list[tuple[int, int]]:
    """The cells a feature covers: a river's channel, an area feature's cells, a sea's anchor."""
    if feature.kind == "river":
        return list(world.rivers[feature.ref].path)
    return list(feature.cells) if feature.cells else [feature.anchor]


def nearest_feature(world: World, config: Config, kind: str, points: Sequence[tuple[int, int]]) -> int:
    """Return the id in ``world.features`` of the feature of ``kind`` nearest ``points``, or -1 when none qualifies.

    A river or range qualifies when some cell of it is within ``politics.reason_near_km`` of a point and on that
    point's landmass; a sea when a point lies within that distance of the coast, the sea whose anchor is nearest then
    wins. Only ``politics.reason_points`` evenly spaced points are measured. Ties go to the lower feature id.
    """
    if not points:
        return -1
    cap_km = float(config.get("politics.reason_near_km"))
    step = max(1, math.ceil(len(points) / int(config.get("politics.reason_points"))))
    chosen = np.array(list(points[::step]), dtype=np.float64)
    km_col, km_row = world.scale.km_per_col, world.scale.km_per_row
    best_km, best = math.inf, -1
    for feature in world.features:
        if feature.kind != kind:
            continue
        cells = np.array(_feature_cells(world, feature), dtype=np.float64).reshape(-1, 2)
        if cells.shape[0] == 0:
            continue
        gap = np.hypot(
            (chosen[:, None, 0] - cells[None, :, 0]) * km_col, (chosen[:, None, 1] - cells[None, :, 1]) * km_row
        )
        if kind == "sea":
            coast = world.dist_to_ocean[chosen[:, 1].astype(int), chosen[:, 0].astype(int)]
            if float(coast.min()) > cap_km:
                continue
        else:
            near_point, near_cell = np.unravel_index(int(np.argmin(gap)), gap.shape)
            here = world.landmass_id[int(chosen[near_point, 1]), int(chosen[near_point, 0])]
            there = world.landmass_id[int(cells[near_cell, 1]), int(cells[near_cell, 0])]
            if float(gap.min()) > cap_km or (here >= 0 and there >= 0 and here != there):
                continue
        km = float(gap.min())
        if km < best_km:
            best_km, best = km, feature.id
    return best
