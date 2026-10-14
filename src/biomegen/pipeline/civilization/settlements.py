"""Stage 7: settlements - habitability and the capital / city / town / village tiers.

1. **Habitability.** Each land cell scores ``tables.biomes.<biome>.habitability`` times the relief's
   ``habitability_mul``, plus bonuses for a river, the coast or a lake within reach (km), scaled by a seeded
   per-cell jitter so equal sites do not tie. Water and cells scoring at or below ``min_habitability`` are never
   settled.
2. **Placement.** Tiers go in ``rank`` order (capitals first). A tier's count is the land area over its
   ``land_per_settlement_km2`` (times ``settlements.density``). Candidates are tried best-scoring first and kept when
   no settlement is closer than the tier's ``spacing_km``. Distances are km and aspect-aware. Capitals need a big
   landmass; cities and towns need a landmass large enough to be a named feature.
3. **Record.** Each settlement is a :class:`~biomegen.world.entities.POI` of the tier's kind with a population drawn
   from the tier's range and ``port`` / ``river`` tags.

Everything is ordered (score, then row-major) and every draw comes from the ``settlements`` stream, so the result
does not depend on dict or set order.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import rng
from ...world.entities import POI
from ...world.tile import BIOME_NAME, RELIEF_NAME, Biome, WaterType
from ...world.world import World

_LANDMASS_REQUIRED = {"capital", "city", "town"}


def _reach(world: World, config: Config, mask: np.ndarray, reach_km: float) -> np.ndarray:
    """Bool grid: True where ``mask`` lies within ``reach_km`` (aspect-aware); all False if ``mask`` is empty."""
    if not mask.any():
        return np.zeros(mask.shape, dtype=bool)
    distance = geo.distance_to(
        mask, backend=config.get("compute.backend"), metric="euclidean", sampling=world.scale.sampling
    )
    return distance <= reach_km


_REACH_PREFIXES = ("river", "coast", "lake")
_TAGS = (("port", "coast"), ("river", "river"), ("lake", "lake"))  # POI tag -> the reach mask that earns it


def _reach_masks(world: World, config: Config) -> dict[str, np.ndarray]:
    """Bool grids per ``river`` / ``coast`` / ``lake``: True where that water lies within its configured reach."""
    fresh = world.water_type == int(WaterType.FRESH)
    lake = fresh & (world.biome == int(Biome.LAKE))
    water = {"river": fresh & ~lake, "coast": world.water_type == int(WaterType.SALT), "lake": lake}
    return {
        prefix: _reach(world, config, water[prefix], float(config.get(f"settlements.{prefix}_reach_km")))
        for prefix in _REACH_PREFIXES
    }


def _score(world: World, config: Config, seed: int, reach: dict[str, np.ndarray]) -> np.ndarray:
    """Habitability from the biome and relief tables, the water bonuses in ``reach`` and the seeded jitter."""
    base = config.table_array("biomes", "habitability", BIOME_NAME)[world.biome]
    relief_mul = config.table_array("relief", "habitability_mul", RELIEF_NAME)[world.relief]
    bonus = np.zeros(base.shape, dtype=np.float64)
    for prefix in _REACH_PREFIXES:
        bonus += np.where(reach[prefix], float(config.get(f"settlements.{prefix}_bonus")), 0.0)
    score = base * relief_mul + np.where(relief_mul > 0.0, bonus, 0.0)
    jitter = float(config.get("settlements.jitter"))
    noise = rng.derive_numpy(seed, "settlements", "habitability").random(score.shape)
    score = score * (1.0 - jitter + 2.0 * jitter * noise)
    land = world.water_type == int(WaterType.NONE)
    return np.where(land, score, 0.0).astype(np.float32)


def habitability(world: World, config: Config, seed: int) -> np.ndarray:
    """Return the settlement suitability of every cell as ``float32`` ``[y, x]`` (0 = never settled)."""
    return _score(world, config, seed, _reach_masks(world, config))


def _km_to(world: World, x: int, y: int) -> np.ndarray:
    """Km distance from cell ``(x, y)`` to every cell, ``[y, x]``."""
    scale = world.scale
    cols = (np.arange(world.width) - x) * scale.km_per_col
    rows = (np.arange(world.height) - y) * scale.km_per_row
    return np.hypot(rows[:, None], cols[None, :])


def _landmass_areas(world: World) -> np.ndarray:
    """Return landmass areas in km², indexed by ``landmass_id``."""
    ids = world.landmass_id[world.landmass_id >= 0]
    return np.bincount(ids, minlength=int(ids.max()) + 1 if ids.size else 1) * world.scale.cell_area_km2


def _eligible_landmasses(world: World, config: Config, tier: str) -> np.ndarray | None:
    """Bool per ``landmass_id``: which landmasses may hold ``tier`` (None = no landmass rule for the tier)."""
    if tier not in _LANDMASS_REQUIRED:
        return None
    areas = _landmass_areas(world)
    if tier == "capital":
        minimum = min(float(config.get("settlements.capital_min_landmass_km2")), float(areas.max()))
    else:
        minimum = float(config.get("geography.min_landmass_km2"))
    return areas >= minimum


def _tier_count(config: Config, tier: str, land_km2: float) -> int:
    per = float(config.get(f"tables.tiers.{tier}.land_per_settlement_km2"))
    count = round(land_km2 / per * float(config.get("settlements.density")))
    if tier == "capital":
        return max(1, min(int(config.get("settlements.max_capitals")), count))
    return max(0, count)


def run(world: World, config: Config, seed: int) -> None:
    """Place every tier's settlements as POIs, mutating ``world`` in place."""
    reach = _reach_masks(world, config)
    score = _score(world, config, seed, reach)
    land = world.water_type == int(WaterType.NONE)
    land_km2 = float(land.sum()) * world.scale.cell_area_km2
    minimum = float(config.get("settlements.min_habitability"))
    stream = rng.derive(seed, "settlements", "population")

    # Best-scoring first; ties fall back to row-major order (lexsort is stable on its last key).
    flat = np.argsort(-score.ravel(), kind="stable")
    candidates = flat[score.ravel()[flat] > minimum]
    candidate_ys, candidate_xs = np.divmod(candidates, world.width)

    nearest_km = np.full(score.shape, np.inf)
    tiers = sorted(config.get("tables.tiers"), key=lambda name: int(config.get(f"tables.tiers.{name}.rank")))
    for tier in tiers:
        row = config.get(f"tables.tiers.{tier}")
        wanted = _tier_count(config, tier, land_km2)
        allowed = _eligible_landmasses(world, config, tier)
        spacing = float(row["spacing_km"])
        lo, hi = (int(v) for v in row["pop"])
        placed = 0
        for x, y in zip(candidate_xs.tolist(), candidate_ys.tolist(), strict=True):
            if placed >= wanted:
                break
            if nearest_km[y, x] < spacing or world.poi_index[y, x] >= 0:
                continue
            if allowed is not None:
                landmass = int(world.landmass_id[y, x])
                if landmass < 0 or not allowed[landmass]:
                    continue
            _commit(world, reach, seed, tier, x, y, stream.randint(lo, hi))
            nearest_km = np.minimum(nearest_km, _km_to(world, x, y))
            placed += 1


def _commit(world: World, reach: dict[str, np.ndarray], seed: int, tier: str, x: int, y: int, population: int) -> None:
    """Append one settlement POI, tagged by the water in reach, and register it with its region."""
    region_id = int(world.region_id[y, x])
    tags = tuple(tag for tag, key in _TAGS if reach[key][y, x])
    poi = POI(
        kind=tier,
        x=x,
        y=y,
        interior_seed=rng.derive_int(seed, "poi_interior", x, y),
        civilized=True,
        region_id=region_id,
        pop=population,
        tags=tags,
    )
    index = len(world.pois)
    world.pois.append(poi)
    world.poi_index[y, x] = index
    if 0 <= region_id < len(world.regions):
        world.regions[region_id].poi_indices.append(index)
