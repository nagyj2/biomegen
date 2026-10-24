"""One reader for what the simulation may change: owners, realms, populated places, manifests and relations.

Render and explorer read realms, owners and points of interest through a :class:`WorldReader`, never the raw base arrays
and lists, so a simulation's changes reach them without either side knowing. With no :class:`~.sim_state.SimState` (or
while the state still equals the generated world) the reader hands back the base objects themselves: every list is
``World``'s own and every entity is the one in it. Only what the simulation changed is a copy, made with
``dataclasses.replace`` once per revision, so objects stay the same between revisions and a reader can hold them.

The contract with the simulation: it bumps ``SimState.revision`` whenever it changes something a reader may have built
(the engine does, once per changing tick), and it appends events through :meth:`~.sim_state.SimState.event_log`, which
numbers them. What does not change (terrain, generation-time names, the chronicle) stays on ``World``.

POI indices follow ``World.place``: the standing POIs, then the vanished ones, then the ones the simulation minted.
:attr:`WorldReader.places` is aligned with those indices and :attr:`WorldReader.standing` says which of them stand.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Optional

import numpy as np

from .entities import POI, Predecessor, Realm, Relation, Ruler
from .ledger import EventLog
from .manifest import SiteManifest
from .sim_state import SimState
from .world import World


class WorldReader:
    """The world as readers see it: ``world`` with ``state``'s changes on top (none when ``state`` is None).

    Attributes:
        world: The generated world, which is never written.
        state: The simulation's state, or None for the world as generated.
    """

    def __init__(self, world: World, state: Optional[SimState] = None) -> None:
        self.world = world
        self.state = state
        self._revision = -1
        self._built: dict[str, Any] = {}
        self._log: Optional[EventLog] = None

    # ------------------------------------------------------------------ time and cache
    @property
    def revision(self) -> int:
        """The state's revision (0 with no state): what a cache holding a built value compares."""
        return self.state.revision if self.state is not None else 0

    @property
    def tick(self) -> int:
        """The state's tick (0 with no state)."""
        return self.state.tick if self.state is not None else 0

    def _memo(self, key: str, build: Callable[[], Any]) -> Any:
        """Return the value ``build`` makes for ``key``, built once per revision."""
        if self._revision != self.revision:
            self._built, self._revision = {}, self.revision
        if key not in self._built:
            self._built[key] = build()
        return self._built[key]

    # ------------------------------------------------------------------ the map
    @property
    def owners(self) -> np.ndarray:
        """The ``[y, x]`` owner grid: ``World.realm_id``, or the simulation's own copy of it (read only)."""
        return self.world.realm_id if self.state is None else self.state.owners

    @property
    def front(self) -> np.ndarray:
        """The ``[y, x]`` war-front grid (the world's; the simulation moves its own once borders do, 10d)."""
        return self.world.front

    # ------------------------------------------------------------------ realms
    @property
    def realms(self) -> list[Realm]:
        """Every realm by id: the generated ones (a copy where the simulation changed one), then the ones it made."""
        return self._memo("realms", self._build_realms)

    def _build_realms(self) -> list[Realm]:
        world, state = self.world, self.state
        if state is None:
            return world.realms
        rulers = self.rulers
        moved = any(state.factions[r.id].liege != r.liege for r in world.realms if r.id in state.factions)
        vassals: dict[int, list[int]] = {}
        if moved:
            for faction_id in sorted(state.factions):
                if state.factions[faction_id].liege >= 0:
                    vassals.setdefault(state.factions[faction_id].liege, []).append(faction_id)
        realms: list[Realm] = []
        for realm in world.realms:
            faction = state.factions.get(realm.id)
            if faction is None:
                realms.append(realm)
                continue
            ruler = rulers[faction.ruler_id].name if 0 <= faction.ruler_id < len(rulers) else realm.ruler
            same = (faction.liege, faction.seat_poi, faction.pop, ruler) == (
                realm.liege,
                realm.seat_poi,
                realm.pop,
                realm.ruler,
            )
            if same and not (moved and sorted(realm.vassals) != vassals.get(realm.id, [])):
                realms.append(realm)
            else:
                realms.append(
                    replace(
                        realm,
                        liege=faction.liege,
                        seat_poi=faction.seat_poi,
                        pop=faction.pop,
                        ruler=ruler,
                        vassals=vassals.get(realm.id, []) if moved else realm.vassals,
                    )
                )
        if not state.realms and all(own is base for own, base in zip(realms, world.realms, strict=True)):
            return world.realms
        return [*realms, *state.realms]

    def realm(self, realm_id: int) -> Realm:
        """Return realm ``realm_id``."""
        return self.realms[realm_id]

    def realm_at(self, x: int, y: int) -> Optional[Realm]:
        """Return the realm that holds ``(x, y)``, or None for wild land and water."""
        index = int(self.owners[y, x])
        realms = self.realms
        return realms[index] if 0 <= index < len(realms) else None

    def top_realm(self, index: int) -> int:
        """Return the id of the independent power at the top of realm ``index``'s chain of lieges."""
        realms = self.realms
        while realms[index].liege >= 0:
            index = realms[index].liege
        return index

    @property
    def rulers(self) -> list[Ruler]:
        """Every ruler by id: the generated ones, then the ones the simulation made."""
        return self._memo("rulers", self._build_rulers)

    def _build_rulers(self) -> list[Ruler]:
        state = self.state
        return self.world.rulers if state is None or not state.rulers else [*self.world.rulers, *state.rulers]

    @property
    def predecessors(self) -> list[Predecessor]:
        """Every predecessor by id: the generated ones, then the ones the simulation made."""
        return self._memo("predecessors", self._build_predecessors)

    def _build_predecessors(self) -> list[Predecessor]:
        state = self.state
        if state is None or not state.predecessors:
            return self.world.predecessors
        return [*self.world.predecessors, *state.predecessors]

    # ------------------------------------------------------------------ places
    @property
    def places(self) -> list[POI]:
        """Every POI by index (as ``World.place`` numbers them, the minted ones last); one the simulation changed the
        owner or people of is a copy."""
        return self._memo("places", self._build_places)

    def _build_places(self) -> list[POI]:
        world, state = self.world, self.state
        if state is None:
            return [*world.pois, *world.vanished]
        every = [*world.pois, *world.vanished, *state.pois]
        for index, poi in enumerate(every):
            place = state.places.get(index)
            if place is not None and (place.owner, place.pop) != (poi.realm_id, poi.pop):
                every[index] = replace(poi, realm_id=place.owner, pop=place.pop)
        return every

    @property
    def standing(self) -> np.ndarray:
        """A bool per place: whether it stands (the POIs and the minted ones do, the vanished do not)."""
        return self._memo("standing", self._build_standing)

    def _build_standing(self) -> np.ndarray:
        world = self.world
        count = len(world.pois) + len(world.vanished) + (len(self.state.pois) if self.state is not None else 0)
        standing = np.ones(count, dtype=bool)
        standing[len(world.pois) : len(world.pois) + len(world.vanished)] = False
        return standing

    @property
    def poi_index(self) -> np.ndarray:
        """The ``[y, x]`` grid of the index of the POI anchored at each cell (-1 for none), the minted ones included."""
        return self._memo("poi_index", self._build_poi_index)

    def _build_poi_index(self) -> np.ndarray:
        world, state = self.world, self.state
        if state is None or not state.pois:
            return world.poi_index
        stamped = world.poi_index.copy()
        first = len(world.pois) + len(world.vanished)
        for offset, poi in enumerate(state.pois):
            if stamped[poi.y, poi.x] < 0:  # one POI to a tile: a standing one keeps it
                stamped[poi.y, poi.x] = first + offset
        return stamped

    def place(self, index: int) -> POI:
        """Return POI ``index`` (see :meth:`~biomegen.world.world.World.place`; the minted ones follow the vanished)."""
        return self.places[index]

    def poi_at(self, x: int, y: int) -> Optional[POI]:
        """Return the standing POI anchored at ``(x, y)``, or None."""
        index = int(self.poi_index[y, x])
        places = self.places
        return places[index] if 0 <= index < len(places) and self.standing[index] else None

    def manifest_of(self, index: int) -> Optional[SiteManifest]:
        """Return the manifest the simulation keeps of POI ``index``, or None (read it by tier and population)."""
        return self.state.manifests.get(index) if self.state is not None else None

    # ------------------------------------------------------------------ relations and events
    @property
    def relations(self) -> list[Relation]:
        """Each pair of independent powers' relation: the world's, a copy where the simulation changed one, and the
        pairs it added."""
        return self._memo("relations", self._build_relations)

    def _build_relations(self) -> list[Relation]:
        world, state = self.world, self.state
        if state is None:
            return world.relations
        relations: list[Relation] = []
        for base in world.relations:
            own = state.relations.get((base.a, base.b))
            if own is not None:  # a pair the simulation ended has no relation any more
                relations.append(base if own == base else own)
        known = {(r.a, r.b) for r in world.relations}
        added = [state.relations[pair] for pair in sorted(state.relations) if pair not in known]
        if not added and len(relations) == len(world.relations):
            if all(own is base for own, base in zip(relations, world.relations, strict=True)):
                return world.relations
        return [*relations, *added]

    @property
    def events(self) -> EventLog:
        """The chronicle and the simulation's events as one list (appending adds to ``SimState.events``)."""
        if self._log is None:
            self._log = self.state.event_log(self.world) if self.state is not None else EventLog(self.world)
        return self._log
