"""What a settlement is chosen to have: its specialized buildings, from what lies round it.

:func:`settlement_kinds` is a pure function of the world's terrain within ``sites.kinds.radius_km`` of the settlement,
the POI (tier, population, tags, style) and the site seed, so a simulation reads the same list the plan draws. Each
production kind of ``tables.buildings`` scores by how well the land suits it (its ``suits`` weights over fertility,
forest, roughness, fresh water and coast, each saturating at ``sites.kinds.saturate``) and is ruled out without its
``needs_tag`` or below its ``min_score``. The tier's ``specialized`` slots (more with population) go to the kinds by
score share (D'Hondt, at most ``max_per_kind`` of one). A generated hamlet's own style kind is always first. Placing
the buildings is the layout's business: a kind that cannot be placed becomes housing there.

Reads small windows of ``World`` arrays only (``sites/`` never imports ``pipeline/``), and is memoised per world.
"""

from __future__ import annotations

import math
import weakref
from typing import Optional

import numpy as np

from ..config.model import Config
from ..util import rng
from ..world.entities import POI
from ..world.tile import BIOME_NAME, RELIEF_NAME, WaterType, biome_from_name
from ..world.world import World
from .potential import plan_tier, settlement_tier

_Cache = tuple[Config, dict[tuple, list[str]]]
_CACHES: "weakref.WeakKeyDictionary[World, dict[int, _Cache]]" = weakref.WeakKeyDictionary()


def _terms(world: World, config: Config, poi: POI) -> dict[str, float]:
    """Return the five terms of the land round ``poi``, each in ``[0, 1]``: fertility, forest, roughness, water, sea.

    Each term is a share of the land (or of the area, for water and sea) within its own ``sites.kinds.radius_km``, over
    its ``saturate`` value: hills are rarer near settlements than fields, so they are read over a wider area.
    """
    settings = config.get("sites.kinds")
    radii = {term: float(km) for term, km in settings["radius_km"].items()}
    scale = world.scale
    widest = max(radii.values())
    rx, ry = max(1, math.ceil(widest / scale.km_per_col)), max(1, math.ceil(widest / scale.km_per_row))
    x0, x1 = max(0, poi.x - rx), min(world.width, poi.x + rx + 1)
    y0, y1 = max(0, poi.y - ry), min(world.height, poi.y + ry + 1)
    window = (slice(y0, y1), slice(x0, x1))
    yy, xx = np.ogrid[y0:y1, x0:x1]
    distance2 = ((xx - poi.x) * scale.km_per_col) ** 2 + ((yy - poi.y) * scale.km_per_row) ** 2
    biome, relief, water = world.biome[window], world.relief[window], world.water_type[window]
    dry = water == int(WaterType.NONE)
    mul = config.table_array("relief", "habitability_mul", RELIEF_NAME)[relief]
    base = config.table_array("biomes", "habitability", BIOME_NAME)[biome]
    wooded = np.isin(biome, [int(biome_from_name(name)) for name in config.get("poi.forest_biomes")])

    def land_share(term: str, values: np.ndarray) -> float:
        land = (distance2 <= radii[term] ** 2) & dry
        return float(values[land].mean()) if land.any() else 0.0

    def area_share(term: str, wet: np.ndarray) -> float:
        inside = distance2 <= radii[term] ** 2
        return float((inside & wet).sum()) / max(1, int(inside.sum()))

    shares = {
        "fertility": land_share("fertility", base * mul),
        "forest": land_share("forest", wooded),
        "roughness": land_share("roughness", relief > 0),
        "fresh_water": area_share("fresh_water", water == int(WaterType.FRESH)),
        "coast": area_share("coast", water == int(WaterType.SALT)),
    }
    saturate = settings["saturate"]
    return {term: min(1.0, share / max(1e-9, float(saturate[term]))) for term, share in shares.items()}


