"""Who held which land, and when: territory changes and the owner map at any moment.

Today's ``World.realm_id`` is the end state. History records the cells that changed hands as a list of
:class:`TerritoryChange` deltas (not snapshots), oldest first; :class:`OwnerTimeline` replays them to give the owner map
at a moment, forward or backward from checkpoints, so its cost follows the cells that changed and not the number of
events. A simulation appends its own changes in the same form (a tick may batch every flip into one record).

Owners are small integers: a realm is its id (``>= 0``), wild land is :data:`WILD`, a fallen realm is
:func:`fallen_owner` of its id (``-2`` downward) and a predecessor (a realm that ended in a clean split) is
:func:`predecessor_owner` of its id (``-1000`` downward), so one ``int16`` grid shows them all together.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

WILD = -1  # owner of land no realm holds
FALLEN_OWNER_BASE = -2  # a fallen realm's owner is this minus its id
PREDECESSOR_OWNER_BASE = -1000  # a predecessor's owner is this minus its id (so fewer than 998 fallen realms)
NO_EVENT = -1  # ``TerritoryChange.event_id`` of a change not tied to a chronicle event
LAST = 10**9  # an event number after every real one: "the end of the month"
_CHECKPOINT_EVERY = 16  # a cached owner map is kept every this many changes


def fallen_owner(fallen_id: int) -> int:
    """Return the owner value that stands for fallen realm ``fallen_id``."""
    return FALLEN_OWNER_BASE - fallen_id


def is_fallen_owner(owner: int) -> bool:
    """Return whether ``owner`` stands for a fallen realm."""
    return PREDECESSOR_OWNER_BASE < owner <= FALLEN_OWNER_BASE


def fallen_id_of(owner: int) -> int:
    """Return the fallen realm id an owner value stands for (it must satisfy :func:`is_fallen_owner`)."""
    return FALLEN_OWNER_BASE - owner


def predecessor_owner(predecessor_id: int) -> int:
    """Return the owner value that stands for predecessor ``predecessor_id``."""
    return PREDECESSOR_OWNER_BASE - predecessor_id


def is_predecessor_owner(owner: int) -> bool:
    """Return whether ``owner`` stands for a predecessor."""
    return owner <= PREDECESSOR_OWNER_BASE


def predecessor_id_of(owner: int) -> int:
    """Return the predecessor id an owner value stands for (it must satisfy :func:`is_predecessor_owner`)."""
    return PREDECESSOR_OWNER_BASE - owner


@dataclass
class TerritoryChange:
    """Cells that passed from one owner to another at a moment.

    Attributes:
        year: Chronicle year.
        month: Month of the year, 1 upward.
        kind: What caused it (a chronicle event kind such as ``expansion``, ``battle`` or ``fall``).
        cells: Sorted unique flat row-major indices (``y * width + x``) of the cells, ``int32``.
        from_owner: Their owner before (a realm id, :data:`WILD` or a :func:`fallen_owner`).
        to_owner: Their owner after.
        event_id: Index of the chronicle event it belongs to, or :data:`NO_EVENT`.
    """

    year: int
    month: int
    kind: str
    cells: np.ndarray
    from_owner: int
    to_owner: int
    event_id: int = NO_EVENT

    @property
    def moment(self) -> tuple[int, int]:
        """The ``(year, month)`` of the change."""
        return self.year, self.month

    @property
    def key(self) -> tuple[int, int, int]:
        """The change's place in time down to its event: ``(year, month, event id)`` (no event: sorts first)."""
        return self.year, self.month, self.event_id


