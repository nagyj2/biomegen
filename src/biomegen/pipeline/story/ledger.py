"""The chronicle's ledger: collects events, then sorts and numbers them."""

from __future__ import annotations

from collections.abc import Sequence

from ...config.model import Config
from ...util import rng
from ...world.entities import EVENT_KINDS, NO_LOCATION, ChronicleEvent


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
    ) -> None:
        """Record an event of ``kind`` worded by chronicle row ``row``; skipped when its kind is switched off."""
        if kind not in self._enabled:
            return
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

    def finish(self) -> list[ChronicleEvent]:
        """Return the events oldest first with ``id`` set to their index."""
        events = [event for _, _, _, event in sorted(self._pending, key=lambda item: item[:3])]
        for index, event in enumerate(events):
            event.id = index
        return events
