"""The one place the explorer's panel reads events from.

Today that is the generated chronicle; a later simulation's events join it through the composite reader
(:class:`~biomegen.world.ledger.EventLog`), so the panel never reads ``World.chronicle`` itself. A reader answers three
questions: what happened at a tile, to a realm, and up to a year.
"""

from __future__ import annotations

from typing import Optional, Protocol

from ..world.chronicle import event_when
from ..world.entities import ChronicleEvent
from ..world.ledger import EventLog
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
    """The events of a world, read through its :class:`~biomegen.world.ledger.EventLog` (the generated chronicle, and a
    simulation's events once it appends any)."""

    def __init__(self, world: World, log: Optional[EventLog] = None) -> None:
        self._log = EventLog(world) if log is None else log

    def at(self, x: int, y: int) -> list[ChronicleEvent]:
        return self._log.at(x, y)

    def of_realm(self, realm_id: int) -> list[ChronicleEvent]:
        return self._log.of_realm(realm_id)

    def until(self, year: int) -> list[ChronicleEvent]:
        return self._log.until(year)


def event_line(event: ChronicleEvent) -> str:
    """One event as ``year/month  kind  text`` (what the panel lists)."""
    return f"{event_when(event)}  {event.kind:<9}  {event.text}"
