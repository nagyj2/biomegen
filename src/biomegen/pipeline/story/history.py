"""Stage: history - a chronicle derived from the finished political state, with no tick simulation.

Everything is placed from static quantities, so the same world always gives the same history:

1. **Founding.** Every realm is founded ``age`` years before the present, the age drawn from its kind's
   ``history.age_range`` and pulled toward the old end by a larger area (``history.age_area_weight``). A seated realm's
   founding is also its seat's; a capital's event carries the tag ``capital``.
2. **Settling.** Every civilized POI is dated: a seat with its realm, any other settlement some time after its realm
   (at least ``history.min_gap_years``), a settlement on wild land from the ``tribal`` age range. The kinds in
   ``history.settle_kinds`` also get a ``settling`` event.
3. **Conquest.** Every vassal tie is one event, after both realms exist plus ``history.min_gap_years``.
4. **Relations.** Every relation between two independent powers is one event: a war (``ongoing``, attacker first,
   the claimed town in ``poi_ids``), a rivalry or a treaty (tagged ``alliance`` or ``trade``). It began some years
   before the present, more for a longer shared border (``history.war_years`` or ``other_years``, up to
   ``history.border_km_for_full_span``), but never before both powers exist plus ``history.min_gap_years``.
5. **Battles.** A war's front sees ``history.battles_per_100km_front`` battles per 100 km of border, each on a cell
   of the front between the war's start and the present; ``realm_ids`` is ``[winner, loser]``.
6. **Falls.** Realms that vanished before the present: ``history.fallen_realms_per_million_km2`` of them, each a
   :class:`~biomegen.world.entities.FallenRealm` on wild land habitable enough to have held a realm
   (``history.fall_min_habitability``), spaced ``history.fall_spacing_km`` from each other and from settlements. A
   ``fall`` event is dated when the realm fell. Without the ``fall`` kind there are no fallen realms.

Events are collected in a :class:`Ledger`, sorted by ``(year, kind order, creation order)`` and numbered, so an event's
``id`` is its index in ``World.chronicle``. An event holds a raw template picked from ``tables.chronicle`` (its
``templates_near`` only when a settlement qualifies as near, see :mod:`.places`); the naming stage renders its text.
Every draw is a ``history`` sub-stream keyed on the entity, so the result does not depend on dict or set order.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ...config.model import Config
from ...util import rng
from ...world.entities import EVENT_KINDS, NO_LOCATION, ChronicleEvent, FallenRealm, Relation
from ...world.tile import WaterType
from ...world.world import World
from ..civilization.diplomacy import front_cells
from ..civilization.settlements import habitability
from ..pois import pick_blue_noise
from .places import nearest_settlement


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


def relation_start_year(span: int, years: Sequence[int], border_km: float, full_km: float, first: int) -> int:
    """Return the year a relation began: ``span`` minus its length, no earlier than ``first``.

    The length runs from ``years[0]`` to ``years[1]`` as the shared border grows to ``full_km``.
    """
    share = min(1.0, max(0.0, border_km / full_km)) if full_km > 0 else 1.0
    length = years[0] + (years[1] - years[0]) * share
    return min(max(span - round(length), first), span)


def _relation_year(world: World, config: Config, span: int, relation: Relation) -> int:
    """Return the year ``relation`` began, from its border length and the founding of both powers."""
    gap = int(config.get("history.min_gap_years"))
    first = min(max(world.realms[relation.a].founded, world.realms[relation.b].founded) + gap, span)
    years = config.get("history.war_years" if relation.kind == "war" else "history.other_years")
    return relation_start_year(
        span, years, relation.border_km, float(config.get("history.border_km_for_full_span")), first
    )


def _relation_events(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> None:
    """Add a war, rivalry or treaty event for every relation."""
    for index, relation in enumerate(world.relations):
        year = _relation_year(world, config, span, relation)
        pair = [relation.a, relation.b]
        if relation.kind == "war":
            attacker = relation.attacker if relation.attacker >= 0 else relation.a
            defender = relation.b if attacker == relation.a else relation.a
            ledger.add(
                year,
                "war",
                "war",
                (index,),
                seed,
                realm_ids=[attacker, defender],
                poi_ids=[relation.claim_poi] if relation.claim_poi >= 0 else [],
                tags=("ongoing",),
            )
        elif relation.kind == "rivalry":
            ledger.add(year, "rivalry", "rivalry", (index,), seed, realm_ids=pair, tags=("rivalry",))
        else:
            ledger.add(year, "treaty", f"treaty_{relation.kind}", (index,), seed, realm_ids=pair, tags=(relation.kind,))


def _battle_events(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> None:
    """Add the battles fought along every war's front."""
    rate = float(config.get("history.battles_per_100km_front"))
    for index, relation in enumerate(world.relations):
        if relation.kind != "war":
            continue
        cells = front_cells(world, relation.a, relation.b).tolist()
        if not cells:
            continue
        began = _relation_year(world, config, span, relation)
        for number in range(round(relation.border_km / 100.0 * rate)):
            stream = rng.derive(seed, "history", "battle", index, number)
            year = min(began + int(stream.random() * (span - began + 1)), span)
            y, x = divmod(cells[stream.randrange(len(cells))], world.width)
            first, second = (relation.a, relation.b) if stream.random() < 0.5 else (relation.b, relation.a)
            ledger.add(
                year,
                "battle",
                "battle",
                (index, number),
                seed,
                realm_ids=[first, second],
                location=(x, y),
                near_poi=nearest_settlement(world, config, x, y),
                tags=("front",),
            )


