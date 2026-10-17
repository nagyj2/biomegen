"""Territory changes: who held which land, found by walking back from today's partition.

History moves no cell, so the chronicle's present map (``World.realm_id``) is the end state and this module works out
how it came to be. It walks the ledger's events from the newest to the oldest, undoing each: a realm's **expansions**
(new ``expansion`` events, a few large annexations of wild land, the cells farthest from its seat first) hand their band
back to the wild, and its **founding** hands whatever is left back to the wild, so a realm begins as a core round its
seat and grows to the size it has today. Every undone step is recorded as a
:class:`~biomegen.world.territory.TerritoryChange` (forward: from the earlier owner to the later one), tied to its
event; after the ledger is numbered :meth:`Plan.resolve` gives each change its month and event id and returns them
oldest first. Nothing here writes a per-tile array.

Draws are ``rng.derive(seed, "history", "territory", ...)`` keyed on the realm, so no realm's expansions depend on
another's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy import ndimage

from ...config.model import Config
from ...util import rng
from ...world.entities import EVENT_KINDS, ChronicleEvent
from ...world.territory import WILD, TerritoryChange, fallen_id_of, fallen_owner
from ...world.world import World
from .ledger import Ledger
from .places import nearest_settlement
from .territory_fields import TerritoryFields, territory_fields

_EXPANSION = EVENT_KINDS.index("expansion")


@dataclass
class _Item:
    """One step of the walk: an event of the ledger, or an expansion planned but not yet added to it."""

    key: tuple[int, int, int]  # the ledger's sort key (year, kind order, creation index)
    kind: str
    event: Optional[ChronicleEvent] = None
    owner: int = WILD  # a planned expansion's owner: a realm id or a fallen realm's owner value
    share: float = 0.0  # a planned expansion's share of what the owner held at most
    ordinal: int = 0  # a planned expansion's number among its owner's
    cells: Optional[np.ndarray] = None  # what a planned expansion took (None: dropped)

    @property
    def year(self) -> int:
        return self.key[0]


@dataclass
class _Domain:
    """Where an owner grew from: its seat (or a fallen realm's ruins), the km from it, and the most land it held."""

    seat: tuple[int, int]
    km: np.ndarray  # [y, x] km from the seat
    final: int  # cells held at the end of its life (today for a realm, the fall for a fallen realm)


@dataclass
class Plan:
    """The changes found by :func:`plan`, each with the step it came from, newest first."""

    entries: list[tuple[_Item, TerritoryChange]] = field(default_factory=list)

    def resolve(self) -> list[TerritoryChange]:
        """Return the changes oldest first, each with its event's month and id (the ledger must be finished)."""
        changes = []
        for item, change in reversed(self.entries):
            assert item.event is not None
            change.month, change.event_id = item.event.month, item.event.id
            changes.append(change)
        changes.sort(key=lambda change: change.event_id)  # stable: changes of one event stay in order
        return changes


class _Walker:
    """Walks the steps back from the present, undoing each on ``state``."""

    def __init__(self, world: World, config: Config, seed: int, ledger: Ledger, fields: TerritoryFields) -> None:
        self.world, self.config, self.seed, self.ledger = world, config, seed, ledger
        self.settings = config.get("history.territory")
        self.state = world.realm_id.astype(np.int16)
        self.plan = Plan()
        self._km: dict[int, np.ndarray] = {}
        final = np.bincount(world.realm_id[world.realm_id >= 0].ravel(), minlength=len(world.realms))
        self.domains = {
            realm.id: _Domain(fields.seats[realm.id], fields.seat_km, int(final[realm.id]))
            for realm in world.realms
            if final[realm.id]
        }

    def run(self) -> Plan:
        steps = [_Item(key, event.kind, event) for key, event in self.ledger.ordered()]
        planned = self._expansions(self.ledger.size) if self.ledger.enabled("expansion") else []
        for step in reversed(sorted(steps + planned, key=lambda step: step.key)):
            event = step.event
            if step.kind == "expansion":
                self._peel(step)
            elif step.kind == "founding" and event and event.fallen_ids:
                self._found(step, fallen_owner(event.fallen_ids[0]))
            elif step.kind == "founding" and event and event.realm_ids:
                self._found(step, event.realm_ids[0])
            elif step.kind == "fall" and event and event.fallen_ids:
                self._fall(step, event)
        self._add_events([step for step in planned if step.cells is not None])
        return self.plan

    def _expansions(self, base: int) -> list[_Item]:
        """Plan each realm's and fallen realm's annexations: when, and how large (the cells are chosen in the walk)."""
        gap = int(self.config.get("history.min_gap_years"))
        share_low, share_high = (float(v) for v in self.settings["expansion_share"])
        drawn: list[tuple[int, int, int, float]] = []  # (year, owner, ordinal, share)
        lives = [(realm.id, realm.kind, realm.founded, self.world.year) for realm in self.world.realms]
        lives += [(fallen_owner(f.id), "fallen", f.founded, f.fell - 1) for f in self.world.fallen_realms]
        for owner, kind, founded, last in lives:
            low, high = (int(v) for v in self.settings["expansions"][kind])
            label = ("expand", owner) if owner >= 0 else ("expand", "fallen", fallen_id_of(owner))
            stream = rng.derive(self.seed, "history", "territory", *label)
            count = stream.randint(low, high)
            first = founded + gap
            if first > last or (owner >= 0 and owner not in self.domains):
                continue
            for ordinal in range(count):
                year = stream.randint(first, last)
                share = stream.uniform(share_low, share_high)
                drawn.append((year, owner, ordinal, share))
        drawn.sort()  # the ledger will receive them in this order, so a step's creation index is base + its position
        return [
            _Item((year, _EXPANSION, base + n), "expansion", None, owner, share, ordinal)
            for n, (year, owner, ordinal, share) in enumerate(drawn)
        ]

    def _outer_band(self, owner: int, count: int, domain: _Domain) -> np.ndarray:
        """Return flat indices of ``count`` cells of ``owner`` farthest from its seat, plus any part cut off from it."""
        held = self.state == owner
        flat = np.flatnonzero(held)
        distance = domain.km.reshape(-1)[flat]
        farthest = flat[np.lexsort((flat, -distance))[:count]]
        kept = held.copy()
        kept.reshape(-1)[farthest] = False
        labels, _ = ndimage.label(kept)
        seat_label = int(labels[domain.seat[1], domain.seat[0]])
        return np.flatnonzero(held & ~((labels == seat_label) & kept)) if seat_label else flat

    def _peel(self, step: _Item) -> None:
        """Undo a planned expansion: its band goes back to the wild."""
        owner = step.owner
        domain = self.domains.get(owner)
        if domain is None:
            return
        have = int(np.count_nonzero(self.state == owner))
        floor = max(math.ceil(float(self.settings["core_share"]) * domain.final), 1)
        want = min(round(step.share * domain.final), have - floor)
        if want < int(self.settings["min_band_cells"]):
            return
        cells = self._outer_band(owner, want, domain).astype(np.int32)
        self.state.reshape(-1)[cells] = WILD
        step.cells = cells
        self.plan.entries.append((step, TerritoryChange(step.year, 0, "expansion", cells, WILD, owner)))

    def _found(self, step: _Item, owner: int) -> None:
        """Undo a founding: what the owner holds then was wild land before."""
        cells = np.flatnonzero(self.state == owner).astype(np.int32)
        if not len(cells):
            return
        self.state.reshape(-1)[cells] = WILD
        self.plan.entries.append((step, TerritoryChange(step.year, 0, "founding", cells, WILD, owner)))

    def _ruin_km(self, fallen_id: int) -> np.ndarray:
        """Return the ``[y, x]`` km from the ruins of fallen realm ``fallen_id`` (computed once)."""
        if fallen_id not in self._km:
            x, y = self.world.fallen_realms[fallen_id].location
            seed_mask = np.ones(self.state.shape, dtype=bool)
            seed_mask[y, x] = False
            self._km[fallen_id] = ndimage.distance_transform_edt(seed_mask, sampling=self.world.scale.sampling)
        return self._km[fallen_id]

    def _fall(self, step: _Item, event: ChronicleEvent) -> None:
        """Undo a fallen realm's fall: the land round its ruins was its own before.

        The land is the nearest wild cells to the ruins, on their landmass, plus the victor's cells when the realm was
        conquered (nearer for the choosing by ``victor_bias``): those are what the victor took at the fall.
        """
        fallen = self.world.fallen_realms[event.fallen_ids[0]]
        owner = fallen_owner(fallen.id)
        victor = event.realm_ids[0] if event.realm_ids else -1
        stream = rng.derive(self.seed, "history", "territory", "fallen", fallen.id)
        low, high = (float(v) for v in self.settings["fallen_area_km2"])
        cell_km2 = self.world.scale.cell_area_km2
        target = max(int(self.settings["min_cells"]), round(stream.uniform(low, high) / cell_km2))
        x0, y0 = fallen.location
        km = self._ruin_km(fallen.id)
        reach_km = float(self.settings["fallen_reach"]) * math.sqrt(target * cell_km2 / math.pi)
        landmass = int(self.world.landmass_id[y0, x0])
        theirs = (self.state == victor) if victor >= 0 else np.zeros(self.state.shape, dtype=bool)
        eligible = (self.world.landmass_id == landmass) & ((self.state == WILD) | theirs) & (km <= reach_km)
        for (
            other
        ) in self.world.fallen_realms:  # land nearer the ruins of a realm that lived at the same time is its own
            if other.id != fallen.id and other.founded <= fallen.fell and fallen.founded <= other.fell:
                nearer = self._ruin_km(other.id) < km if other.id < fallen.id else self._ruin_km(other.id) <= km
                eligible &= ~nearer
        flat = np.flatnonzero(eligible)
        if landmass < 0 or not len(flat):
            return
        effective = np.where(theirs, km * float(self.settings["victor_bias"]), km).reshape(-1)[flat]
        chosen = flat[np.lexsort((flat, effective))[:target]]
        anchor = int(flat[np.lexsort((flat, km.reshape(-1)[flat]))[0]])  # the ruins' cell, or the nearest eligible one
        mask = np.zeros(self.state.size, dtype=bool)
        mask[chosen] = True
        mask[anchor] = True
        labels, _ = ndimage.label(mask.reshape(self.state.shape))
        blob = np.flatnonzero(labels.reshape(-1) == labels.reshape(-1)[anchor]).astype(np.int32)
        if len(blob) < int(self.settings["min_band_cells"]):
            return
        was = self.state.reshape(-1)[blob]
        for source in sorted(int(s) for s in np.unique(was)):
            part = blob[was == source]
            self.plan.entries.append((step, TerritoryChange(step.year, 0, "fall", part, owner, source)))
        self.state.reshape(-1)[blob] = owner
        self.domains[owner] = _Domain((anchor % self.world.width, anchor // self.world.width), km, len(blob))

    def _add_events(self, kept: list[_Item]) -> None:
        """Add the events of the expansions that took cells to the ledger, in the order the walk assumed."""
        width = self.world.width
        km_row, km_col = self.world.scale.sampling
        for step in kept:
            assert step.cells is not None
            ys, xs = step.cells // width, step.cells % width
            gap = ((ys - ys.mean()) * km_row) ** 2 + ((xs - xs.mean()) * km_col) ** 2
            middle = int(np.argmin(gap))
            location = (int(xs[middle]), int(ys[middle]))
            near = nearest_settlement(self.world, self.config, *location)
            if step.owner >= 0:
                step.event = self.ledger.add(
                    step.year,
                    "expansion",
                    "expansion",
                    ("realm", step.owner, step.ordinal),
                    self.seed,
                    realm_ids=[step.owner],
                    location=location,
                    near_poi=near,
                    tags=(self.world.realms[step.owner].kind,),
                )
            else:
                fallen = fallen_id_of(step.owner)
                step.event = self.ledger.add(
                    step.year,
                    "expansion",
                    "expansion_fallen",
                    ("fallen", fallen, step.ordinal),
                    self.seed,
                    fallen_ids=[fallen],
                    location=location,
                    near_poi=near,
                    tags=("fallen",),
                )


def plan(world: World, config: Config, seed: int, ledger: Ledger) -> Plan:
    """Find the territory changes of the ledger's events and add the ``expansion`` events they need to the ledger.

    Call it after every other event is in the ledger and before :meth:`Ledger.finish`; then ``world.territory`` is
    ``plan.resolve()`` once the ledger is finished.
    """
    if not world.realms and not world.fallen_realms:
        return Plan()
    return _Walker(world, config, seed, ledger, territory_fields(world)).run()
