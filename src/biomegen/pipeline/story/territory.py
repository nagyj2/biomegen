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
from ...world.territory import WILD, TerritoryChange
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
    realm: int = -1
    share: float = 0.0  # a planned expansion's share of the realm's present area
    ordinal: int = 0  # a planned expansion's number among its realm's
    cells: Optional[np.ndarray] = None  # what a planned expansion took (None: dropped)

    @property
    def year(self) -> int:
        return self.key[0]


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
        self.world, self.config, self.seed, self.ledger, self.fields = world, config, seed, ledger, fields
        self.settings = config.get("history.territory")
        self.state = world.realm_id.astype(np.int16)
        self.final = np.bincount(world.realm_id[world.realm_id >= 0].ravel(), minlength=len(world.realms))
        self.plan = Plan()

    def run(self) -> Plan:
        steps = [_Item(key, event.kind, event) for key, event in self.ledger.ordered()]
        planned = self._expansions(self.ledger.size) if self.ledger.enabled("expansion") else []
        for step in reversed(sorted(steps + planned, key=lambda step: step.key)):
            if step.kind == "expansion":
                self._peel(step)
            elif step.kind == "founding" and step.event and step.event.realm_ids and not step.event.fallen_ids:
                self._found(step, step.event.realm_ids[0])
        self._add_events([step for step in planned if step.cells is not None])
        return self.plan

    def _expansions(self, base: int) -> list[_Item]:
        """Plan each realm's annexations: when, and how large (the cells are chosen in the walk)."""
        gap = int(self.config.get("history.min_gap_years"))
        span = self.world.year
        share_low, share_high = (float(v) for v in self.settings["expansion_share"])
        drawn: list[tuple[int, int, int, float]] = []  # (year, realm, ordinal, share)
        for realm in self.world.realms:
            low, high = (int(v) for v in self.settings["expansions"][realm.kind])
            stream = rng.derive(self.seed, "history", "territory", "expand", realm.id)
            count = stream.randint(low, high)
            first = realm.founded + gap
            if self.final[realm.id] < int(self.settings["min_cells"]) or first > span:
                continue
            for ordinal in range(count):
                year = stream.randint(first, span)
                share = stream.uniform(share_low, share_high)
                drawn.append((year, realm.id, ordinal, share))
        drawn.sort()  # the ledger will receive them in this order, so a step's creation index is base + its position
        return [
            _Item((year, _EXPANSION, base + n), "expansion", None, realm, share, ordinal)
            for n, (year, realm, ordinal, share) in enumerate(drawn)
        ]

    def _outer_band(self, owner: int, count: int, seat: tuple[int, int]) -> np.ndarray:
        """Return flat indices of ``count`` cells of ``owner`` farthest from its seat, plus any part cut off from it."""
        held = self.state == owner
        flat = np.flatnonzero(held)
        distance = self.fields.seat_km.reshape(-1)[flat]
        farthest = flat[np.lexsort((flat, -distance))[:count]]
        kept = held.copy()
        kept.reshape(-1)[farthest] = False
        labels, _ = ndimage.label(kept)
        seat_label = int(labels[seat[1], seat[0]])
        return np.flatnonzero(held & ~((labels == seat_label) & kept)) if seat_label else flat

    def _peel(self, step: _Item) -> None:
        """Undo a planned expansion: its band goes back to the wild."""
        realm = step.realm
        have = int(np.count_nonzero(self.state == realm))
        floor = max(math.ceil(float(self.settings["core_share"]) * int(self.final[realm])), 1)
        want = min(round(step.share * int(self.final[realm])), have - floor)
        if want < int(self.settings["min_band_cells"]):
            return
        band = self._outer_band(realm, want, self.fields.seats[realm])
        cells = band.astype(np.int32)
        self.state.reshape(-1)[cells] = WILD
        step.cells = cells
        self.plan.entries.append((step, TerritoryChange(step.year, 0, "expansion", cells, WILD, realm)))

    def _found(self, step: _Item, realm: int) -> None:
        """Undo a realm's founding: what it holds then was wild land before."""
        cells = np.flatnonzero(self.state == realm).astype(np.int32)
        if not len(cells):
            return
        self.state.reshape(-1)[cells] = WILD
        self.plan.entries.append((step, TerritoryChange(step.year, 0, "founding", cells, WILD, realm)))

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
            step.event = self.ledger.add(
                step.year,
                "expansion",
                "expansion",
                ("realm", step.realm, step.ordinal),
                self.seed,
                realm_ids=[step.realm],
                location=location,
                near_poi=nearest_settlement(self.world, self.config, *location),
                tags=(self.world.realms[step.realm].kind,),
            )


def plan(world: World, config: Config, seed: int, ledger: Ledger) -> Plan:
    """Find the territory changes of the ledger's events and add the ``expansion`` events they need to the ledger.

    Call it after every other event is in the ledger and before :meth:`Ledger.finish`; then ``world.territory`` is
    ``plan.resolve()`` once the ledger is finished.
    """
    if not world.realms:
        return Plan()
    return _Walker(world, config, seed, ledger, territory_fields(world)).run()