def _fallen_realms(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> None:
    """Place the fallen realms on wild, habitable land and add a ``fall`` event for each."""
    world.fallen_realms = []
    if not ledger.enabled("fall"):
        return
    land = world.water_type == int(WaterType.NONE)
    count = round(
        float(land.sum()) * world.scale.cell_area_km2 / 1e6 * float(config.get("history.fallen_realms_per_million_km2"))
    )
    score = habitability(world, config, seed)
    eligible = land & (world.realm_id < 0) & (world.landmass_id >= 0) & (world.poi_index < 0)
    eligible &= score >= float(config.get("history.fall_min_habitability"))
    settled = [(poi.x, poi.y) for poi in world.pois if poi.civilized]
    sites = pick_blue_noise(
        np.where(eligible, score, -np.inf), count, float(config.get("history.fall_spacing_km")), settled, world
    )
    life_lo, life_hi = (int(v) for v in config.get("history.fallen_life_years"))
    last_fall = max(span - int(config.get("history.fallen_min_years_ago")), 0)
    for number, (x, y) in enumerate(sites):
        stream = rng.derive(seed, "history", "fallen", number)
        life = min(stream.randint(life_lo, life_hi), last_fall)
        founded = stream.randint(0, last_fall - life)
        world.fallen_realms.append(FallenRealm(id=number, location=(x, y), founded=founded, fell=founded + life))
        ledger.add(
            founded + life,
            "fall",
            "fall",
            (number,),
            seed,
            fallen_ids=[number],
            location=(x, y),
            near_poi=nearest_settlement(world, config, x, y),
        )


def run(world: World, config: Config, seed: int) -> None:
    """Date the realms and settlements and derive ``world.chronicle``, mutating ``world`` in place."""
    span = int(config.get("history.span_years"))
    world.year = span
    _realm_founding_years(world, config, seed, span)
    _settlement_founding_years(world, config, seed, span)
    ledger = Ledger(config)
    _realm_events(world, config, seed, span, ledger)
    _relation_events(world, config, seed, span, ledger)
    _battle_events(world, config, seed, span, ledger)
    _fallen_realms(world, config, seed, span, ledger)
    world.chronicle = ledger.finish()
