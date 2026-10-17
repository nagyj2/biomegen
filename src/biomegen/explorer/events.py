"""The one place the explorer's panel reads events from.

Today that is the generated chronicle; a later simulation's ledger joins it here (one composite reader), so the panel
never reads ``World.chronicle`` itself. A reader answers three questions: what happened at a tile, to a realm, and up
to a year.
"""

from __future__ import annotations

from typing import Protocol

from ..world.entities import ChronicleEvent
from ..world.world import World


class EventReader(Protocol):
    """What the panel asks of the events of a world."""

    def at(self, x: int, y: int) -> list[ChronicleEvent]:
        """Events at tile ``(x, y)`` or naming the settlement there, oldest first."""
        ...

    def of_realm(self, realm_id: int) -> list[ChronicleEvent]:
        """Events that name realm ``realm_id``, oldest first."""
        ...

    def until(self, year: int) -> list[ChronicleEvent]:
        """Events dated ``year`` or earlier, oldest first."""
        ...


class ChronicleReader:
    """The generated chronicle of a world."""

    def __init__(self, world: World) -> None:
        self._world = world

    def at(self, x: int, y: int) -> list[ChronicleEvent]:
        return self._world.events_at(x, y)

    def of_realm(self, realm_id: int) -> list[ChronicleEvent]:
        return self._world.events_of(realm_id)

    def until(self, year: int) -> list[ChronicleEvent]:
        return self._world.events_until(year)


def event_line(event: ChronicleEvent) -> str:
    """One event as ``year  kind  text`` (what the panel lists)."""
    return f"{event.year:>5}  {event.kind:<9}  {event.text}"
