"""The simulation's state, kept beside the generated world (which stays immutable).

Nothing builds or reads a :class:`SimState` yet: it fixes the shape the simulation (phase 10) will fill, so the readers
and the id rules are agreed first. Everything the simulation adds *continues* a list the generation made: events
(:class:`~biomegen.world.ledger.EventLog`), rulers, predecessors and points of interest take ids after the generated
ones, so an id means the same thing to every reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .entities import POI, ChronicleEvent, Predecessor, Ruler
from .manifest import SiteManifest
from .world import World


@dataclass
class SimState:
    """What the simulation owns.

    Attributes:
        tick: The current tick (an absolute month, as ``ChronicleEvent.tick``).
        revision: Bumped whenever state a cache may hold changes, so readers can drop what they cached.
        events: Events the simulation emitted, which continue ``World.chronicle``.
        rulers: Rulers it made, continuing ``World.rulers``.
        predecessors: Predecessors it made, continuing ``World.predecessors``.
        pois: Points of interest it minted (hamlets, camps), continuing ``World.pois`` and ``World.vanished``.
        manifests: The manifest of each settlement whose plan it has changed, by POI index.
    """

    tick: int = 0
    revision: int = 0
    events: list[ChronicleEvent] = field(default_factory=list)
    rulers: list[Ruler] = field(default_factory=list)
    predecessors: list[Predecessor] = field(default_factory=list)
    pois: list[POI] = field(default_factory=list)
    manifests: dict[int, SiteManifest] = field(default_factory=dict)

    def next_ruler_id(self, world: World) -> int:
        """Return the id of the next ruler: after the generated rulers and the ones made so far."""
        return len(world.rulers) + len(self.rulers)

    def next_predecessor_id(self, world: World) -> int:
        """Return the id of the next predecessor."""
        return len(world.predecessors) + len(self.predecessors)

    def next_poi_index(self, world: World) -> int:
        """Return the index of the next POI: after the standing POIs and the vanished ones (see ``World.place``)."""
        return len(world.pois) + len(world.vanished) + len(self.pois)
