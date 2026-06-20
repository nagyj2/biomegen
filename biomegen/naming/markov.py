"""Order-N character Markov name generator (the alternative to syllable assembly).

Trains a small per-culture model on a curated seed corpus and samples novel, phonotactically-similar
words. Used when ``naming.generators.<category> == 'markov'``; syllable assembly is the default.
Deterministic: all sampling uses the passed seeded ``rng``.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Dict, List

_START = "^"
_END = "$"

# Small seed corpora per culture - enough to give the order-2 model a recognizable flavour.
CORPORA: Dict[str, List[str]] = {
    "common": [
        "ashford",
        "brookton",
        "greenfield",
        "harwick",
        "stonebury",
        "oldham",
        "marsten",
        "rendall",
        "westmere",
        "thornwick",
        "dunbury",
        "felton",
    ],
    "norse": [
        "skarnvik",
        "drakheim",
        "frostby",
        "hjalmstad",
        "svenfjord",
        "bjornness",
        "ulfvik",
        "thorsby",
        "grimfell",
        "snorrheim",
    ],
    "elvish": [
        "aelinor",
        "sylvaria",
        "lothriel",
        "elwyn",
        "faelas",
        "siliriel",
        "ithilmar",
        "naelwyn",
        "vaeloth",
        "elandor",
    ],
    "dwarvish": [
        "khazdim",
        "bramforge",
        "duringar",
        "kraghold",
        "thordelf",
        "gundabarim",
        "zirakdum",
        "baradhold",
        "dhurrak",
    ],
    "southern": ["zaharabad", "khamir", "qasrazah", "sundakar", "mirpur", "shaibad", "razakar", "jahmir", "tazabad"],
}


class MarkovModel:
    """An order-``order`` character Markov chain over a word list."""

    def __init__(self, order: int = 2) -> None:
        self.order = max(1, order)
        self._table: Dict[str, List[str]] = defaultdict(list)

    def train(self, words: List[str]) -> "MarkovModel":
        pad = _START * self.order
        for raw in words:
            w = pad + raw.lower() + _END
            for i in range(len(w) - self.order):
                self._table[w[i : i + self.order]].append(w[i + self.order])
        return self

    def generate(self, rng: random.Random, min_len: int = 4, max_len: int = 12) -> str:
        """Sample a name; retries a bounded number of times to satisfy the length bounds."""
        word = ""
        for _ in range(8):
            ctx = _START * self.order
            out: List[str] = []
            while len(out) < max_len:
                choices = self._table.get(ctx)
                if not choices:
                    break
                ch = rng.choice(sorted(choices))  # sorted -> deterministic given rng
                if ch == _END:
                    break
                out.append(ch)
                ctx = (ctx + ch)[-self.order :]
            word = "".join(out)
            if len(word) >= min_len:
                return word.capitalize()
        return (word or "ar").capitalize()


_MODELS: Dict[tuple, MarkovModel] = {}


def model_for(culture_name: str, order: int) -> MarkovModel:
    """Return a cached trained model for a culture (corpus falls back to 'common' if unknown)."""
    key = (culture_name, order)
    if key not in _MODELS:
        corpus = CORPORA.get(culture_name, CORPORA["common"])
        _MODELS[key] = MarkovModel(order).train(corpus)
    return _MODELS[key]
