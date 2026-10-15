"""Culture profiles + biome-biased culture assignment for mixed-per-realm naming.

Each :class:`Culture` carries the phonetic building blocks (onsets / nuclei / codas) and the affixes
used to turn a bare root into a settlement, fort, or water name.
``BIOME_CULTURE_WEIGHTS`` biases which cultures appear in which terrain (elves in forests, dwarves in
mountains, a southern people in deserts, ...), and :func:`culture_for_realm` makes the choice
deterministically from the realm's stable id.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List

from ..world.entities import Realm
from ..world.tile import Biome


@dataclass(frozen=True)
class Culture:
    name: str  # culture id, e.g. "norse"
    onsets: List[str]  # leading consonant clusters for a syllable
    nuclei: List[str]  # vowel cores of a syllable
    codas: List[str]  # trailing consonant clusters (often empty)
    settlement: List[str]  # suffixes for civilized POIs (city/town/village)
    nature: List[str]  # suffixes for rivers/lakes
    fort: List[str]  # words for towers/keeps/ruin


CULTURES: Dict[str, Culture] = {
    "common": Culture(
        "common",
        onsets=["b", "br", "d", "f", "g", "gr", "h", "k", "l", "m", "n", "r", "s", "st", "t", "th", "w"],
        nuclei=["a", "e", "i", "o", "u", "ai", "ea", "ou"],
        codas=["", "ld", "n", "r", "rk", "st", "th", "m", "ll", "nd"],
        settlement=["ton", "ham", "ford", "bury", "field", "wick", "stead", "borough"],
        nature=["water", "brook", "run", "mere", "bourne"],
        fort=["Keep", "Hold", "Watch", "Tower"],
    ),
    "norse": Culture(
        "norse",
        onsets=["bj", "dr", "fr", "gr", "h", "hj", "kn", "sk", "sn", "st", "sv", "th", "v"],
        nuclei=["a", "o", "u", "au", "ja", "y", "ei"],
        codas=["", "fell", "rk", "nd", "ll", "gr", "rn", "n", "r"],
        settlement=["vik", "by", "stad", "heim", "fjord", "ness"],
        nature=["foss", "elv", "vatn"],
        fort=["Barrow", "Hall", "Howe", "Hold"],
    ),
    "elvish": Culture(
        "elvish",
        onsets=["l", "s", "th", "v", "f", "gl", "n", "ph", "sy", "ly", "r", "m", "ll"],
        nuclei=["a", "e", "i", "ae", "ia", "y"],
        codas=["", "l", "n", "r", "th", "s", "ll", "el", "wen"],
        settlement=["loth", "riel", "wyn", "las", "dor", "mar", "thel"],
        nature=["sil", "wen", "loth", "fae"],
        fort=["Spire", "Bower", "Court", "Tower"],
    ),
    "dwarvish": Culture(
        "dwarvish",
        onsets=["b", "br", "d", "dr", "g", "gr", "k", "kh", "th", "dh", "z", "bz"],
        nuclei=["a", "o", "u", "au", "ou"],
        codas=["", "dim", "rak", "run", "dur", "gar", "z", "mn", "k"],
        settlement=["delf", "forge", "hold", "dim", "barim", "dum"],
        nature=["kal", "durin", "zir"],
        fort=["Forge", "Vault", "Gate", "Tower"],
    ),
    "southern": Culture(
        "southern",
        onsets=["z", "zh", "k", "kh", "q", "s", "sh", "m", "r", "h", "t", "d", "j"],
        nuclei=["a", "aa", "i", "u", "ai", "au", "ia"],
        codas=["", "r", "n", "m", "kar", "zah", "d", "sh"],
        settlement=["abad", "kar", "mir", "zah", "pur", "bad"],
        nature=["wadi", "ain", "nahr"],
        fort=["Citadel", "Ribat", "Tower", "Qasr"],
    ),
}

_UNIFORM = {name: 1.0 for name in CULTURES}

# Per-biome culture weighting (keys are Biome ints). Absent biomes fall back to uniform.
BIOME_CULTURE_WEIGHTS: Dict[int, Dict[str, float]] = {
    int(Biome.FOREST): {"elvish": 4, "common": 2, "norse": 1},
    int(Biome.JUNGLE): {"elvish": 3, "southern": 2, "common": 1},
    int(Biome.TAIGA): {"norse": 4, "dwarvish": 2, "common": 1},
    int(Biome.SWAMP): {"common": 2, "elvish": 1, "southern": 1},
    int(Biome.GRASS): {"common": 4, "norse": 1, "elvish": 1},
    int(Biome.SAVANNA): {"southern": 4, "common": 1},
    int(Biome.DESERT): {"southern": 5},
    int(Biome.TUNDRA): {"norse": 3, "dwarvish": 2},
    int(Biome.SNOW): {"dwarvish": 4, "norse": 2},
    int(Biome.BEACH): {"common": 2, "norse": 1, "southern": 1},
    int(Biome.LAKE): {"common": 1, "elvish": 1},
}


def weighted_choice(rng: random.Random, weights: Dict[str, float]) -> str:
    """Deterministically pick a key from ``weights`` (keys iterated in sorted order)."""
    items = sorted(weights.items())
    total = sum(w for _k, w in items)
    if total <= 0:
        return items[0][0]
    r = rng.random() * total
    cum = 0.0
    for key, w in items:
        cum += w
        if r < cum:
            return key
    return items[-1][0]  # float-slack guard


def culture_for_realm(seed: int, realm: Realm) -> str:
    """Assign a culture to a realm: biome-biased weighted choice seeded on the realm's id."""
    from ..util import rng as rngmod

    weights = BIOME_CULTURE_WEIGHTS.get(int(realm.dominant_biome), _UNIFORM)
    return weighted_choice(rngmod.derive(seed, "naming.culture", "realm", realm.id), weights)


def culture_for_site(seed: int, biome: int, key: int) -> str:
    """Assign a culture to something with no realm (a fallen one): biome-biased choice seeded on ``key``."""
    from ..util import rng as rngmod

    return weighted_choice(
        rngmod.derive(seed, "naming.culture", "fallen", key), BIOME_CULTURE_WEIGHTS.get(biome, _UNIFORM)
    )
