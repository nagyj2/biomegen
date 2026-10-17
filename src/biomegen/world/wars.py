"""Which wars were being fought at a moment, read from the chronicle.

A war between two realms starts at its ``war`` event and ends at the ``peace`` event of the same pair (an older war),
at the ``conquest`` that wins a vassal (a war tagged ``conquest``), or not before the present (an ongoing war). Wars
with a fallen realm are not listed: a fallen realm has no front.
"""

from __future__ import annotations

from typing import Optional

from .world import World

Stop = tuple[int, int]  # (year, month)


def war_intervals(world: World) -> list[tuple[int, int, Stop, Optional[Stop]]]:
    """Return ``(attacker, defender, start, end)`` of every war between two realms, oldest first; ``end`` is ``None``
    for a war that is still going."""
    events = world.chronicle
    wars = []
    for event in events:
        if event.kind != "war" or event.fallen_ids or len(event.realm_ids) != 2:
            continue
        start, pair = (event.year, event.month), set(event.realm_ids)
        closing = "conquest" if "conquest" in event.tags else "peace"
        end = next(
            (
                (e.year, e.month)
                for e in events
                if e.kind == closing and set(e.realm_ids) == pair and (e.year, e.month) >= start
            ),
            None,
        )
        wars.append((event.realm_ids[0], event.realm_ids[1], start, end))
    return wars


def wars_at(world: World, moment: Stop) -> list[tuple[int, int]]:
    """Return the ``(attacker, defender)`` realm pairs at war at ``moment`` (a war holds from its start to just
    before its end)."""
    return [(a, b) for a, b, start, end in war_intervals(world) if start <= moment and (end is None or moment < end)]