def _score(suits: dict[str, float], terms: dict[str, float]) -> float:
    """Return how well land with ``terms`` suits a kind weighing ``suits``: the weighted mean of its terms."""
    total = sum(float(w) for w in suits.values())
    return sum(float(w) * terms[term] for term, w in suits.items()) / total if total > 0.0 else 0.0


def specialized_slots(config: Config, tier: str, pop: int) -> int:
    """Return how many specialized buildings a settlement of ``tier`` and ``pop`` has: its slot range, by population."""
    low, high = (int(v) for v in config.get(f"tables.sites.{tier}.specialized"))
    pop_low, pop_high = (int(v) for v in config.get(f"tables.tiers.{tier}.pop"))
    fraction = 0.0 if pop_high <= pop_low else min(1.0, max(0.0, (pop - pop_low) / (pop_high - pop_low)))
    return low + round((high - low) * fraction)


def _allocate(scores: dict[str, float], limits: dict[str, int], slots: int) -> list[str]:
    """Share ``slots`` among the kinds by score (D'Hondt): a slot goes to the best score over its count so far + 1."""
    given: dict[str, int] = {kind: 0 for kind in scores}
    order: list[str] = []
    for _ in range(slots):
        open_kinds = [kind for kind in sorted(scores) if given[kind] < limits[kind]]
        if not open_kinds:
            break
        kind = max(open_kinds, key=lambda k: (scores[k] / (given[k] + 1), -sorted(scores).index(k)))
        given[kind] += 1
        order.append(kind)
    return order


def settlement_kinds(world: World, config: Config, poi: POI) -> list[str]:
    """Return the specialized building kinds ``poi`` is chosen to have, in the order they are placed.

    The list is as long as the slots of the POI's potential (``tables.sites.<potential>.specialized``, the most), never
    shortened by its population: a settlement that has fewer built stands with a prefix of it (``SiteManifest``). Empty
    for a POI that is no settlement (a homestead, a wild site). A hamlet's style kind comes first. Pure and memoised per
    world and config.
    """
    if not settlement_tier(config, poi):
        return []
    tier = plan_tier(config, poi)
    if config.get(f"tables.sites.{tier}.specialized", None) is None:
        return []
    per_config = _CACHES.setdefault(world, {})
    entry = per_config.get(id(config))
    if entry is None or entry[0] is not config:  # an id can be reused once its config is gone
        entry = (config, {})
        per_config[id(config)] = entry
    key = (poi.x, poi.y, poi.interior_seed, tier, poi.style, tuple(poi.tags))
    if key not in entry[1]:
        entry[1][key] = _choose(world, config, poi, tier)
    return list(entry[1][key])


def _choose(world: World, config: Config, poi: POI, tier: str) -> list[str]:
    """Pick the kinds (see :func:`settlement_kinds`): the style's first, then the scored kinds by slot share."""
    buildings = config.get("tables.buildings")
    chosen: list[str] = []
    style_kind: Optional[str] = None
    if poi.style and config.get(f"tables.poi_styles.{poi.style}.building", None) is not None:
        style_kind = str(config.get(f"tables.poi_styles.{poi.style}.building"))
        chosen.append(style_kind)
    slots = int(config.get(f"tables.sites.{tier}.specialized")[1]) - len(chosen)
    if slots <= 0:
        return chosen
    terms = _terms(world, config, poi)
    stream = rng.derive(poi.interior_seed, "site.kinds")
    scores: dict[str, float] = {}
    limits: dict[str, int] = {}
    for kind in sorted(buildings):
        row = buildings[kind]
        jitter = stream.random() * 1e-6  # a seeded tie-break, always drawn so the stream stays aligned
        if row["function"] != "production" or kind == style_kind:
            continue
        if "needs_tag" in row and row["needs_tag"] not in poi.tags:
            continue
        score = _score(row["suits"], terms)
        if score >= float(row["min_score"]) and score > 0.0:
            scores[kind] = score + jitter
            limits[kind] = int(row["max_per_kind"])
    return chosen + _allocate(scores, limits, slots)
