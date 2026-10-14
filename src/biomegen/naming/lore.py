"""Region fact extraction + geographic vocabulary for naming/lore.

Pulls grounded facts from a region (dominant biome, size bucket, the settlements/ruin it contains via
``region.poi_indices``, and adjacent water) into the flat ``facts`` dict the grammar fills. Also
provides the per-biome geographic words used as region-name descriptors ("Wood", "Peaks", ...).
"""

from __future__ import annotations

import random
from typing import Dict, List

from ..world.entities import Region
from ..world.tile import WATER_BIOMES, Biome, POIType, WaterType
from ..world.world import World
from .cultures import Culture

# Natural-language word for each biome (used in lore prose).
BIOME_WORD: Dict[int, str] = {
    int(Biome.DEEP): "sea",
    int(Biome.SHALLOW): "shallows",
    int(Biome.SEAICE): "ice",
    int(Biome.LAKE): "lake",
    int(Biome.BEACH): "shore",
    int(Biome.GRASS): "grassland",
    int(Biome.SAVANNA): "savanna",
    int(Biome.FOREST): "forest",
    int(Biome.JUNGLE): "jungle",
    int(Biome.TAIGA): "boreal forest",
    int(Biome.DESERT): "desert",
    int(Biome.TUNDRA): "tundra",
    int(Biome.SWAMP): "wetland",
    int(Biome.SNOW): "snowfields",
}

# Geographic descriptor words appended to region names, by dominant biome.
GEO_WORDS: Dict[int, List[str]] = {
    int(Biome.FOREST): ["Wood", "Forest", "Wilds"],
    int(Biome.JUNGLE): ["Jungle", "Wilds", "Tangle"],
    int(Biome.TAIGA): ["Pinewood", "Taiga", "Wood"],
    int(Biome.SWAMP): ["Marsh", "Fen", "Mire"],
    int(Biome.GRASS): ["Plains", "Vale", "Downs"],
    int(Biome.SAVANNA): ["Savanna", "Plains", "Flats"],
    int(Biome.DESERT): ["Sands", "Waste", "Dunes"],
    int(Biome.TUNDRA): ["Tundra", "Reach", "Barrens"],
    int(Biome.SNOW): ["Frostlands", "Wastes", "Reach"],
    int(Biome.BEACH): ["Shore", "Coast", "Strand"],
    int(Biome.LAKE): ["Lakeland", "Marches"],
}

_CIVIL = (POIType.CITY, POIType.TOWN, POIType.VILLAGE)
_WILD = (POIType.TOWER, POIType.DUNGEON, POIType.RUIN, POIType.CAMP, POIType.BRIDGE)
_NUMBER = {1: "a", 2: "two", 3: "three"}

_SINGULAR = {
    POIType.CITY: "city",
    POIType.TOWN: "town",
    POIType.VILLAGE: "village",
    POIType.TOWER: "tower",
    POIType.DUNGEON: "dungeon",
    POIType.RUIN: "ruin",
    POIType.CAMP: "camp",
    POIType.BRIDGE: "bridge",
}
_PLURAL = {
    POIType.CITY: "cities",
    POIType.TOWN: "towns",
    POIType.VILLAGE: "villages",
    POIType.TOWER: "towers",
    POIType.DUNGEON: "dungeons",
    POIType.RUIN: "ruin",
    POIType.CAMP: "camps",
    POIType.BRIDGE: "bridges",
}


def geo_word(rng: random.Random, biome_class: int) -> str:
    """Pick a geographic descriptor word for a region's dominant biome (e.g. 'Wood', 'Peaks')."""
    return rng.choice(GEO_WORDS.get(int(biome_class), ["Region", "Land"]))


def size_bucket(size: int) -> str:
    """Bucket a region's tile count into a descriptive size adjective."""
    if size < 30:
        return "small"
    if size < 90:
        return "modest"
    if size < 220:
        return "broad"
    return "vast"


def _noun(kind: POIType, count: int) -> str:
    """Return a number-word + (pluralised) noun, e.g. (village,3) -> 'three villages'."""
    word = (_PLURAL.get(kind)) if count != 1 else _SINGULAR.get(kind)
    qty = _NUMBER.get(count, "several")
    return f"{qty} {word}"


def _phrase(parts: List[str]) -> str:
    """Join phrases with commas and a trailing 'and'."""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def settlement_phrase(world: World, region: Region) -> str:
    """Describe the POIs a region contains, e.g. 'a town and three villages, and an old ruin'."""
    from collections import Counter

    counts: Counter = Counter()
    for i in sorted(region.poi_indices):
        if 0 <= i < len(world.pois):
            counts[world.pois[i].kind] += 1
    civ = [_noun(k, counts[k]) for k in _CIVIL if counts[k]]
    wild = [_noun(k, counts[k]) for k in _WILD if counts[k]]
    if civ and wild:
        return _phrase(civ) + ", and " + _phrase(wild)
    elif civ:
        return _phrase(civ)
    elif wild:
        return _phrase(wild)
    return "no permanent settlements"


def water_phrase(world: World, region: Region) -> str:
    """Describe a region's relationship to water, by inspecting its tiles' neighbours."""
    x0, y0, x1, y1 = region.bbox
    has_river = has_lake = coastal = False
    biome = world.biome
    wt = world.water_type
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if world.region_id[y, x] != region.id:
                continue
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not world.in_bounds(nx, ny):
                    continue
                b = int(biome[ny, nx])
                if wt[ny, nx] == int(WaterType.FRESH) and b not in WATER_BIOMES:
                    has_river = True  # a river is fresh water over a land biome
                elif b == int(Biome.LAKE):
                    has_lake = True
                elif wt[ny, nx] == int(WaterType.SALT):
                    coastal = True
            if has_river and has_lake and coastal:
                break
    if has_river:
        return "A river threads through it"
    if coastal:
        return "Its edges meet the open sea"
    if has_lake:
        return "It cradles a quiet lake"
    return "No great waters cross it"


def extract_facts(world: World, region: Region, culture: Culture, rng: random.Random) -> Dict[str, str]:
    """Build the flat fact dict the lore grammar fills for one region."""
    return {
        "biome": BIOME_WORD.get(int(region.biome_class), "land"),
        "size": size_bucket(region.size),
        "culture_adj": rng.choice(culture.adjectives),
        "settlement_phrase": settlement_phrase(world, region),
        "water_phrase": water_phrase(world, region),
    }
