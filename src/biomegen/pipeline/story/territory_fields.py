"""Fields the territory planner reads, computed once per world (terrain and the present partition never change).

``seat_km`` is, for every cell a realm holds today, the straight-line distance in km to that realm's seat: the farther a
cell is from the seat, the later the realm is taken to have annexed it. Distances use the anisotropic grid
(``world.scale.sampling``), never a tile count, and are computed in each realm's bounding window.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from ...world.world import World


@dataclass(frozen=True)
class TerritoryFields:
    """Per-world fields of the territory planner.

    Attributes:
        seat_km: ``[y, x]`` float32 km from a held cell to its realm's seat; ``inf`` where no realm holds the cell.
        seats: Each realm's seat cell ``(x, y)`` by realm id; ``(-1, -1)`` for a realm that holds no cell.
    """

    seat_km: np.ndarray
    seats: tuple[tuple[int, int], ...]


def _seat_cell(world: World, realm_id: int, mask: np.ndarray, ys: np.ndarray, xs: np.ndarray) -> tuple[int, int]:
    """Return the cell of realm ``realm_id`` that stands for its seat: the seat settlement's, else the held cell
    nearest the realm's mean position (ties go to the first cell in row-major order)."""
    seat_poi = world.realms[realm_id].seat_poi
    if seat_poi >= 0:
        poi = world.pois[seat_poi]
        if mask[poi.y, poi.x]:
            return poi.x, poi.y
    km_row, km_col = world.scale.sampling
    gap = ((ys - ys.mean()) * km_row) ** 2 + ((xs - xs.mean()) * km_col) ** 2
    best = int(np.argmin(gap))
    return int(xs[best]), int(ys[best])


def territory_fields(world: World) -> TerritoryFields:
    """Compute the fields of ``world``'s present partition."""
    seat_km = np.full((world.height, world.width), np.inf, dtype=np.float32)
    seats: list[tuple[int, int]] = []
    for realm in world.realms:
        mask = world.realm_id == realm.id
        ys, xs = np.nonzero(mask)
        if not len(ys):
            seats.append((-1, -1))
            continue
        seat = _seat_cell(world, realm.id, mask, ys, xs)
        seats.append(seat)
        top, bottom, left, right = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
        seed = np.ones((bottom - top, right - left), dtype=bool)
        seed[seat[1] - top, seat[0] - left] = False
        km = ndimage.distance_transform_edt(seed, sampling=world.scale.sampling)
        window = (slice(top, bottom), slice(left, right))
        held = mask[window]
        seat_km[window][held] = km[held]
    return TerritoryFields(seat_km, tuple(seats))
