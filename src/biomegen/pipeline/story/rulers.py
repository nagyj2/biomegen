"""Ruling styles and the successions that change them, abstracted from real lifetimes.

Each living realm is founded under a ruling style drawn from ``tables.ruling_styles``. Successions then fall every
``history.succession_years`` years (a [min, max] gap) until the present, and at each the style changes with
``history.succession_change_chance``. Only a change is an event (a ``succession`` tagged ``from:<old>`` and
``to:<new>``); a succession that keeps the style is silent, so the chronicle does not fill with rulers dying. The last
style held is ``Realm.ruling_style``. The timelines it returns tell the conflicts a realm's style in any year, as a
strength multiplier.
"""

from __future__ import annotations

import bisect
import random

from ...config.model import Config
from ...util import rng
from ...world.world import World
from .ledger import Ledger

StyleTimeline = list[tuple[int, str]]  # (year the style began, style name), oldest first


def _draw_style(stream: random.Random, names: list[str], weights: list[float]) -> str:
    """Pick a style by weight; ``names`` is in a fixed (sorted) order."""
    pick = stream.random() * sum(weights)
    for name, weight in zip(names, weights, strict=True):
        pick -= weight
        if pick < 0:
            return name
    return names[-1]


def style_at(timeline: StyleTimeline, year: int) -> str:
    """Return the style held in ``year`` (the first style before the realm's first entry)."""
    index = bisect.bisect_right([start for start, _ in timeline], year) - 1
    return timeline[max(index, 0)][1]


def derive(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> dict[int, StyleTimeline]:
    """Give every realm its ruling style over time, add the succession events, and return the timelines by realm id."""
    rows = config.get("tables.ruling_styles")
    names = sorted(rows)
    weights = {name: float(rows[name]["weight"]) for name in names}
    gap_lo, gap_hi = (int(v) for v in config.get("history.succession_years"))
    change_chance = float(config.get("history.succession_change_chance"))
    timelines: dict[int, StyleTimeline] = {}
    for realm in world.realms:
        stream = rng.derive(seed, "history", "rule", realm.id)
        style = _draw_style(stream, names, [weights[name] for name in names])
        timeline: StyleTimeline = [(realm.founded, style)]
        year = realm.founded
        while True:
            year += stream.randint(gap_lo, gap_hi)
            change_roll = stream.random()  # both rolls are always drawn, so the stream stays aligned
            other = _draw_style(stream, [n for n in names if n != style], [weights[n] for n in names if n != style])
            if year > span:
                break
            if change_roll < change_chance:
                ledger.add(
                    year,
                    "succession",
                    "succession",
                    (realm.id, len(timeline)),
                    seed,
                    realm_ids=[realm.id],
                    tags=(f"from:{style}", f"to:{other}"),
                )
                style = other
                timeline.append((year, style))
        realm.ruling_style = style
        timelines[realm.id] = timeline
    return timelines
