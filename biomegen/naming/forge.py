"""The name facade: turn a culture + category (+ kind) into a finished name.

``name_entity`` is the single entry the pipeline calls. It derives a per-entity RNG keyed on stable
identity (so names never depend on processing order), generates a bare *root* (syllable assembly by
default, or order-2 Markov if configured for the category), then applies a category/kind-specific
pattern (settlement suffixes, "Ruins of X", "Lake X", a region's geographic word, ...).
"""

from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

from ..config.model import Config
from ..util import rng
from . import markov, syllables
from .cultures import CULTURES

# Syllable-count ranges per category (roots are shorter for settlements, longer for regions).
_SYLL = {"island": (2, 3), "region": (2, 3), "poi": (1, 2), "river": (2, 2), "lake": (2, 2)}


def _root(
    rng_: random.Random,
    culture_name: str,
    category: str,
    generators_cfg: Optional[Dict[str, str]],
    order: int,
    min_len: int,
    max_len: int,
) -> str:
    gen = (generators_cfg or {}).get(category, "syllable")
    if gen == "markov":
        return markov.model_for(culture_name, order).generate(rng_, min_len, max_len)
    return syllables.assemble(rng_, CULTURES[culture_name], _SYLL.get(category, (2, 3)), min_len, max_len)


def name_entity(
    seed: int,
    category: str,
    key: Tuple,
    culture_name: str,
    generators_cfg: Optional[Dict[str, str]],
    naming_cfg: Optional[Config],
    kind: Optional[str] = None,
    civilized: bool = False,
    descriptor: Optional[str] = None,
) -> str:
    """Return a finished name for one entity.

    Parameters
    ----------
    category : 'island' | 'region' | 'poi' | 'river' | 'lake'
    key      : a tuple of ints uniquely + stably identifying the entity (region id, POI (x,y), ...).
    descriptor : optional geographic word for regions (e.g. 'Wood', 'Peaks').
    """
    r = rng.derive(seed, "naming", category, *key)
    profile = CULTURES.get(culture_name, CULTURES["common"])
    order = int(naming_cfg.get("markov_order", 2)) if naming_cfg else 2
    min_len = int(naming_cfg.get("min_name_len", 4)) if naming_cfg else 4
    max_len = int(naming_cfg.get("max_name_len", 12)) if naming_cfg else 12
    if min_len > max_len:
        min_len = max_len
    root = _root(r, profile.name, category, generators_cfg, order, min_len, max_len)

    if category == "island":
        return root if r.random() < 0.5 else f"{root} Isle"

    if category == "region":
        if descriptor and r.random() < 0.75:
            return f"{root} {descriptor}"
        return root

    if category == "river":
        return f"{root}{r.choice(profile.nature)}".capitalize() if r.random() < 0.5 else f"{root} River"

    if category == "lake":
        return r.choice([f"Lake {root}", f"{root} Lake", f"{root}{r.choice(profile.nature)}".capitalize()])

    # POIs.
    if civilized:
        return f"{root}{r.choice(profile.settlement)}".capitalize()
    if kind == "tower":
        return r.choice([f"{root} {r.choice(profile.fort)}", f"{profile.fort[0]} of {root}"])
    if kind == "dungeon":
        return r.choice([f"{root} Depths", f"{root} Catacombs", f"Tomb of {root}", f"{root} Deep"])
    if kind == "ruins":
        return r.choice([f"Ruins of {root}", f"{root} Ruins", f"Old {root}"])
    if kind == "camp":
        return r.choice([f"{root} Camp", f"{root} Hollow", f"{root} Rest"])
    if kind == "boat":
        return r.choice([f"The {root}", f"{root}"])
    return root
