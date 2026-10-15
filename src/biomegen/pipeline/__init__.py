"""The procedural generation pipeline.

:func:`generate` runs the stages in a fixed order, each consuming only fields produced by earlier
stages so there is no backtracking:

    terrain -> climate -> hydrology -> biomes -> geography -> regions -> settlements
    -> pois -> roads -> realms -> naming

Roads end at every POI's anchor. A POI's site plan (:mod:`biomegen.sites`) is built lazily and finds the roads
that reach it from the world arrays, so no stage records anything for it.

A **land-exists sanity gate** wraps the cheap leading terrain stage: if a seed yields too little land,
the seed is deterministically perturbed and the stage re-runs, preventing empty-world cascades from
reaching the expensive downstream stages. Terrain sets its sea level by rank, so the gate only trips
when a style's land fraction is configured below ``world.min_land_fraction``.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Callable, Dict, Optional

import numpy as np

from ..config.model import Config
from ..util import rng
from ..util.units import grid_scale
from ..world.tile import BIOME_NAME, RELIEF_NAME, WATER_BIOMES, WaterType
from ..world.world import World
from . import (
    naming,
    pois,
    regions,
)
from .civilization import realms, roads, settlements
from .physical import biomes, climate, geography, hydrology, terrain


def generate(config: Config, seed: int, timings: Optional[Dict[str, float]] = None) -> World:
    """Generate and return a fully-populated :class:`World` for ``seed``.

    ``config`` is a :class:`~biomegen.config.model.Config`; ``seed`` is the (already normalised)
    master seed. The returned world is treated as immutable by all downstream consumers. If ``timings``
    is given, each stage's wall-clock seconds are added to it under the stage name (for
    ``scripts/bench.sh``; timing never affects the world).
    """
    clock: Dict[str, float] = timings if timings is not None else {}

    def timed(name: str, stage: Callable[[World, Config, int], None], world: World, stage_seed: int) -> None:
        start = time.perf_counter()
        stage(world, config, stage_seed)
        clock[name] = clock.get(name, 0.0) + time.perf_counter() - start

    width = int(config.get("world.width"))
    height = int(config.get("world.height"))
    attempts = int(config.get("world.regen_attempts"))
    min_land = float(config.get("world.min_land_fraction"))
    size_km = config.get("world.size_km")

    world: World | None = None
    for attempt in range(max(1, attempts)):
        # Attempt 0 uses the master seed directly; later attempts perturb it deterministically.
        gen_seed = seed if attempt == 0 else rng.derive_int(seed, "regen", attempt)
        scale = grid_scale(
            width,
            height,
            (float(size_km[0]), float(size_km[1])),
            center_lat(config, gen_seed),
            float(config.get("world.center_lon")),
        )
        world = World(width, height, gen_seed, scale)
        world.master_seed = seed  # original seed (for echoing / naming continuity)

        # The leading stage forms the gate: cheap, and it decides how much land exists.
        timed("terrain", terrain.run, world, gen_seed)
        if terrain.land_fraction(world) >= min_land:
            break

    assert world is not None
    gen_seed = world.seed

    # Downstream stages (only reached once a land-bearing world is in hand).
    for name, stage in (
        ("climate", climate.run),
        ("hydrology", hydrology.run),
        ("biomes", biomes.run),
        ("geography", geography.run),
        ("regions", regions.run),
        ("settlements", settlements.run),
        ("pois", pois.run),
        ("roads", roads.run),
        ("realms", realms.run),
        ("naming", naming.run),
    ):
        timed(name, stage, world, gen_seed)
    return world


def center_lat(config: Config, seed: int) -> float:
    """Return the map-centre latitude: ``world.center_lat`` if it is a number, else one drawn for ``seed``.

    For ``"seed"`` the hemisphere and the absolute latitude (uniform in ``world.center_lat_range_deg``)
    come from the ``terrain.latitude`` stream, so the same seed always sits at the same latitude.
    """
    value = config.get("world.center_lat")
    if value != "seed":
        return float(value)
    lo, hi = (float(v) for v in config.get("world.center_lat_range_deg"))
    stream = rng.derive(seed, "terrain", "latitude")
    sign = stream.choice((-1.0, 1.0))
    return sign * stream.uniform(lo, hi)


def stats(world: World) -> Dict[str, object]:
    """Return summary statistics for a generated world (used by the headless dump and tests)."""
    biome_counts = {
        BIOME_NAME[int(v)]: int(c) for v, c in zip(*np.unique(world.biome, return_counts=True), strict=True)
    }
    land = world.water_type == int(WaterType.NONE)
    return {
        "size": (world.width, world.height),
        "cell_km": (round(world.km_per_col, 2), round(world.km_per_row, 2)),
        "lat_top": round(world.lat_top, 2),
        "lon_left": round(world.lon_left, 2),
        "seed": world.seed,
        "terrain_style": world.terrain_style,
        "land_fraction": round(float(land.mean()), 4),
        "biomes": dict(sorted(biome_counts.items())),
        "regions": len(world.regions),
        "realms": len(world.realms),
        "relations": len(world.relations),
        "rivers": len(world.rivers),
        "lakes": len(world.lakes),
        "features": dict(sorted(Counter(f.kind for f in world.features).items())),
        "river_tiles": int(
            ((world.water_type == int(WaterType.FRESH)) & ~np.isin(world.biome, list(WATER_BIOMES))).sum()
        ),
        "lake_tiles": sum(lake.area for lake in world.lakes),
        "relief": {
            RELIEF_NAME[int(v)]: int(c) for v, c in zip(*np.unique(world.relief, return_counts=True), strict=True)
        },
        "road_tiles": int((world.road != 0).sum()),
        "pois": len(world.pois),
        "poi_kinds": dict(sorted(Counter(p.kind for p in world.pois).items())),
        "bridge_tiles": int(((world.road != 0) & (world.water_type != int(WaterType.NONE))).sum()),
        "elevation_m": {
            "min": round(float(world.elevation_m.min()), 1),
            "max": round(float(world.elevation_m.max()), 1),
        },
        "fingerprint": world.fingerprint(),
    }
