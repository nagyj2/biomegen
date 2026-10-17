"""The chronicle's ledger: collects events, then sorts and numbers them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from ...config.model import Config
from ...util import rng
from ...world.entities import EVENT_KINDS, NO_LOCATION, ChronicleEvent
from ...world.world import World


class Ledger:
    """Collects events of the kinds ``history.kinds`` enables, then sorts and numbers them."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._enabled = set(config.get("history.kinds"))
        self._pending: list[tuple[int, int, int, ChronicleEvent]] = []

    def enabled(self, kind: str) -> bool:
        """Return whether events of ``kind`` are derived (``history.kinds``)."""
        return kind in self._enabled

    def add(
        self,
        year: int,
        kind: str,
        row: str,
        stream_labels: Sequence[object],
        seed: int,
        *,
        realm_ids: Sequence[int] = (),
        poi_ids: Sequence[int] = (),
        fallen_ids: Sequence[int] = (),
        predecessor_ids: Sequence[int] = (),
        location: tuple[int, int] = NO_LOCATION,
        near_poi: int = -1,
        tags: Sequence[str] = (),
        salience: str = "major",
    ) -> Optional[ChronicleEvent]:
        """Record an event of ``kind`` worded by chronicle row ``row``; None (nothing recorded) when its kind is off."""
        if kind not in self._enabled:
            return None
        stream = rng.derive(seed, "history", "text", kind, *stream_labels)
        rows = self._config.get(f"tables.chronicle.{row}")
        pool = list(rows["templates"]) + (list(rows.get("templates_near", [])) if near_poi >= 0 else [])
        event = ChronicleEvent(
            id=-1,
            year=year,
            kind=kind,
            realm_ids=list(realm_ids),
            poi_ids=list(poi_ids),
            fallen_ids=list(fallen_ids),
            predecessor_ids=list(predecessor_ids),
            location=location,
            near_poi=near_poi,
            template=str(stream.choice(pool)),
            tags=tuple(tags),
            salience=salience,
        )
        self._pending.append((year, EVENT_KINDS.index(kind), len(self._pending), event))
        return event

    @property
    def size(self) -> int:
        """How many events have been recorded (the creation index of the next one)."""
        return len(self._pending)

    def ordered(self) -> list[tuple[tuple[int, int, int], ChronicleEvent]]:
        """Return each recorded event with its sort key ``(year, kind order, creation index)``, in sorted order."""
        return [(item[:3], item[3]) for item in sorted(self._pending, key=lambda item: item[:3])]

    def finish(self, seed: int) -> list[ChronicleEvent]:
        """Return the events oldest first with ``id`` set to their index and a ``month`` each.

        The months of one year are drawn together and sorted, then dealt out in event order, so an event's month never
        precedes an earlier event's and causality within a year holds; the draw is keyed on the year alone.
        """
        events = [event for _, _, _, event in sorted(self._pending, key=lambda item: item[:3])]
        months = int(self._config.get("history.months_per_year"))
        start = 0
        for index, event in enumerate(events):
            event.id = index
            if index + 1 == len(events) or events[index + 1].year != event.year:
                stream = rng.derive(seed, "history", "month", event.year)
                drawn = sorted(stream.randint(1, months) for _ in range(index + 1 - start))
                for placed, month in zip(events[start : index + 1], drawn, strict=True):
                    placed.month = month
                start = index + 1
        return events


def merge_events(world: World, events: Sequence[ChronicleEvent]) -> None:
    """Merge ``events`` (each with its ``year`` and ``month`` set) into the finished chronicle.

    The chronicle stays ordered by ``(year, month)``, an existing event keeping its place before a new one of the same
    month; every event is renumbered and the ids the world keeps (``POI.event_ids``, ``TerritoryChange.event_id`` and
    ``RoadLink.event_id``)
    follow. The new events' ``poi_ids`` are not linked back here: the caller appends each new id to its POIs.
    """
    old = world.chronicle
    order = sorted(
        [(e.year, e.month, 0, i) for i, e in enumerate(old)] + [(e.year, e.month, 1, i) for i, e in enumerate(events)]
    )
    merged = [old[i] if which == 0 else events[i] for _, _, which, i in order]
    remap: dict[int, int] = {}
    for new_id, ((_, _, which, i), event) in enumerate(zip(order, merged, strict=True)):
        if which == 0:
            remap[old[i].id] = new_id
        event.id = new_id
    world.chronicle = merged
    for poi in world.pois:
        poi.event_ids = [remap[i] for i in poi.event_ids]
    for link in world.road_links:
        if link.event_id in remap:
            link.event_id = remap[link.event_id]
    for change in world.territory:
        if change.event_id in remap:
            change.event_id = remap[change.event_id]
