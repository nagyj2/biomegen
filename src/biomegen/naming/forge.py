"""The name facade: turn a culture + category (+ kind) into a finished name.

``name_entity`` is the single entry the pipeline calls. It derives a per-entity RNG keyed on stable
identity (so names never depend on processing order), generates a bare *root* (syllable assembly by
default, or order-2 Markov if configured for the category), then applies a category/kind-specific
pattern (settlement suffixes, "Ruins of X", "Lake X", a region's geographic word, ...).
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Dict, Optional, Tuple

from ..config.model import Config
from ..util import rng
from . import markov, syllables
from .cultures import CULTURES

# Syllable-count ranges per category (roots are shorter for settlements, longer for islands).
_SYLL = {
    "island": (2, 3),
    "realm": (1, 2),
    "ruler": (1, 2),
    "poi": (1, 2),
    "river": (2, 2),
    "lake": (2, 2),
}


def _root(
    rng_: random.Random,
    culture_name: str,
    category: str,
    generators_cfg: Optional[Dict[str, str]],
    order: int,
    min_len: int,
    max_len: int,
    syllable_range: Optional[Tuple[int, int]] = None,
) -> str:
    gen = (generators_cfg or {}).get(category, "syllable")
    if gen == "markov":
        return markov.model_for(culture_name, order).generate(rng_, min_len, max_len)
    counts = syllable_range or _SYLL.get(category, (2, 3))
    return syllables.assemble(rng_, CULTURES[culture_name], counts, min_len, max_len)


def _lengths(naming_cfg: Optional[Config]) -> Tuple[int, int, int]:
    """Return ``(markov_order, min_len, max_len)`` from the naming config (with the documented defaults)."""
    order = int(naming_cfg.get("markov_order", 2)) if naming_cfg else 2
    min_len = int(naming_cfg.get("min_name_len", 4)) if naming_cfg else 4
    max_len = int(naming_cfg.get("max_name_len", 12)) if naming_cfg else 12
    return order, min(min_len, max_len), max_len


def name_feature(
    seed: int,
    kind: str,
    key: Tuple,
    culture_name: str,
    row: Dict,
    generators_cfg: Optional[Dict[str, str]],
    naming_cfg: Optional[Config],
) -> str:
    """Return a name for a geographic feature from its ``tables.geo_names`` row (forms + syllables).

    ``key`` stably identifies the feature (its anchor cell), so the name does not depend on the order
    features were found in.
    """
    r = rng.derive(seed, "naming", "feature", kind, *key)
    profile = CULTURES.get(culture_name, CULTURES["common"])
    order, min_len, max_len = _lengths(naming_cfg)
    low, high = (int(v) for v in row["syllables"])
    root = _root(r, profile.name, kind, generators_cfg, order, min_len, max_len, (low, high))
    return str(r.choice(list(row["forms"]))).format(n=root)


def name_entity(
    seed: int,
    category: str,
    key: Tuple,
    culture_name: str,
    generators_cfg: Optional[Dict[str, str]],
    naming_cfg: Optional[Config],
    forms: Optional[Sequence[str]] = None,
    extra: Optional[Mapping[str, str]] = None,
    civilized: bool = False,
) -> str:
    """Return a finished name for one entity.

    Parameters
    ----------
    category : 'island' | 'realm' | 'ruler' | 'poi' | 'river' | 'lake'
    key      : a tuple of ints uniquely + stably identifying the entity (realm id, POI (x,y), ...).
    forms    : for a wild POI, its kind's name patterns (``tables.pois.<kind>.names``): ``{n}`` is the root and
               ``{fort}`` a fort word of the culture; without them the bare root is the name.
    extra    : more tokens for the patterns (a fallen realm's ruin names ``{fallen}``).
    """
    r = rng.derive(seed, "naming", category, *key)
    profile = CULTURES.get(culture_name, CULTURES["common"])
    order, min_len, max_len = _lengths(naming_cfg)
    root = _root(r, profile.name, category, generators_cfg, order, min_len, max_len)

    if category in ("realm", "ruler"):
        return root  # the realm's base word, or a ruler's personal name; the form is picked by naming.polity

    if category == "island":
        return root if r.random() < 0.5 else f"{root} Isle"

    if category == "river":
        return f"{root}{r.choice(profile.nature)}".capitalize() if r.random() < 0.5 else f"{root} River"

    if category == "lake":
        return r.choice([f"Lake {root}", f"{root} Lake", f"{root}{r.choice(profile.nature)}".capitalize()])

    # POIs.
    if civilized:
        return f"{root}{r.choice(profile.settlement)}".capitalize()
    if forms:
        tokens = {"n": root, "fort": r.choice(profile.fort), **(extra or {})}
        return str(r.choice(list(forms))).format(**tokens)
    return root