@dataclass
class OwnerTimeline:
    """The owner map at any moment, replayed from the present state and a list of changes.

    Attributes:
        present: ``[height, width]`` owner grid after every change (``World.realm_id``); never modified.
        changes: The changes, oldest first by ``(year, month)``; equal moments keep their list order.
    """

    present: np.ndarray
    changes: Sequence[TerritoryChange]
    _keys: list[tuple[int, int, int]] = field(init=False, repr=False)
    _cache: dict[int, np.ndarray] = field(init=False, repr=False)
    _latest: Optional[tuple[int, np.ndarray]] = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._keys = [change.key for change in self.changes]
        if self._keys != sorted(self._keys):
            raise ValueError("territory changes must be ordered by (year, month)")
        last = np.ascontiguousarray(self.present, dtype=np.int16).copy()
        last.flags.writeable = False
        self._cache = {len(self.changes) - 1: last}

    @property
    def size(self) -> int:
        """How many changes the timeline was built from (a longer list needs a new timeline)."""
        return len(self.changes)

    def moments(self) -> list[tuple[int, int]]:
        """Return each distinct ``(year, month)`` at which land changed hands, oldest first."""
        return sorted({key[:2] for key in self._keys})

    def changes_at(self, year: int, month: Optional[int] = None) -> list[TerritoryChange]:
        """Return the changes of ``year`` (of that month only when ``month`` is given), in order."""
        return [c for c in self.changes if c.year == year and (month is None or c.month == month)]

    def index_at(self, year: int, month: Optional[int] = None, event: Optional[int] = None) -> int:
        """Return the index of the last change at or before the moment (-1 before the first).

        With no ``month`` the moment is the end of ``year``; with no ``event`` the end of ``month``; with one it is just
        after that chronicle event (earlier events of the same month count, later ones do not).
        """
        key = (year, 10**6 if month is None else month, LAST if event is None else event)
        return bisect_right(self._keys, key) - 1

    def owners_at(self, year: int, month: Optional[int] = None, event: Optional[int] = None) -> np.ndarray:
        """Return the read-only owner grid after every change at or before the moment (end of ``year`` by default)."""
        return self._state(self.index_at(year, month, event))

    def _state(self, index: int) -> np.ndarray:
        """Return the owner grid after change ``index`` (-1: before all), replayed from the nearest cached grid."""
        if index in self._cache:
            return self._cache[index]
        if self._latest is not None and self._latest[0] == index:
            return self._latest[1]
        nearest = min(self._cache, key=lambda known: (abs(known - index), known))
        grid = self._cache[nearest].copy()
        if self._latest is not None and abs(self._latest[0] - index) < abs(nearest - index):
            nearest, grid = self._latest[0], self._latest[1].copy()
        width = grid.shape[1]
        step = 1 if index > nearest else -1
        position = nearest
        while position != index:
            if step > 0:
                change = self.changes[position + 1]
                owner = change.to_owner
            else:
                change = self.changes[position]
                owner = change.from_owner
            grid[change.cells // width, change.cells % width] = owner
            position += step
            if position % _CHECKPOINT_EVERY == 0 and position != index:
                self._cache[position] = self._frozen(grid)
        state = self._frozen(grid)
        if index % _CHECKPOINT_EVERY == 0:
            self._cache[index] = state
        else:
            self._latest = (index, state)  # a stepping view moves one change at a time: keep only the last one
        return state

    @staticmethod
    def _frozen(grid: np.ndarray) -> np.ndarray:
        kept = grid.copy()
        kept.flags.writeable = False
        return kept


def wild_since(changes: Sequence[TerritoryChange], height: int, width: int) -> np.ndarray:
    """Return an ``int32 [height, width]`` grid: the year each cell was last taken from the wild (0 where never).

    ``changes`` run oldest first. A cell a realm holds today was settled no sooner than this, whoever held it between:
    a transfer between realms does not count, since what stood on the land stood already.
    """
    since = np.zeros(height * width, dtype=np.int32)
    for change in changes:
        if change.from_owner == WILD:
            since[change.cells] = change.year
    return since.reshape(height, width)


Key = tuple[int, int, int]  # (year, month, chronicle event id): a place in time down to one event


def at_end(moment: tuple[int, ...]) -> Key:
    """Return ``moment`` as a full key: ``(year, month)`` means the end of that month (after every event in it), a
    three-part moment is already an event's place."""
    return (moment[0], moment[1], LAST) if len(moment) < 3 else (moment[0], moment[1], moment[2])
