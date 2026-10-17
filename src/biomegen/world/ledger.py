"""The events of a world as one list: the generated chronicle followed by a continuation.

``World.chronicle`` is the derived prehistory and is final once the world is generated. A later simulation emits its own
events after it; :class:`EventLog` reads both as one list, so ``id == index`` holds across them and a reader asks one
object where it used to ask ``World``. The generation's own builder, which collects and numbers the prehistory, is
``biomegen.pipeline.story.ledger.Ledger``; this is the reader above it.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from .entities import ChronicleEvent
from .world import World


class EventLog:
    """The chronicle of ``world`` and the events that continue it, in one list.

    The continuation is appended with :meth:`append`, which numbers each event after every earlier one and refuses to go
    back before the last ``(year, month)``. Build the log after generation: it reads ``world.chronicle`` as it is, so a
    chronicle renumbered later would leave the continuation's ids behind.
    """

    def __init__(self, world: World, extra: Sequence[ChronicleEvent] = ()) -> None:
        self._world = world
        self._extra: list[ChronicleEvent] = []
        for event in extra:
            self.append(event)

    def __len__(self) -> int:
        return len(self._world.chronicle) + len(self._extra)

    def __getitem__(self, index: int) -> ChronicleEvent:
        size = len(self)
        if not -size <= index < size:
            raise IndexError(index)
        index %= size
        base = len(self._world.chronicle)
        return self._world.chronicle[index] if index < base else self._extra[index - base]

    def __iter__(self) -> Iterator[ChronicleEvent]:
        yield from self._world.chronicle
        yield from self._extra

    def append(self, event: ChronicleEvent) -> ChronicleEvent:
        """Add ``event`` after the last one, set its ``id`` to its index and return it.

        Raises:
            ValueError: ``event`` is dated before the last event's ``(year, month)``.
        """
        last = self[-1] if len(self) else None
        if last is not None and (event.year, event.month) < (last.year, last.month):
            raise ValueError(
                f"event dated {event.year}/{event.month} comes before the last one, {last.year}/{last.month}"
            )
        event.id = len(self)
        self._extra.append(event)
        return event

    def at(self, x: int, y: int) -> list[ChronicleEvent]:
        """Return the events located at cell ``(x, y)`` or naming the POI anchored there, oldest first."""
        found = self._world.events_at(x, y)
        poi = int(self._world.poi_index[y, x])
        marked = set(self._world.pois[poi].event_ids) if poi >= 0 else set()
        return found + [e for e in self._extra if e.location == (x, y) or poi in e.poi_ids or e.id in marked]

    def of_realm(self, realm_id: int) -> list[ChronicleEvent]:
        """Return the events that name realm ``realm_id``, oldest first."""
        return self._world.events_of(realm_id) + [e for e in self._extra if realm_id in e.realm_ids]

    def until(self, year: int) -> list[ChronicleEvent]:
        """Return the events dated ``year`` or earlier, oldest first."""
        return self._world.events_until(year) + [e for e in self._extra if e.year <= year]
