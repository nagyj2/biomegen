"""Tests for territory changes and the owner map at a moment (``world/territory.py``)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.world.territory import (
    WILD,
    OwnerTimeline,
    TerritoryChange,
    fallen_id_of,
    fallen_owner,
    is_fallen_owner,
)
from biomegen.world.world import World

WIDTH, HEIGHT = 6, 4


def _cells(*points: tuple[int, int]) -> np.ndarray:
    return np.array(sorted(y * WIDTH + x for x, y in points), dtype=np.int32)


def _present() -> np.ndarray:
    # Realm 0 holds the left three columns, realm 1 the right three; row 0 of the right is wild.
    grid = np.zeros((HEIGHT, WIDTH), dtype=np.int16)
    grid[:, 3:] = 1
    grid[0, 3:] = WILD
    return grid


def _changes() -> list[TerritoryChange]:
    return [
        TerritoryChange(
            100, 3, "expansion", _cells((3, 0), (4, 0)), fallen_owner(0), WILD
        ),  # a fallen realm's land goes wild
        TerritoryChange(120, 1, "expansion", _cells((3, 1), (3, 2)), WILD, 1),
        TerritoryChange(120, 6, "battle", _cells((2, 3)), 1, 0),
        TerritoryChange(150, 2, "fall", _cells((0, 0)), fallen_owner(0), 0),
    ]


def _timeline() -> OwnerTimeline:
    return OwnerTimeline(_present(), _changes())


def test_a_fallen_owner_round_trips_its_id() -> None:
    assert fallen_id_of(fallen_owner(7)) == 7 and is_fallen_owner(fallen_owner(0)) and not is_fallen_owner(WILD)


def test_the_state_after_every_change_is_the_present() -> None:
    assert np.array_equal(_timeline().owners_at(150, 2), _present())


def test_before_the_first_change_the_cells_have_their_first_owner() -> None:
    grid = _timeline().owners_at(99)
    assert grid[0, 3] == fallen_owner(0) and grid[0, 0] == fallen_owner(0)


def test_a_change_applies_at_its_month_and_not_before() -> None:
    timeline = _timeline()
    assert (timeline.owners_at(120, 5)[3, 2], timeline.owners_at(120, 6)[3, 2]) == (1, 0)


def test_the_end_of_a_year_holds_all_that_years_changes() -> None:
    assert _timeline().owners_at(120)[3, 2] == 0


def test_a_moment_does_not_depend_on_the_order_asked() -> None:
    # Replaying forward and backward from cached grids gives the same grid for the same moment.
    first = _timeline()
    forward = [first.owners_at(year, month).copy() for year, month in first.moments()]
    second = _timeline()
    backward = [second.owners_at(year, month).copy() for year, month in reversed(second.moments())][::-1]
    assert all(np.array_equal(a, b) for a, b in zip(forward, backward, strict=True))


def test_many_changes_replay_through_checkpoints() -> None:
    # Fifty single-cell changes alternate two cells between realms 0 and 1; each step is replayed exactly.
    changes = [TerritoryChange(year, 1, "battle", _cells((0, 0)), year % 2, (year + 1) % 2) for year in range(1, 51)]
    present = np.zeros((HEIGHT, WIDTH), dtype=np.int16)
    present[0, 0] = changes[-1].to_owner
    timeline = OwnerTimeline(present, changes)
    owners = [int(timeline.owners_at(year)[0, 0]) for year in (7, 40, 3, 50, 1, 33)]
    assert owners == [(7 + 1) % 2, (40 + 1) % 2, (3 + 1) % 2, (50 + 1) % 2, (1 + 1) % 2, (33 + 1) % 2]


def test_a_returned_grid_cannot_be_written() -> None:
    grid = _timeline().owners_at(110)
    with pytest.raises(ValueError):
        grid[0, 0] = 5


def test_unordered_changes_are_rejected() -> None:
    changes = _changes()
    with pytest.raises(ValueError):
        OwnerTimeline(_present(), [changes[1], changes[0]])


def test_the_moments_are_the_distinct_months_of_the_changes() -> None:
    assert _timeline().moments() == [(100, 3), (120, 1), (120, 6), (150, 2)]


def test_a_world_with_no_changes_answers_with_its_realm_map() -> None:
    world = World(WIDTH, HEIGHT, 1)
    world.realm_id[:] = _present()
    assert np.array_equal(world.owners_at(50), _present())


def test_a_world_replays_its_territory_and_sees_later_changes() -> None:
    world = World(WIDTH, HEIGHT, 1)
    world.realm_id[:] = _present()
    world.territory = _changes()[:2]
    first = int(world.owners_at(100)[0, 3])
    world.territory = _changes()
    assert (first, int(world.owners_at(100)[0, 0])) == (WILD, fallen_owner(0))
