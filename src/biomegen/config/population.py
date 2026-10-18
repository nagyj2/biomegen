"""Scaling of the people the tables name: one knob, applied after every draw.

The tables give populations as ranges (``tables.tiers.<tier>.pop``, ``poi.homestead_people``, a realm kind's
``rural_per_km2``) and every stage draws from them. ``settlements.pop_scale`` multiplies what is drawn (and the ranges a
population is measured against), so the numbers can be raised or lowered without changing a single draw: the stream is
consumed exactly as before and any two populations compare as they did, so the world does not change.
"""

from __future__ import annotations

import math

from .model import Config


def pop_scale(config: Config) -> float:
    """Return the factor every population is multiplied by (``settlements.pop_scale``)."""
    return float(config.get("settlements.pop_scale"))


def scaled_people(config: Config, people: float) -> int:
    """Return ``people`` times the population scale, rounded half up (never reordering two whole numbers)."""
    return int(math.floor(people * pop_scale(config) + 0.5))


def tier_pop_range(config: Config, tier: str) -> tuple[int, int]:
    """Return the scaled ``(smallest, largest)`` population of a settlement ``tier``.

    A drawn population is measured against this range (its place in the tier's range).
    """
    low, high = config.get(f"tables.tiers.{tier}.pop")
    return scaled_people(config, int(low)), scaled_people(config, int(high))
