"""The simulation's state, kept beside the generated world (which stays immutable).

A :class:`SimState` is what ``sim.hydrate`` makes of a finished world and what ``sim.Simulation`` advances. Everything
the simulation adds *continues* a list the generation made: events (:class:`~biomegen.world.ledger.EventLog`), rulers,
predecessors, realms and points of interest take ids after the generated ones, so an id means the same thing to every
reader. Readers go through :class:`~biomegen.world.reader.WorldReader`, never the raw base arrays, once a state exists.

Time is whole ticks: ``ticks_per_month`` of them make a month (``sim.ticks_per_month``), so ``tick // ticks_per_month``
is the absolute month a chronicle event's ``tick`` counts (:func:`~biomegen.world.entities.month_tick`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .entities import POI, ChronicleEvent, Predecessor, Realm, Relation, Ruler
from .ledger import EventLog
from .manifest import SiteManifest
from .world import World


@dataclass
class Schedule:
    """One cadence of one faction: when it next checks.

    Attributes:
        next_tick: The tick of its next check.
        count: How many checks it has made (a jitter draw is keyed on it).
        last_tick: The tick of its last check (the start tick before the first), so a step knows the ticks elapsed.
    """

    next_tick: int
    count: int = 0
    last_tick: int = 0


@dataclass
class Faction:
    """What the simulation tracks of one realm (generated or made by the simulation), keyed by ``realm_id``.

    Attributes:
        realm_id: Index into ``World.realms`` followed by ``SimState.realms``.
        ruler_id: Index of the present ruler into ``World.rulers`` followed by ``SimState.rulers`` (-1: none).
        traits: The ruler's personality, a value in [0, 1] for each of ``entities.TRAITS`` (a copy a succession may
            redraw).
        liege: The overlord's realm id (-1 when independent).
        seat_poi: Index of the seat in the POI list (-1 for a tribe with no settlement).
        pop: The realm's people.
        schedule: The faction's next check of each cadence (a ``sim.cadence`` row), keyed by cadence name.
    """

    realm_id: int
    ruler_id: int = -1
    traits: dict[str, float] = field(default_factory=dict)
    liege: int = -1
    seat_poi: int = -1
    pop: int = 0
    schedule: dict[str, Schedule] = field(default_factory=dict)


@dataclass
class PlaceState:
    """What the simulation tracks of one populated place, keyed by its POI index.

    Attributes:
        owner: The realm id that holds it (-1: no realm).
        pop: Its people.
        stock: What it stores, whole units per resource (money included); empty until the economy fills it.
    """

    owner: int = -1
    pop: int = 0
    stock: dict[str, int] = field(default_factory=dict)


def present_tick(year: int, months_per_year: int, ticks_per_month: int) -> int:
    """Return the tick the simulation starts at for a world whose last year is ``year``.

    It is the present moment, the end of month ``months_per_year`` of ``year`` (the history viewer's present stop),
    which is the first tick of month 1 of the next year: the first tick advanced opens that month.
    """
    return (year + 1) * months_per_year * ticks_per_month


@dataclass
class SimState:
    """What the simulation owns.

    Attributes:
        tick: The current tick (``ticks_per_month`` of them make a month).
        ticks_per_month: Ticks in a month, copied from ``sim.ticks_per_month``, so the state holds its own time base.
        revision: Bumped whenever state a cache may hold changes, so readers can drop what they cached.
        owners: ``int16 [y, x]``, a copy of ``World.realm_id`` that the simulation moves (the map readers draw).
        factions: One per realm, by realm id.
        places: One per populated POI (civilized or a homestead), by POI index.
        relations: Each pair of independent powers' relation, by ``(a, b)`` with ``a < b`` (copies of today's).
        events: Events the simulation emitted, which continue ``World.chronicle`` (:meth:`event_log` reads both).
        rulers: Rulers it made, continuing ``World.rulers``.
        predecessors: Predecessors it made, continuing ``World.predecessors``.
        realms: Realms it made (a secession), continuing ``World.realms``.
        pois: Points of interest it minted (hamlets, camps), continuing ``World.pois`` and ``World.vanished``.
        manifests: The manifest of each standing settlement, by POI index; ``sim.hydrate`` fills one per settlement and
            a simulation replaces it as buildings are added. A POI with no entry is read by its tier and population.
    """

    tick: int = 0
    ticks_per_month: int = 1
    revision: int = 0
    owners: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.int16))
    factions: dict[int, Faction] = field(default_factory=dict)
    places: dict[int, PlaceState] = field(default_factory=dict)
    relations: dict[tuple[int, int], Relation] = field(default_factory=dict)
    events: list[ChronicleEvent] = field(default_factory=list)
    rulers: list[Ruler] = field(default_factory=list)
    predecessors: list[Predecessor] = field(default_factory=list)
    realms: list[Realm] = field(default_factory=list)
    pois: list[POI] = field(default_factory=list)
    manifests: dict[int, SiteManifest] = field(default_factory=dict)

    def month(self) -> int:
        """Return the absolute month of the current tick (the number ``ChronicleEvent.tick`` counts)."""
        return self.tick // self.ticks_per_month

    def moment(self, months_per_year: int) -> tuple[int, int]:
        """Return the current ``(year, month)``, the month counted from 1, as a chronicle event is dated."""
        year, month = divmod(self.month(), months_per_year)
        return year, month + 1

    def event_log(self, world: World) -> EventLog:
        """Return the chronicle of ``world`` and ``events`` as one list; appending to it adds to ``events``."""
        return EventLog(world, self.events)

    def next_ruler_id(self, world: World) -> int:
        """Return the id of the next ruler: after the generated rulers and the ones made so far."""
        return len(world.rulers) + len(self.rulers)

    def next_predecessor_id(self, world: World) -> int:
        """Return the id of the next predecessor."""
        return len(world.predecessors) + len(self.predecessors)

    def next_realm_id(self, world: World) -> int:
        """Return the id of the next realm: after the generated realms and the ones made so far."""
        return len(world.realms) + len(self.realms)

    def next_poi_index(self, world: World) -> int:
        """Return the index of the next POI: after the standing POIs and the vanished ones (see ``World.place``)."""
        return len(world.pois) + len(world.vanished) + len(self.pois)
