"""Wild points of interest placed by location (tower, dungeon, ruin, camp, boat).

Settlements come from the settlements stage first, so they count for spacing and for the remoteness field. Each
kind in ``tables.pois`` placed by location (``source`` "location" or "both") then gets one pass, in ``priority``
order:

1. a hard **eligibility** mask (biome whitelist, elevation bounds, land or water, a free tile, and for land kinds
   enough dry land under the largest site it may grow to);
2. a soft **score** (freshwater and coastal closeness, remoteness from settlements, seeded jitter), with every
   falloff in km;
3. **blue-noise picking**: best score first, kept when no placed POI is closer than ``min_spacing_km``.

A kind's count is the land (or sea, for ``on_water``) area over its ``km2_per_poi``, times ``poi.density``.
Candidates sort by score then row-major order and every draw is a ``poi`` stream, so the result does not depend
on dict or set order.
"""

from __future__ import annotations

import math
import random

import numpy as np

from ..config.model import Config
from ..sites.geometry import site_row_name
from ..util import geometry as geo
from ..util import rng
from ..world.entities import POI
from ..world.tile import WaterType, biome_from_name
from ..world.world import World

_CANDIDATE_LIMIT = 4000  # only the best-scoring eligible cells are tried; placement needs a handful


def max_footprint(config: Config, kind: str, purpose: str = "") -> tuple[int, int] | None:
    """Return the most tiles ``(w, h)`` a kind's site can cover given ``sites.size_jitter``, or None (no site).

    A POI with a ``purpose`` uses its ``<kind>_<purpose>`` site row when there is one.
    """
    row = config.get(f"tables.sites.{site_row_name(config, kind, purpose)}", None)
    if row is None:
        return None
    jitter = float(config.get("sites.size_jitter"))
    width, height = row["extent_tiles"]
    return max(1, math.ceil(width * (1.0 + jitter))), max(1, math.ceil(height * (1.0 + jitter)))


