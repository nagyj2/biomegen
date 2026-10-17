"""Which wars were being fought at a moment, read from the chronicle.

A war between two realms starts at its ``war`` event and ends at the ``peace`` event of the same pair (an older war),
at the ``conquest`` that wins a vassal (a war tagged ``conquest``), or not before the present (an ongoing war). Wars
with a fallen realm are not listed: a fallen realm has no front.
"""

from __future__ import annotations

from typing import Optional

from .entities import ChronicleEvent
from .world import World

Stop = tuple[int, int]  # (year, month)


def war_end(world: World, war: ChronicleEvent) -> Optional[ChronicleEvent]:
    """Return the event that ended ``war`` (its peace, or the conquest that won a vassal); ``None`` while it goes on."""
    pair, start = set(war.realm_ids), (war.year, war.month)
    closing = "conquest" if "conquest" in war.tags else "peace"
    return next(
        (e for e in world.chronicle if e.kind == closing and set(e.realm_ids) == pair and (e.year, e.month) >= start),
        None,
    )


def war_intervals(world: World) -> list[tuple[int, int, Stop, Optional[Stop]]]:
    """Return ``(attacker, defender, start, end)`` of every war between two realms, oldest first; ``end`` is ``None``
    for a war that is still going."""
    wars = []
    for event in world.chronicle:
        if event.kind != "war" or event.fallen_ids or len(event.realm_ids) != 2:
            continue
        closing = war_end(world, event)
        end = (closing.year, closing.month) if closing is not None else None
        wars.append((event.realm_ids[0], event.realm_ids[1], (event.year, event.month), end))
    return wars


def wars_at(world: World, moment: Stop) -> list[tuple[int, int]]:
    """Return the ``(attacker, defender)`` realm pairs at war at ``moment`` (a war holds from its start to just
    before its end)."""
    return [(a, b) for a, b, start, end in war_intervals(world) if start <= moment and (end is None or moment < end)]
