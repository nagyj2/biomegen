"""Stage: annals - the minor events the history leaves out.

The history records what moves realms; the world is also made of smaller things that happen without a realm's hand. This
stage adds each of them to the chronicle as a *minor* event, so it is tracked (and the history viewer can date what
stands) without filling the default listing:

- a **tower** raised or a **dungeon** delved: one that came of a fall is dated by it; one placed by location is either
  ancient (year 0, with chance ``history.annals.ancient_share``: it stood before the history began) or made in a year
  drawn over the history, and then gets that year as its ``founded``;
- the **founding of a village or hamlet** (the settlements the history does not give a ``settling`` event); a hamlet or
  homestead on land a realm annexed is founded no sooner than the land came in (as the history does for a settlement).

The roads laid between them (``World.road_links``) each get a minor ``road`` event too, once both ends exist.

It runs after the POIs and their roads, so the chronicle is finished: the new events are merged into it (renumbering the
ids the world keeps) and linked from the POI they are about. Every draw is a ``history`` / ``annals`` stream keyed on
the POI.
"""

from __future__ import annotations

from ...config.model import Config
from ...util import rng
from ...world.entities import POI, ChronicleEvent, RoadLink
from ...world.lifespans import poi_appears
from ...world.territory import wild_since
from ...world.world import World
from .ledger import Ledger, merge_events
from .places import nearest_settlement


def _dated_by_history(world: World, poi: POI) -> bool:
    """Whether the history already gave the settlement a founding, settling or secession event."""
    return any(world.chronicle[i].kind in ("founding", "settling", "secession") for i in poi.event_ids)


def _month(stream_roll: float, low: int, months: int) -> int:
    """Map ``stream_roll`` in [0, 1) to a month in ``low..months``."""
    return low + int(stream_roll * (months - low + 1))


def _creation(world: World, config: Config, seed: int, ledger: Ledger, index: int, first: int, ancient: float) -> None:
    """Add the creation of the tower or dungeon ``index``; dates a POI placed by location."""
    poi = world.pois[index]
    stream = rng.derive(seed, "history", "annals", "creation", index)
    roll_ancient, roll_year, roll_month = (stream.random() for _ in range(3))
    months = int(config.get("history.months_per_year"))
    if poi.event_ids:  # it came of a fall: it stands from then
        made = world.chronicle[poi.event_ids[0]]
        year, low = made.year, made.month
    else:
        year = 0 if roll_ancient < ancient else first + int(roll_year * (world.year - first + 1))
        low = 1
        poi.founded = year
    event = ledger.add(
        year,
        "creation",
        f"creation_{poi.kind}",
        ("poi", index),
        seed,
        poi_ids=[index],
        location=(poi.x, poi.y),
        near_poi=nearest_settlement(world, config, poi.x, poi.y),
        tags=(poi.kind,),
        salience="minor",
    )
    if event is not None:
        event.month = _month(roll_month, low, months)


def _settling(world: World, config: Config, seed: int, ledger: Ledger, index: int) -> None:
    """Add the founding of the village or hamlet ``index``, in the year it was founded."""
    poi = world.pois[index]
    free = poi.realm_id < 0
    roll = rng.derive(seed, "history", "annals", "settling", index).random()
    event = ledger.add(
        poi.founded,
        "settling",
        "settling_free" if free else "settling",
        ("annals", index),
        seed,
        realm_ids=[] if free else [poi.realm_id],
        poi_ids=[index],
        location=(poi.x, poi.y),
        tags=(poi.kind, *(("free",) if free else ())),
        salience="minor",
    )
    if event is not None:
        event.month = _month(roll, 1, int(config.get("history.months_per_year")))


def _roads(world: World, config: Config, seed: int) -> None:
    """Add the laying of every road, up to ``road_delay_years`` after the later of its two ends appears."""
    ledger = Ledger(config)
    delay = int(config.get("history.annals.road_delay_years"))
    months = int(config.get("history.months_per_year"))
    laid: list[tuple[RoadLink, ChronicleEvent]] = []
    for number, link in enumerate(world.road_links):
        ends = [link.a] + ([link.b] if link.b >= 0 else [])
        starts = [poi_appears(world, config, index) for index in ends]
        base = max((start for start in starts if start is not None), default=(0, 1))
        roll_delay, roll_month = (rng.derive(seed, "history", "annals", "road", number).random() for _ in range(2))
        year = min(world.year, base[0] + int(roll_delay * (delay + 1)))
        middle = int(link.cells[len(link.cells) // 2])
        event = ledger.add(
            year,
            "road",
            "road_trunk" if link.b >= 0 else "road_spur",
            ("link", number),
            seed,
            poi_ids=ends,
            location=(middle % world.width, middle // world.width),
            tags=("trunk" if link.b >= 0 else "spur",),
            salience="minor",
        )
        if event is not None:
            event.month = _month(roll_month, base[1] if year == base[0] else 1, months)
            laid.append((link, event))
    merge_events(world, [event for _, event in laid])
    for link, event in laid:
        link.event_id = event.id


def run(world: World, config: Config, seed: int) -> None:
    """Add the minor events to ``world.chronicle`` and link them from their POIs."""
    ledger = Ledger(config)
    first = int(config.get("history.first_founding_year"))
    ancient = float(config.get("history.annals.ancient_share"))
    settle_kinds = set(config.get("history.settle_kinds"))
    since = wild_since(world.territory, world.height, world.width)
    for poi in world.pois:  # a hamlet or homestead on annexed land is founded no sooner than the land was taken in
        if poi.realm_id >= 0 and poi.kind in ("hamlet", "homestead") and poi.founded > 0:
            poi.founded = max(poi.founded, int(since[poi.y, poi.x]))
    for index, poi in enumerate(world.pois):
        if poi.kind in ("tower", "dungeon"):
            _creation(world, config, seed, ledger, index, first, ancient)
        elif poi.civilized and poi.kind not in settle_kinds and poi.founded > 0 and not _dated_by_history(world, poi):
            _settling(world, config, seed, ledger, index)
    events: list[ChronicleEvent] = [event for _, event in sorted(ledger.ordered(), key=lambda item: item[0][2])]
    merge_events(world, events)
    for event in events:
        for index in event.poi_ids:
            world.pois[index].event_ids.append(event.id)
    _roads(world, config, seed)
