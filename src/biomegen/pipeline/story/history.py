"""Stage: history - a chronicle derived from the finished political state, with no tick simulation.

Everything is placed from static quantities, so the same world always gives the same history:

1. **Founding.** Every realm is founded ``age`` years before the present, the age drawn from its kind's
   ``history.age_range`` and pulled toward the old end by a larger area (``history.age_area_weight``); the dates are
   then shifted so the oldest realm is founded in ``history.first_founding_year``. A seated realm's founding is also
   its seat's; a capital's event carries the tag ``capital``.
2. **Settling.** Every civilized POI is dated: a seat with its realm, any other settlement some time after its realm
   (at least ``history.min_gap_years``), a settlement on wild land from the ``tribal`` age range. The kinds in
   ``history.settle_kinds`` also get a ``settling`` event.
3. **Conquest.** Every vassal tie is one event, after both realms exist plus ``history.min_gap_years``.
4. **Fallen realms.** Realms that vanished before the present: ``history.fallen_realms_per_million_km2`` of them, each
   a :class:`~biomegen.world.entities.FallenRealm` on wild land habitable enough to have held a realm
   (``history.fall_min_habitability``), spaced ``history.fall_spacing_km`` from each other and from settlements. Each
   has a founding event; its fall comes from :mod:`.conflicts`. Without the ``fall`` kind there are no fallen realms.
5. **Conflicts** (:mod:`.conflicts`): wars, battles, peace, rivalries, treaties and falls, tracked through time.

Events are collected in a :class:`~.ledger.Ledger`, sorted by ``(year, kind order, creation order)`` and numbered, so
an event's ``id`` is its index in ``World.chronicle``. An event holds a raw template picked from ``tables.chronicle``
(its ``templates_near`` only when a settlement qualifies as near, see :mod:`.places`); the naming stage renders its
text. Every draw is a ``history`` sub-stream keyed on the entity, so the result does not depend on dict or set order.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import rng
from ...world.entities import NO_LOCATION, FallenRealm
from ...world.tile import WaterType
from ...world.world import World
from ..civilization.settlements import habitability
from ..pois import pick_blue_noise
from . import conflicts, rulers
from .ledger import Ledger
from .places import nearest_settlement


def _realm_founding_years(world: World, config: Config, seed: int, span: int) -> None:
    """Set ``Realm.founded`` for every realm, then shift all so the oldest is founded in the first founding year.

    A realm is older when its kind's age range and its area say so; the shift keeps every gap between realms.
    """
    weight = float(config.get("history.age_area_weight"))
    by_area = sorted(world.realms, key=lambda realm: (-realm.area_km2, realm.id))
    last = max(len(by_area) - 1, 1)
    area_share = {realm.id: 1.0 - n / last for n, realm in enumerate(by_area)}  # the largest realm is 1.0
    for realm in world.realms:
        lo, hi = (float(v) for v in config.get(f"history.age_range.{realm.kind}"))
        share = (1.0 - weight) * rng.derive(seed, "history", "age", realm.id).random() + weight * area_share[realm.id]
        realm.founded = span - round((lo + share * (hi - lo)) * span)
    if world.realms:
        shift = min(realm.founded for realm in world.realms) - int(config.get("history.first_founding_year"))
        for realm in world.realms:
            realm.founded -= shift


def _settlement_founding_years(world: World, config: Config, seed: int, span: int) -> None:
    """Set ``POI.founded`` for every civilized POI; leave other POIs undated (0)."""
    gap = int(config.get("history.min_gap_years"))
    first_year = int(config.get("history.first_founding_year"))
    for index, poi in enumerate(world.pois):
        if not poi.civilized:
            continue
        roll = rng.derive(seed, "history", "poi", index).random()
        realm = world.realms[poi.realm_id] if poi.realm_id >= 0 else None
        if realm is None:  # settled on wild land: any time before the present
            poi.founded = first_year + int(roll * (span - first_year + 1))
        elif realm.seat_poi == index:
            poi.founded = realm.founded
        else:
            first = min(realm.founded + gap, span)
            poi.founded = min(first + int(roll * (span - first + 1)), span)


def _place_fallen_realms(world: World, config: Config, seed: int, span: int, enabled: bool) -> None:
    """Place the fallen realms on wild, habitable land with their founding and natural fall years."""
    world.fallen_realms = []
    if not enabled:
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
    first_year = int(config.get("history.first_founding_year"))
    last_fall = max(span - int(config.get("history.fallen_min_years_ago")), first_year)
    for number, (x, y) in enumerate(sites):
        stream = rng.derive(seed, "history", "fallen", number)
        life = min(stream.randint(life_lo, life_hi), last_fall - first_year)
        founded = stream.randint(first_year, last_fall - life)
        world.fallen_realms.append(FallenRealm(id=number, location=(x, y), founded=founded, fell=founded + life))


def _realm_events(world: World, config: Config, seed: int, span: int, ledger: Ledger) -> None:
    """Add the founding (realms and fallen realms), settling and conquest events."""
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
    for fallen in world.fallen_realms:
        ledger.add(
            fallen.founded,
            "founding",
            "founding_fallen",
            ("fallen", fallen.id),
            seed,
            fallen_ids=[fallen.id],
            location=fallen.location,
            near_poi=nearest_settlement(world, config, *fallen.location),
            tags=("fallen",),
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
    _place_fallen_realms(world, config, seed, span, ledger.enabled("fall"))
    _realm_events(world, config, seed, span, ledger)
    styles = rulers.derive(world, config, seed, span, ledger)
    conflicts.derive(world, config, seed, span, ledger, styles)
    world.chronicle = ledger.finish()
    for event in world.chronicle:  # a settlement is marked by the event that founded or settled it
        if event.kind in ("founding", "settling"):
            for index in event.poi_ids:
                world.pois[index].event_ids.append(event.id)