def footprint_land_fraction_mask(world: World, width: int, height: int, min_fraction: float) -> np.ndarray:
    """Bool grid: True where a ``width x height`` footprint centred on the tile is at least ``min_fraction`` land.

    Off-map cells count as land, so a footprint clipped by the map border is judged on its on-map water only. A
    summed-area table makes each window count a four-point lookup.
    """
    water = (world.water_type != int(WaterType.NONE)).astype(np.int64)
    rows, cols = water.shape
    table = np.zeros((rows + 1, cols + 1), dtype=np.int64)
    table[1:, 1:] = water.cumsum(0).cumsum(1)
    xs, ys = np.arange(cols), np.arange(rows)
    x0 = np.clip(xs - width // 2, 0, cols)
    x1 = np.clip(xs - width // 2 + width, 0, cols)
    y0 = np.clip(ys - height // 2, 0, rows)
    y1 = np.clip(ys - height // 2 + height, 0, rows)
    water_count = table[np.ix_(y1, x1)] - table[np.ix_(y0, x1)] - table[np.ix_(y1, x0)] + table[np.ix_(y0, x0)]
    full_area = max(1, width * height)
    return (full_area - water_count) / full_area >= min_fraction


def _eligible(world: World, row: dict, footprint: tuple[int, int] | None, min_land: float) -> np.ndarray:
    """Bool grid of the cells a kind may occupy."""
    wanted = np.array(sorted(int(biome_from_name(name)) for name in row.get("biomes", [])), dtype=world.biome.dtype)
    on_water = bool(row.get("on_water", False))
    surface = (world.water_type != int(WaterType.NONE)) if on_water else (world.water_type == int(WaterType.NONE))
    mask = np.isin(world.biome, wanted) & surface & (world.poi_index < 0)
    if "elevation_min_m" in row:
        mask &= world.elevation_m >= float(row["elevation_min_m"])
    if "elevation_max_m" in row:
        mask &= world.elevation_m <= float(row["elevation_max_m"])
    if not on_water and footprint is not None:
        mask &= footprint_land_fraction_mask(world, footprint[0], footprint[1], min_land)
    return mask


def _closeness(distance_km: np.ndarray, scale_km: float) -> np.ndarray:
    """Map a km distance to a ``[0, 1]`` closeness weight (near is 1); an infinite distance gives 0."""
    with np.errstate(over="ignore"):
        return np.exp(-distance_km / max(scale_km, 1e-6)).astype(np.float64)


def _remoteness(distance_km: np.ndarray, scale_km: float) -> np.ndarray:
    """Map a km distance to a ``[0, 1]`` remoteness weight (far is 1); an infinite distance gives 1."""
    return np.where(np.isfinite(distance_km), 1.0 - _closeness(distance_km, scale_km), 1.0)


def _floors(kind: str, row: dict, stream: random.Random) -> tuple[int, int]:
    """Return ``(floor_count, lowest_floor)``: a dungeon descends, everything else anchors at floor 0."""
    floors = row.get("floors", 1)
    if isinstance(floors, (list, tuple)):
        lo, hi = int(floors[0]), int(floors[1])
        count = stream.randint(min(lo, hi), max(lo, hi))
    else:
        count = int(floors)
    count = max(1, count)
    return count, (-(count - 1) if kind == "dungeon" else 0)


def pick_blue_noise(
    score: np.ndarray, count: int, spacing_km: float, placed: list[tuple[int, int]], world: World
) -> list[tuple[int, int]]:
    """Blue-noise pick: best-scoring cells first, each kept when every placed POI is at least ``spacing_km`` away."""
    ys, xs = np.nonzero(np.isfinite(score))
    if xs.size == 0 or count <= 0:
        return []
    order = np.lexsort((xs, ys, -score[ys, xs]))[:_CANDIDATE_LIMIT]
    km_col, km_row = world.scale.km_per_col, world.scale.km_per_row
    anchors = np.array(placed, dtype=np.float64).reshape(-1, 2)
    picked: list[tuple[int, int]] = []
    for index in order.tolist():
        if len(picked) >= count:
            break
        x, y = int(xs[index]), int(ys[index])
        if anchors.shape[0]:
            nearest = np.hypot((anchors[:, 0] - x) * km_col, (anchors[:, 1] - y) * km_row).min()
            if nearest < spacing_km:
                continue
        picked.append((x, y))
        anchors = np.vstack([anchors, [x, y]])
    return picked


def _commit(world: World, seed: int, kind: str, x: int, y: int, floors: tuple[int, int], purpose: str = "") -> None:
    """Append one POI and write it into ``poi_index``."""
    poi = POI(
        kind=kind,
        x=x,
        y=y,
        interior_seed=rng.derive_int(seed, "poi_interior", x, y),
        floor_count=floors[0],
        lowest_floor=floors[1],
        purpose=purpose,
    )
    index = len(world.pois)
    world.pois.append(poi)
    world.poi_index[y, x] = index


def run(world: World, config: Config, seed: int) -> None:
    """Place every location-sourced ``tables.pois`` kind, mutating ``world`` in place."""
    backend = config.get("compute.backend")
    sampling = world.scale.sampling
    land = world.water_type == int(WaterType.NONE)
    cell_km2 = world.scale.cell_area_km2
    area_km2 = {True: float(land.sum()) * cell_km2, False: float((~land).sum()) * cell_km2}  # keyed by "land kind"

    fresh = geo.distance_to(
        world.water_type == int(WaterType.FRESH), backend=backend, metric="euclidean", sampling=sampling
    )
    fresh_weight = _closeness(fresh, float(config.get("poi.freshwater_scale_km")))
    coast_weight = _closeness(world.dist_to_ocean, float(config.get("poi.coastal_scale_km")))
    settled = np.zeros(land.shape, dtype=bool)
    for poi in world.pois:
        if poi.civilized:
            settled[poi.y, poi.x] = True
    remote = _remoteness(
        geo.distance_to(settled, backend=backend, metric="euclidean", sampling=sampling),
        float(config.get("poi.remoteness_scale_km")),
    )
    min_land = float(config.get("poi.min_footprint_land"))
    jitter = float(config.get("poi.jitter"))
    density = float(config.get("poi.density"))

    types = config.get("tables.pois")
    placed = [(p.x, p.y) for p in world.pois]
    for kind in sorted(types, key=lambda name: (int(types[name].get("priority", 0)), name)):
        row = types[kind]
        if row.get("source", "location") == "history" or "km2_per_poi" not in row:
            continue
        on_water = bool(row.get("on_water", False))
        count = round(area_km2[not on_water] / float(row["km2_per_poi"]) * density)
        if count <= 0 or not row.get("biomes"):
            continue
        purpose = str(row.get("purpose", ""))
        footprint = None if on_water else max_footprint(config, kind, purpose)
        mask = _eligible(world, row, footprint, min_land)
        noise = rng.derive_numpy(seed, "poi", kind).random(mask.shape) * jitter
        score = 1.0 + float(row.get("near_freshwater", 0.0)) * fresh_weight
        score = score + float(row.get("coastal", 0.0)) * coast_weight + float(row.get("remoteness", 0.0)) * remote
        score = np.where(mask, score + noise, -np.inf)

        stream = rng.derive(seed, "poi", kind, "floors")
        for x, y in pick_blue_noise(score, count, float(row["min_spacing_km"]), placed, world):
            _commit(world, seed, kind, x, y, _floors(kind, row, stream), purpose)
            placed.append((x, y))
