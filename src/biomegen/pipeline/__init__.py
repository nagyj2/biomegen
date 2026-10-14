"""The procedural generation pipeline.

:func:`generate` runs the stages in a fixed order, each consuming only fields produced by earlier
stages so there is no backtracking:

    heightmap -> island_mask -> climate -> hydrology -> biomes -> regions
    (-> poi_placement -> roads -> poi_interiors -> naming, added in later phases)

Roads run **before** POI interiors so the road network knows where every POI anchor is: each road
that reaches a POI records its approach direction on the POI, and the interiors stage then sites that
POI's footprint entrance (and the interior door) on the side the road arrives from.

A **land-exists sanity gate** wraps the two cheap leading stages: if a seed yields too little land,
the seed is deterministically perturbed and those stages re-run, preventing empty-world cascades from
reaching the expensive downstream stages.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict

import numpy as np

from ..config.model import Config
from ..util import rng
from ..world.tile import BIOME_NAME, Biome, WaterType
from ..world.world import World
from . import (
    biomes,
    climate,
    heightmap,
    hydrology,
    island_mask,
    naming,
    poi_interiors,
    poi_placement,
    regions,
    roads,
)


def generate(config: Config, seed: int) -> World:
    """Generate and return a fully-populated :class:`World` for ``seed``.

    ``config`` is a :class:`~biomegen.config.model.Config`; ``seed`` is the (already normalised)
    master seed. The returned world is treated as immutable by all downstream consumers.
    """
    width = int(config.get("world.width"))
    height = int(config.get("world.height"))
    attempts = int(config.get("world.regen_attempts"))
    min_land = float(config.get("world.min_land_fraction"))

    world: World | None = None
    for attempt in range(max(1, attempts)):
        # Attempt 0 uses the master seed directly; later attempts perturb it deterministically.
        gen_seed = seed if attempt == 0 else rng.derive_int(seed, "regen", attempt)
        world = World(width, height, gen_seed)
        world.master_seed = seed  # original seed (for echoing / naming continuity)

        # The two leading stages form the gate: cheap, and they decide how much land exists.
        heightmap.run(world, config, gen_seed)
        island_mask.run(world, config, gen_seed)
        if island_mask.land_fraction(world) >= min_land:
            break

    assert world is not None
    gen_seed = world.seed

    # Downstream stages (only reached once a land-bearing world is in hand).
    climate.run(world, config, gen_seed)
    hydrology.run(world, config, gen_seed)
    biomes.run(world, config, gen_seed)
    regions.run(world, config, gen_seed)
    poi_placement.run(world, config, gen_seed)
    roads.run(world, config, gen_seed)
    poi_interiors.run(world, config, gen_seed)
    naming.run(world, config, gen_seed)
    return world


def stats(world: World) -> Dict[str, object]:
    """Return summary statistics for a generated world (used by the headless dump and tests)."""
    biome_counts = {
        BIOME_NAME[int(v)]: int(c) for v, c in zip(*np.unique(world.biome, return_counts=True), strict=True)
    }
    land = world.water_type == int(WaterType.NONE)
    return {
        "size": (world.width, world.height),
        "seed": world.seed,
        "land_fraction": round(float(land.mean()), 4),
        "biomes": dict(sorted(biome_counts.items())),
        "regions": len(world.regions),
        "rivers": len(world.rivers),
        "lakes": len(world.lakes),
        "river_tiles": int((world.biome == int(Biome.RIVER)).sum()),
        "lake_tiles": int((world.biome == int(Biome.LAKE)).sum()),
        "road_tiles": int((world.road != 0).sum()),
        "pois": len(world.pois),
        "poi_kinds": dict(sorted(Counter(p.kind for p in world.pois).items())),
        "bridges": sum(1 for p in world.pois if p.kind == "bridge"),
        "elevation": {
            "min": round(float(world.elevation.min()), 3),
            "max": round(float(world.elevation.max()), 3),
            "mean": round(float(world.elevation.mean()), 3),
        },
        "fingerprint": world.fingerprint(),
    }
