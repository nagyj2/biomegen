"""Syllable-assembly name generator.

Builds a pronounceable root by stringing together ``onset + nucleus + coda`` syllables drawn from a
:class:`~biomegen.naming.cultures.Culture`. Tight control over the phoneme sets gives each culture a
distinct sound. Deterministic: every draw comes from the passed ``rng`` (a seeded ``random.Random``).
"""

from __future__ import annotations

import random

from .cultures import Culture


def assemble(
    rng: random.Random,
    culture: Culture,
    syllables: tuple[int, int] = (2, 3),
    min_len: int = 4,
    max_len: int = 12,
) -> str:
    """Return a capitalized root word of ``syllables`` (low,high) syllables within the length bounds."""
    lo, hi = syllables
    n = rng.randint(min(lo, hi), max(lo, hi))
    word = ""
    for _i in range(n):
        onset = rng.choice(culture.onsets) if rng.random() < 0.90 else ""
        # Avoid vowel pile-ups across syllable boundaries: if the word so far ends in a vowel and
        # this syllable would start with one, force a consonant onset.
        if word and word[-1] in "aeiou" and (onset == "" or onset[0] in "aeiou"):
            onset = rng.choice(culture.onsets)
        nucleus = rng.choice(culture.nuclei)
        coda = rng.choice(culture.codas) if rng.random() < 0.40 else ""
        syl = onset + nucleus + coda
        # Stop on a syllable boundary rather than truncating mid-syllable (keeps names clean).
        if word and len(word) + len(syl) > max_len:
            break
        word += syl

    # Pad short words with an extra nucleus(+coda) syllable; bounded so it can't loop forever.
    guard = 0
    while len(word) < max(1, min_len) and guard < 3:
        word += rng.choice(culture.nuclei) + (rng.choice(culture.codas) if rng.random() < 0.4 else "")
        guard += 1
    return word.capitalize()
