"""Tests for street routing and bridging."""

from __future__ import annotations

import numpy as np

from biomegen.sites.streets import StreetRules, lay_street
from biomegen.world.tile import Cell

VOID, PATH, BRIDGE, RAIL, WALL = (int(c) for c in (Cell.VOID, Cell.PATH, Cell.BRIDGE, Cell.BRIDGE_WALL, Cell.WALL))
RULES = StreetRules(water_cost=6.0, bridge_max=4, aspect=2.0)


def _grid(rows: int = 9, cols: int = 30) -> tuple[np.ndarray, np.ndarray]:
    return np.full((rows, cols), VOID, dtype=np.uint8), np.ones((rows, cols), dtype=bool)


def test_a_street_joins_two_points_over_dry_ground() -> None:
    grid, dry = _grid()
    assert lay_street(grid, dry, (1, 4), (25, 4), RULES) and (grid[4, 1:26] == PATH).all()


def test_a_street_stops_at_a_wall() -> None:
    grid, dry = _grid()
    grid[:, 12] = WALL
    grid[0, 12] = VOID  # one gap at the top
    assert lay_street(grid, dry, (1, 4), (25, 4), RULES) and (grid[:, 12] == WALL).sum() == 8


def test_a_street_over_water_becomes_a_bridge() -> None:
    grid, dry = _grid()
    dry[:, 10:13] = False
    lay_street(grid, dry, (1, 4), (25, 4), RULES)
    assert (grid[4, 10:13] == BRIDGE).all()


def test_a_bridge_has_railings_on_both_sides() -> None:
    grid, dry = _grid()
    dry[:, 10:13] = False
    lay_street(grid, dry, (1, 4), (25, 4), RULES)
    assert (grid[3, 10:13] == RAIL).all() and (grid[5, 10:13] == RAIL).all()


def test_water_wider_than_the_limit_is_not_bridged() -> None:
    grid, dry = _grid()
    dry[:, 10:20] = False
    assert not lay_street(grid, dry, (1, 4), (25, 4), RULES)


def test_a_failed_street_leaves_the_grid_untouched() -> None:
    grid, dry = _grid()
    dry[:, 10:20] = False
    before = grid.copy()
    lay_street(grid, dry, (1, 4), (25, 4), RULES)
    assert np.array_equal(grid, before)


def test_an_unreachable_goal_gives_no_street() -> None:
    grid, dry = _grid()
    grid[:, 12] = WALL
    assert not lay_street(grid, dry, (1, 4), (25, 4), RULES)


def test_later_streets_reuse_an_existing_one() -> None:
    # A second street between nearby points runs along the first instead of beside it.
    grid, dry = _grid()
    lay_street(grid, dry, (1, 4), (25, 4), RULES)
    before = int((grid == PATH).sum())
    lay_street(grid, dry, (5, 2), (20, 4), RULES)
    assert int((grid == PATH).sum()) - before < 20
