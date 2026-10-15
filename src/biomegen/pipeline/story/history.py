"""Stage: history - a chronicle derived from the finished political state, with no tick simulation.

Everything is placed from static quantities, so the same world always gives the same history:

1. **Founding.** Every realm is founded ``age`` years before the present, the age drawn from its kind's
   ``history.age_range`` and pulled toward the old end by a larger area (``history.age_area_weight``). A seated realm's
   founding is also its seat's; a capital's event carries the tag ``capital``.
2. **Settling.** Every civilized POI is dated: a seat with its realm, any other settlement some time after its realm
   (at least ``history.min_gap_years``), a settlement on wild land from the ``tribal`` age range. The kinds in
   ``history.settle_kinds`` also get a ``settling`` event.
3. **Conquest.** Every vassal tie is one event, after both realms exist plus ``history.min_gap_years``.

Events are collected in a :class:`Ledger`, sorted by ``(year, kind order, creation order)`` and numbered, so an event's
``id`` is its index in ``World.chronicle``. An event holds a raw template picked from ``tables.chronicle`` (its
``templates_near`` only when a settlement qualifies as near, see :mod:`.places`); the naming stage renders its text.
Every draw is a ``history`` sub-stream keyed on the entity, so the result does not depend on dict or set order.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...config.model import Config
from ...util import rng
from ...world.entities import EVENT_KINDS, NO_LOCATION, ChronicleEvent
from ...world.world import World
from .places import nearest_settlement


class Ledger:
    """Collects events of the kinds ``history.kinds`` enables, then sorts and numbers them."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._enabled = set(config.get("history.kinds"))
        self._pending: list[tuple[int, int, int, ChronicleEvent]] = []

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
        location: tuple[int, int] = NO_LOCATION,
        near_poi: int = -1,
        tags: Sequence[str] = (),
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
            location=location,
            near_poi=near_poi,
            template=str(stream.choice(pool)),
            tags=tuple(tags),
        )
        self._pending.append((year, EVENT_KINDS.index(kind), len(self._pending), event))

    def finish(self) -> list[ChronicleEvent]:
        """Return the events oldest first with ``id`` set to their index."""
        events = [event for _, _, _, event in sorted(self._pending, key=lambda item: item[:3])]
        for index, event in enumerate(events):
            event.id = index
        return events


def _realm_founding_years(world: World, config: Config, seed: int, span: int) -> None:
    """Set ``Realm.founded`` for every realm: older when the kind's age range and the realm's area say so."""
    weight = float(config.get("history.age_area_weight"))
    by_area = sorted(world.realms, key=lambda realm: (-realm.area_km2, realm.id))
    last = max(len(by_area) - 1, 1)
    area_share = {realm.id: 1.0 - n / last for n, realm in enumerate(by_area)}  # the largest realm is 1.0
    for realm in world.realms:
        lo, hi = (float(v) for v in config.get(f"history.age_range.{realm.kind}"))
        share = (1.0 - weight) * rng.derive(seed, "history", "age", realm.id).random() + weight * area_share[realm.id]
        realm.founded = span - round((lo + share * (hi - lo)) * span)


def _settlement_founding_years(world: World, config: Config, seed: int, span: int) -> None:
    """Set ``POI.founded`` for every civilized POI; leave other POIs undated (0)."""
    gap = int(config.get("history.min_gap_years"))
    lo_age, hi_age = (float(v) for v in config.get("history.age_range.tribal"))
    for index, poi in enumerate(world.pois):
        if not poi.civilized:
            continue
        roll = rng.derive(seed, "history", "poi", index).random()
        realm = world.realms[poi.realm_id] if poi.realm_id >= 0 else None
        if realm is None:  # settled on wild land: as old as a tribe's range says
            poi.founded = span - round((lo_age + roll * (hi_age - lo_age)) * span)
        elif realm.seat_poi == index:
            poi.founded = realm.founded
        else:
            first = min(realm.founded + gap, span)
            poi.founded = min(first + int(roll * (span - first + 1)), span)


def _realm_events(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> None:
    """Add the founding, settling and conquest events."""
    gap = int(config.get("history.min_gap_years"))
    settle_kinds = set(config.get("history.settle_kinds"))
    for realm in world.realms:
        seat = realm.seat_poi
        poi = world.pois[seat] if seat >= 0 else None
        ledger.add(
            realm.founded,
            "founding",
            "founding",
            (realm.id,),
            seed,
            realm_ids=[realm.id],
            poi_ids=[seat] if poi else [],
            location=(poi.x, poi.y) if poi else NO_LOCATION,
            near_poi=nearest_settlement(world, config, poi.x, poi.y, (seat,)) if poi else -1,
            tags=(realm.kind, "capital") if poi and poi.kind == "capital" else (realm.kind,),
        )
    seats = {realm.seat_poi for realm in world.realms}
    for index, poi in enumerate(world.pois):
        if poi.civilized and poi.kind in settle_kinds and poi.realm_id >= 0 and index not in seats:
            ledger.add(
                poi.founded,
                "settling",
                "settling",
                (index,),
                seed,
                realm_ids=[poi.realm_id],
                poi_ids=[index],
                location=(poi.x, poi.y),
                near_poi=nearest_settlement(world, config, poi.x, poi.y, (index,)),
                tags=(poi.kind,),
            )
    for realm in world.realms:
        if realm.liege < 0:
            continue
        liege = world.realms[realm.liege]
        first = min(max(realm.founded, liege.founded) + gap, span)
        year = min(first + int(rng.derive(seed, "history", "conquest", realm.id).random() * (span - first + 1)), span)
        ledger.add(year, "conquest", "conquest", (realm.id,), seed, realm_ids=[realm.id, liege.id], tags=("vassalage",))


def run(world: World, config: Config, seed: int) -> None:
    """Date the realms and settlements and derive ``world.chronicle``, mutating ``world`` in place."""
    span = int(config.get("history.span_years"))
    world.year = span
    _realm_founding_years(world, config, seed, span)
    _settlement_founding_years(world, config, seed, span)
    ledger = Ledger(config)
    _realm_events(world, config, seed, span, ledger)
    world.chronicle = ledger.finish()
