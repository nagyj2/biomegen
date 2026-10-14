"""A tiny Tracery-style expansion engine for region lore.

Rules live in ``grammar_rules.toml``. :func:`expand` recursively replaces ``#symbol#`` tokens: a token
that names a grammar symbol expands to one of its (randomly chosen) templates; any other token is a
*fact* and is replaced by the value the lore stage bound (or dropped if absent). :func:`render_lore`
samples a few top-level sentences and renders them into clean prose. All randomness flows from the
passed seeded ``rng``, so lore is reproducible and order-independent.
"""

from __future__ import annotations

import random
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_TOKEN = re.compile(r"#([a-z_]+)#")
_MAX_DEPTH = 8
_RULES_PATH = Path(__file__).with_name("grammar_rules.toml")


@lru_cache(maxsize=1)
def load_rules() -> Dict[str, List[str]]:
    """Load and cache the lore grammar's ``[lore]`` table from ``grammar_rules.toml``."""
    with _RULES_PATH.open("rb") as fh:
        return tomllib.load(fh)["lore"]


def expand(rng: random.Random, rules: Dict[str, List[str]], symbol: str, facts: Dict[str, str], depth: int = 0) -> str:
    """Recursively expand a grammar ``symbol`` (or fact) into text."""
    if depth > _MAX_DEPTH:
        return ""
    if symbol in rules:
        template = rng.choice(rules[symbol])
        return _TOKEN.sub(lambda m: expand(rng, rules, m.group(1), facts, depth + 1), template)
    # Not a grammar symbol -> treat as a fact terminal (empty string if unknown).
    return str(facts.get(symbol, ""))


def render_lore(
    rng: random.Random,
    rules: Dict[str, List[str]],
    facts: Dict[str, str],
    lore_min: int,
    lore_max: int,
) -> List[str]:
    """Render ``[lore_min, lore_max]`` balanced sentences for one region from its facts."""
    pool = list(rules.get("_sentences", []))
    if not pool:
        return []
    count = rng.randint(min(lore_min, lore_max), max(lore_min, lore_max))
    count = max(1, min(count, len(pool)))
    chosen = rng.sample(sorted(pool), count)  # sorted copy -> deterministic given rng

    out: List[str] = []
    for symbol in chosen:
        text = expand(rng, rules, symbol, facts).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        text = text[0].upper() + text[1:]
        if text[-1] not in ".!?":
            text += "."
        out.append(text)

    # Guarantee at least lore_min sentences if some expanded empty (fall back to the overview symbol).
    while len(out) < min(lore_min, len(pool)) and "overview" in rules:
        text = expand(rng, rules, "overview", facts).strip()
        if text:
            out.append(text[0].upper() + text[1:] + ("" if text[-1] in ".!?" else "."))
        else:
            break
    return out
