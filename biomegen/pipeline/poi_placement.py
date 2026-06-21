"""Stage 7: POI placement.

Places points of interest (city, town, village, tower, dungeon, ruin, camp, boat) on the finished
terrain. Approach: build shared suitability fields once, then walk the kinds in a fixed priority order
(high-value civilized settlements first) and, for each, score every eligible tile and pick anchors
with a capacity-constrained blue-noise sampler that enforces per-kind spacing against a *shared* set
of already-placed POIs. Civilized POIs feed a remoteness field as they land, so later uncivilized
kinds naturally avoid settlements.

Each placement writes ``world.poi_index`` at the anchor, mints a deterministic ``interior_seed`` (for
the lazy Phase-5 interiors), records floor metadata, and registers itself with its region. Everything
is keyed on integer coordinates and iterated in sorted order, so the result is invariant to
dict/set ordering and ``PYTHONHASHSEED``.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

from ..config.model import Config
from ..util import rng
from ..world.entities import POI
from ..world.world import World
from . import poi_fields, poi_rules
from .poi_rules import KindRule
from .poi_sampler import POI_SAMPLERS

# Fixed priority so higher-value civilized POIs claim the best land first; also makes results stable.
KIND_PRIORITY: Tuple[str, ...] = (
    "city",
    "town",
    "village",
    "tower",
    "dungeon",
    "ruin",
    "camp",
    "boat",
)


def _max_footprint(config: Config, kind: str) -> Optional[Tuple[int, int]]:
    """Largest footprint (w, h) a kind's structure can grow to, given ``interiors.size_jitter``.

    The interiors stage scales each nominal footprint dimension by a factor in ``[1-jitter, 1+jitter)``
    (see :mod:`poi_interiors`). For the land-fraction check we need the *upper bound* so it covers any
    jitter outcome; ``ceil(nominal * (1 + jitter))`` is that bound (conservative by at most one tile).
    Returns ``None`` when the kind has no configured footprint (nothing to keep off the water).
    """
    fp = config.get("interiors.footprints").get(kind)
    if not fp:
        return None
    jitter = float(config.get("interiors.size_jitter"))
    fw = max(1, math.ceil(int(fp[0]) * (1.0 + jitter)))
    fh = max(1, math.ceil(int(fp[1]) * (1.0 + jitter)))
    return fw, fh


def _commit_poi(world: World, seed: int, kind: str, x: int, y: int, rule: KindRule, rgen: random.Random) -> int:
    """Build one :class:`POI`, write it into the world, and return its index."""
    floor_count, lowest_floor = poi_rules.floors_for(kind, rule, rgen)
    region_id = int(world.region_id[y, x])
    poi = POI(
        kind=kind,
        x=x,
        y=y,
        interior_seed=rng.derive_int(seed, "poi_interior", x, y),
        civilized=rule.civilized,
        region_id=region_id,
        floor_count=floor_count,
        lowest_floor=lowest_floor,
        footprint=(1, 1),  # refined in Phase 5 when structures are generated
        entrance=(x, y),  # anchor doubles as the entrance until Phase 5
    )
    index = len(world.pois)
    world.pois.append(poi)
    world.poi_index[y, x] = index
    if 0 <= region_id < len(world.regions):
        world.regions[region_id].poi_indices.append(index)
    return index


def run(world: World, config: Config, seed: int) -> None:
    """Place all POIs in priority order, mutating ``world`` in place."""
    backend = config.get("compute.backend")
    poi_cfg = config.section("poi")
    sampler = POI_SAMPLERS.get(poi_cfg.get("sampler", "bluenoise"))
    types_cfg = config.get("poi.types")

    fresh_scale = float(poi_cfg.get("freshwater_scale", 6.0))
    coast_scale = float(poi_cfg.get("coastal_scale", 9.0))
    remote_scale = float(poi_cfg.get("remoteness_scale", 22.0))
    jitter_strength = float(poi_cfg.get("jitter", 0.15))
    min_land = float(poi_cfg.get("min_footprint_land", 0.5))

    # Shared distance fields (freshwater/coast are static; remoteness grows as settlements land).
    fresh_dist = poi_fields.freshwater_distance(world, backend)
    coast_dist = poi_fields.coast_distance(world)
    fresh_w = poi_fields.closeness_weight(fresh_dist, fresh_scale)
    coast_w = poi_fields.closeness_weight(coast_dist, coast_scale)

    placed: List[Tuple[int, int]] = []  # all anchors (shared spacing)
    civ_points: List[Tuple[int, int]] = []  # civilized anchors (drive remoteness)

    for kind in KIND_PRIORITY:
        raw = types_cfg.get(kind)
        if not raw:
            continue
        rule = poi_rules.parse_rule(kind, raw)
        if rule.count <= 0 or not rule.biome_ints:
            continue

        # Remoteness reflects the settlements placed so far (only matters when a kind weights it).
        if rule.remoteness > 0:
            remote_dist = poi_fields.remoteness_distance(world, civ_points, backend)
            remote_w = poi_fields.remoteness_weight(remote_dist, remote_scale)
        else:
            remote_w = fresh_w * 0.0  # zero field matching expected ndarray shape/type

        # Land structures must anchor where most of their (max) footprint is dry land, so a coastal
        # structure stays substantial while the terrain-aware builder forms it around the water. Boats
        # (on_water) skip the land check; bridges have no footprint here. See poi_rules.eligibility_mask.
        footprint = None if rule.on_water else _max_footprint(config, kind)
        mask = poi_rules.eligibility_mask(rule, world, footprint, min_land)
        jitter = poi_rules.build_jitter(world, seed, kind, jitter_strength)
        score = poi_rules.score_array(rule, mask, fresh_w, coast_w, remote_w, jitter)

        rgen = rng.derive(seed, "poi", kind, "floors")
        for x, y in sampler(score, rule, placed):
            _commit_poi(world, seed, kind, x, y, rule, rgen)
            placed.append((x, y))
            if rule.civilized:
                civ_points.append((x, y))
