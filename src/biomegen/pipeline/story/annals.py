"""Stage: annals - the minor events the history leaves out.

The history records what moves realms; the world is also made of smaller things that happen without a realm's hand. This
stage adds each of them to the chronicle as a *minor* event, so it is tracked (and the history viewer can date what
stands) without filling the default listing:

- a **tower** raised or a **dungeon** delved: one that came of a fall is dated by it; one placed by location is either
  ancient (year 0, with chance ``history.annals.ancient_share``: it stood before the history began) or made in a year
  drawn over the history, and then gets that year as its ``founded``;
- the **founding of a village or hamlet** (the settlements the history does not give a ``settling`` event).

It runs after the POIs and their roads, so the chronicle is finished: the new events are merged into it (renumbering the
ids the world keeps) and linked from the POI they are about. Every draw is a ``history`` / ``annals`` stream keyed on
the POI.
"""

from __future__ import annotations

from ...config.model import Config
from ...util import rng
from ...world.entities import POI, ChronicleEvent
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


def run(world: World, config: Config, seed: int) -> None:
    """Add the minor events to ``world.chronicle`` and link them from their POIs."""
    ledger = Ledger(config)
    first = int(config.get("history.first_founding_year"))
    ancient = float(config.get("history.annals.ancient_share"))
    settle_kinds = set(config.get("history.settle_kinds"))
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
