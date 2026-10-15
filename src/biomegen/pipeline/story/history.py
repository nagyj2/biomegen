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
5. **Secession** (:mod:`.secession`). Two touching realms may have come of one old realm (a clean split): they share a
   founding year, the old realm is recorded as a :class:`~biomegen.world.entities.Predecessor`, and one ``secession``
   event replaces both foundings; this is decided up front, before the rulers are drawn. A living realm may also have
   left an older one (an offshoot): its founding event is held back, and the conflicts timeline checks at its founding
   year, with the parent's strength then, and writes a ``secession`` event or, if the check fails, the ordinary
   founding. A settlement may also have left an older realm for its holder (a defection): the same check decides it.
6. **Conflicts** (:mod:`.conflicts`): wars, battles, peace, rivalries, treaties and falls, tracked through time.

Events are collected in a :class:`~.ledger.Ledger`, sorted by ``(year, kind order, creation order)`` and numbered, so
an event's ``id`` is its index in ``World.chronicle``. An event holds a raw template picked from ``tables.chronicle``
(its ``templates_near`` only when a settlement qualifies as near, see :mod:`.places`); the naming stage renders its
text. Every draw is a ``history`` sub-stream keyed on the entity, so the result does not depend on dict or set order.
"""

from __future__ import annotations

import math
from collections.abc import Collection

import numpy as np

from ...config.model import Config
from ...util import rng
from ...world.entities import NO_LOCATION, POI, FallenRealm, Predecessor
from ...world.tile import WaterType
from ...world.world import World
from ..civilization.diplomacy import faction_color, neutral_colors
from ..civilization.settlements import habitability
from ..pois import pick_blue_noise
from . import conflicts, rulers, secession
from .founding import add_founding, add_settling
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
    taken = neutral_colors(config) + [realm.color for realm in world.realms]
    start = rng.derive(seed, "history", "colours").random()
    for fallen in world.fallen_realms:  # each fallen realm has a colour no realm or earlier fallen realm shares
        fallen.color = faction_color(config, "fallen", taken, start)


def _remnant_of(world: World, config: Config, poi: POI) -> int:
    """Return the id of the fallen realm ``poi`` is a remnant of, or -1.

    That is the fallen realm whose site is nearest, within ``history.remnant_km`` and on the same landmass; ties go to
    the lower id.
    """
    limit = float(config.get("history.remnant_km"))
    best = (math.inf, -1)
    for fallen in world.fallen_realms:
        fx, fy = fallen.location
        if world.landmass_id[fy, fx] != world.landmass_id[poi.y, poi.x]:
            continue
        km = world.scale.distance_km(poi.x, poi.y, fx, fy)
        if km <= limit and (km, fallen.id) < best:
            best = (km, fallen.id)
    return best[1]


def _apply_splits(world: World, config: Config, seed: int, plans: list[secession.SplitPlan]) -> None:
    """Make each planned clean split real: both realms share the year, and the old realm is recorded.

    The younger realm's founding (and its seat's) moves to the older's, so this runs before anything reads those years.
    Each realm gets its origin and the :class:`Predecessor` that ended; the predecessor is coloured after the realms and
    fallen realms, so no faction shares its colour.
    """
    taken = neutral_colors(config) + [realm.color for realm in world.realms] + [f.color for f in world.fallen_realms]
    start = rng.derive(seed, "history", "colours", "predecessor").random()
    world.predecessors = []
    for plan in plans:
        predecessor = Predecessor(id=len(world.predecessors), founded=plan.founded, split_year=plan.year)
        predecessor.color = faction_color(config, "fallen", taken, start)
        taken.append(predecessor.color)
        for realm_id in (plan.first, plan.second):
            realm = world.realms[realm_id]
            realm.founded, realm.origin, realm.predecessor = plan.year, "split", predecessor.id
            if realm.seat_poi >= 0:
                world.pois[realm.seat_poi].founded = plan.year
            predecessor.children.append(realm_id)
        world.predecessors.append(predecessor)


def _split_events(world: World, config: Config, seed: int, ledger: Ledger) -> None:
    """Add each clean split's events: the old realm's founding, and the ``secession`` replacing the two foundings."""
    for predecessor in world.predecessors:
        ledger.add(
            predecessor.founded,
            "founding",
            "founding_predecessor",
            ("predecessor", predecessor.id),
            seed,
            predecessor_ids=[predecessor.id],
            tags=("predecessor",),
        )
        first, second = (world.realms[i] for i in predecessor.children)
        seats = [r.seat_poi for r in (first, second) if r.seat_poi >= 0]
        tag = secession.relation_tag(world, config, first, second)
        ledger.add(
            predecessor.split_year,
            "secession",
            f"secession_split_{tag}",
            ("split", predecessor.id),
            seed,
            realm_ids=[first.id, second.id],
            poi_ids=seats,
            predecessor_ids=[predecessor.id],
            location=(world.pois[seats[0]].x, world.pois[seats[0]].y) if seats else NO_LOCATION,
            tags=("split", tag, *(("capital",) if any(world.pois[s].kind == "capital" for s in seats) else ())),
        )


def _realm_events(
    world: World,
    config: Config,
    seed: int,
    span: int,
    ledger: Ledger,
    held_back: Collection[int],
    defecting: Collection[int] = (),
) -> None:
    """Add the founding (realms and fallen realms), settling and conquest events.

    A realm in ``held_back`` has no founding yet: it came of a clean split (:func:`_split_events` adds the
    secession), or it may have left an older realm (the conflicts timeline adds a ``secession`` event, or the founding
    if the check fails). A settlement in ``defecting`` may have left an older realm: the timeline settles it (for the
    realm it left if it did, else for its holder).
    """
    gap = int(config.get("history.min_gap_years"))
    settle_kinds = set(config.get("history.settle_kinds"))
    for realm in world.realms:
        if realm.id not in held_back:
            add_founding(world, config, seed, ledger, realm)
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
        if poi.free and poi.kind in settle_kinds and _remnant_of(world, config, poi) < 0:
            ledger.add(
                poi.founded,
                "settling",
                "settling_free",
                ("free", index),
                seed,
                poi_ids=[index],
                location=(poi.x, poi.y),
                tags=(poi.kind, "free"),
            )
        if poi.civilized and poi.kind in settle_kinds and poi.realm_id >= 0 and index not in seats | set(defecting):
            add_settling(world, config, seed, ledger, index, poi.realm_id)
    for realm in world.realms:
        if realm.liege < 0:
            continue
        liege = world.realms[realm.liege]
        first = min(max(realm.founded, liege.founded) + gap, span)
        year = min(first + int(rng.derive(seed, "history", "conquest", realm.id).random() * (span - first + 1)), span)
        ledger.add(year, "conquest", "conquest", (realm.id,), seed, realm_ids=[realm.id, liege.id], tags=("vassalage",))


def _remnants(world: World, config: Config, seed: int, ledger: Ledger) -> dict[int, int]:
    """Date every free settlement that is a remnant of a fallen realm inside that realm's life, and return them.

    Runs after the conflicts, so the realm's ``fell`` is final and the settlement is founded before it. A remnant of
    the ``history.settle_kinds`` gets a ``settling`` event tagged ``free`` and ``remnant``. The result maps the POI
    index to the fallen realm id.
    """
    settle_kinds = set(config.get("history.settle_kinds"))
    remnants: dict[int, int] = {}
    for index, poi in enumerate(world.pois):
        fallen_id = _remnant_of(world, config, poi) if poi.free else -1
        if fallen_id < 0:
            continue
        fallen = world.fallen_realms[fallen_id]
        roll = rng.derive(seed, "history", "remnant", index).random()
        poi.founded = fallen.founded + int(roll * max(1, fallen.fell - fallen.founded))
        remnants[index] = fallen_id
        if poi.kind in settle_kinds:
            ledger.add(
                poi.founded,
                "settling",
                "settling_remnant",
                ("remnant", index),
                seed,
                poi_ids=[index],
                fallen_ids=[fallen_id],
                location=(poi.x, poi.y),
                tags=(poi.kind, "free", "remnant"),
            )
    return remnants


def run(world: World, config: Config, seed: int) -> None:
    """Date the realms and settlements and derive ``world.chronicle``, mutating ``world`` in place."""
    span = int(config.get("history.span_years"))
    world.year = span
    _realm_founding_years(world, config, seed, span)
    _settlement_founding_years(world, config, seed, span)
    ledger = Ledger(config)
    _place_fallen_realms(world, config, seed, span, ledger.enabled("fall"))
    splits = secession.plan_splits(world, config, seed) if ledger.enabled("secession") else []
    _apply_splits(world, config, seed, splits)
    styles = rulers.derive(world, config, seed, span, ledger)
    came_of_split = frozenset(i for plan in splits for i in (plan.first, plan.second))
    offshoots = {}
    if ledger.enabled("secession"):
        offshoots = secession.plan_offshoots(world, config, seed, came_of_split)
    defections = secession.plan_defections(world, config, seed) if ledger.enabled("secession") else {}
    _realm_events(world, config, seed, span, ledger, came_of_split | set(offshoots), set(defections))
    _split_events(world, config, seed, ledger)
    conflicts.derive(world, config, seed, span, ledger, styles, offshoots, len(splits), defections)
    remnants = _remnants(world, config, seed, ledger)
    world.chronicle = ledger.finish()
    for event in world.chronicle:  # a settlement is marked by the event that founded or settled it
        if event.kind in ("founding", "secession", "settling"):
            for index in event.poi_ids:
                world.pois[index].event_ids.append(event.id)
    falls = {event.fallen_ids[0]: event.id for event in world.chronicle if event.kind == "fall"}
    for index, fallen_id in sorted(remnants.items()):  # a remnant is also marked by the fall it outlived
        if fallen_id in falls:
            world.pois[index].event_ids.append(falls[fallen_id])
