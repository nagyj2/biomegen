"""Stage: annals - the minor events the history leaves out.

The history records what moves realms; the world is also made of smaller things that happen without a realm's hand. This
stage adds each of them to the chronicle as a *minor* event, so it is tracked (and the history viewer can date what
stands) without filling the default listing:

- a **tower** raised or a **dungeon** delved: one that came of a fall is dated by it; one placed by location is either
  ancient (year 0, with chance ``history.annals.ancient_share``: it stood before the history began) or made in a year
  drawn over the history, and then gets that year as its ``founded``;
- the **life of a watchtower** raised in a war: raised with the war, abandoned or dismantled at the peace, and taken by
  bandits later (after which it is a tower; ``World.vanished`` holds the dismantled);
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
    """Add the creation of the tower, dungeon or camp ``index``; dates a POI placed by location.

    A camp is made by whoever holds the land when it is made (a realm: ``creation_camp``) or by no one
    (``creation_camp_wild``): it marks a building project, not a permanent structure.
    """
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
    month = _month(roll_month, low, months)
    row = f"creation_{poi.kind}"
    realms: list[int] = []
    if poi.kind == "camp":
        owner = int(world.owners_at(year, month)[poi.y, poi.x])
        row, realms = ("creation_camp", [owner]) if owner >= 0 else ("creation_camp_wild", [])
    event = ledger.add(
        year,
        "creation",
        row,
        ("poi", index),
        seed,
        realm_ids=realms,
        poi_ids=[index],
        location=(poi.x, poi.y),
        near_poi=nearest_settlement(world, config, poi.x, poi.y),
        tags=(poi.kind,),
        salience="minor",
    )
    if event is not None:
        event.month = month


def _watchtower(world: World, config: Config, seed: int, ledger: Ledger, ref: int) -> None:
    """Add the life of a watchtower raised in a war (``ref`` indexes :meth:`World.place`): its raising in the month the
    war was declared, at the peace its abandonment or dismantling in that month, and, if bandits took it, their
    occupation (a month of its year)."""
    poi = world.place(ref)
    months = int(config.get("history.months_per_year"))
    roll = rng.derive(seed, "history", "annals", "watchtower", ref).random()
    near = nearest_settlement(world, config, poi.x, poi.y)

    def add(year: int, month: int, row: str, kind: str, *tags: str) -> None:
        event = ledger.add(
            year,
            kind,
            row,
            ("watch", ref),
            seed,
            poi_ids=[ref],
            location=(poi.x, poi.y),
            near_poi=near,
            tags=tags,
            salience="minor",
        )
        if event is not None:
            event.month = month

    war = world.chronicle[poi.event_ids[0]]
    add(war.year, war.month, "creation_watchtower", "creation", "watchtower")
    fate = str(poi.extra["fate"])
    if fate == "standing":
        return
    closing = world.chronicle[poi.event_ids[1]]
    add(
        closing.year,
        closing.month,
        "dismantle_watchtower" if fate == "dismantled" else "abandon_watchtower",
        "abandon",
        fate,
    )
    if fate == "occupied":
        add(int(poi.extra["taken"]), _month(roll, 1, months), "occupation_tower", "occupation", "tower")


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
    for index, poi in enumerate((*world.pois, *world.vanished)):
        if poi.extra.get("fate"):
            _watchtower(world, config, seed, ledger, index)
        elif poi.kind in ("tower", "dungeon", "camp"):
            _creation(world, config, seed, ledger, index, first, ancient)
        elif poi.civilized and poi.kind not in settle_kinds and poi.founded > 0 and not _dated_by_history(world, poi):
            _settling(world, config, seed, ledger, index)
    events: list[ChronicleEvent] = [event for _, event in sorted(ledger.ordered(), key=lambda item: item[0][2])]
    merge_events(world, events)
    for event in events:
        for index in event.poi_ids:
            world.place(index).event_ids.append(event.id)
    _roads(world, config, seed)
