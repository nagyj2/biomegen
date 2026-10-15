"""The event-to-POI rule table: which POIs a chronicle event makes.

:func:`poi_for_event` is pure. From one event, the world's present state, the config and the seed it returns the
:class:`PoiPlan` of every kind that event makes (a *rule* is when an event makes a POI), and nothing else: it
neither places a POI nor writes to the world. Generation calls it over the finished ledger and a later simulation
calls it for each event it emits, so one table serves both.

The rules are the rows of ``tables.pois`` that name the event's kind in ``events``: the event must carry every tag
the row lists, be at least ``min_age_years`` old, and pass the row's ``chance``. The row then says how many POIs it
makes: one, plus a draw of ``holdings`` (a fallen realm's outlying ruins), or one per ``per_km_of_front`` of a war's
front up to ``max_per_event``. A ``fated`` kind draws a fate per POI from ``tables.poi_fates``. A kind with
``tables.poi_sites`` rows (a shrine) picks the site the previous ruler's temper calls for. Where a POI goes is the
placement's business; spacing against other POIs depends on what was placed before, so it is checked there.

Every draw is ``rng.derive(seed, "poi", "event", *event_key(event), kind)`` drawn in a fixed order, so a plan depends
on its event alone. The key is the event's own content, not its id: an id is a position in the ledger and shifts
whenever an event is added, swapped or a chronicle kind is switched off, which would re-roll every POI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...config.model import Config
from ...util import rng
from ...world.entities import ChronicleEvent
from ...world.world import World


@dataclass(frozen=True)
class PoiPlan:
    """What one event makes: ``count`` POIs of ``kind``, not yet placed.

    ``fates`` holds one ``tables.poi_fates`` name per POI for a fated kind (else empty). ``site`` names the
    ``tables.poi_sites`` row a shrine-like kind is built at, ``realm_id`` the realm that builds it (-1 for none).
    """

    kind: str
    event_id: int
    count: int = 1
    fates: tuple[str, ...] = ()
    site: str = ""
    realm_id: int = -1


def event_key(event: ChronicleEvent) -> tuple[object, ...]:
    """Return the labels that identify ``event`` by what it is (kind, year, who, where, tags), never by its id.

    Every POI draw an event drives is keyed on this, so adding or removing other events leaves its POIs alone. The
    separators keep the id lists apart. Two events with the same key would share their draws.
    """
    return (
        event.kind,
        event.year,
        "realms",
        *event.realm_ids,
        "fallen",
        *event.fallen_ids,
        "pois",
        *event.poi_ids,
        "at",
        *event.location,
        "tags",
        *event.tags,
    )


def front_km(world: World, event: ChronicleEvent) -> float:
    """Return the length of the front (the shared border, km) of a two-realm event's relation, 0 when it has none."""
    if len(event.realm_ids) != 2:
        return 0.0
    pair = (min(event.realm_ids), max(event.realm_ids))
    for relation in world.relations:
        if (relation.a, relation.b) == pair:
            return relation.border_km
    return 0.0


def site_for(config: Config, kind: str, event: ChronicleEvent) -> str:
    """Return the ``poi_sites`` row of ``kind`` suiting the temper of the style the event leaves, or ``""``."""
    previous = next((tag.partition(":")[2] for tag in event.tags if tag.startswith("from:")), "")
    temper = config.get(f"tables.ruling_styles.{previous}.temper", None) if previous else None
    sites = config.get("tables.poi_sites")
    for name in sorted(sites):
        if sites[name]["kind"] == kind and sites[name]["temper"] == temper:
            return name
    return ""


def _fate(config: Config, roll: float, simulated: bool) -> str:
    """Pick a fate by weight among the open ones (``sim_only`` fates only for a simulation)."""
    fates = config.get("tables.poi_fates")
    names = [name for name in sorted(fates) if simulated or not fates[name]["sim_only"]]
    pick = roll * sum(float(fates[name]["weight"]) for name in names)
    for name in names:
        pick -= float(fates[name]["weight"])
        if pick < 0:
            return name
    return names[-1]


def poi_for_event(
    world: World,
    config: Config,
    seed: int,
    event: ChronicleEvent,
    *,
    simulated: bool = False,
    now: int | None = None,
) -> list[PoiPlan]:
    """Return what ``event`` makes, one plan per kind in ``priority`` order (empty when it makes nothing).

    ``simulated`` opens the ``sim_only`` fates (captured, successor) to a simulation; ``now`` is the year the age rule
    counts to (default ``world.year``, the present of the generated world).
    """
    rows = config.get("tables.pois")
    present = world.year if now is None else now
    plans: list[PoiPlan] = []
    for kind in sorted(rows, key=lambda name: (int(rows[name]["priority"]), name)):
        row = rows[kind]
        if row["source"] == "location" or event.kind not in row.get("events", ()):
            continue
        if not set(row.get("tags", ())) <= set(event.tags):
            continue
        stream = rng.derive(seed, "poi", "event", *event_key(event), kind)
        chance_roll = stream.random()  # always drawn, so the stream stays aligned
        if chance_roll >= float(row.get("chance", 1.0)) or present - event.year < int(row.get("min_age_years", 0)):
            continue
        count = 1
        if "holdings" in row:
            lo, hi = (int(v) for v in row["holdings"])
            count += stream.randint(lo, hi)
        if "per_km_of_front" in row:
            front = front_km(world, event)
            if front <= 0.0:
                continue
            count = min(int(row["max_per_event"]), max(1, math.ceil(front / float(row["per_km_of_front"]))))
        site, realm_id = "", -1
        if any(poi_site["kind"] == kind for poi_site in config.get("tables.poi_sites").values()):
            site = site_for(config, kind, event)
            if not site or not event.realm_ids:
                continue
            realm_id = event.realm_ids[0]
        fates = tuple(_fate(config, stream.random(), simulated) for _ in range(count)) if row.get("fated") else ()
        plans.append(PoiPlan(kind, event.id, count, fates, site, realm_id))
    return plans
