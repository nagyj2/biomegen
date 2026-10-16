"""Tests for the centre building: one civic kind per settlement tier, standing in its reserved plot at the plaza."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.sites.kinds import lot_rows, lot_widths, roof_cell, tier_reserve
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world

TIERS = {"hamlet": 40, "village": 500, "town": 3000, "city": 12000, "capital": 60000}
CENTRES = {
    "hamlet": "gathering_point",
    "village": "chapel",
    "town": "hall",
    "city": "cathedral",
    "capital": "palace",
}


def _plan(config: Config, tier: str, floor: int = 0, floors: int = 1):
    world = flat_world(20, 14)
    poi = add_poi(world, tier, 10, 7, pop=TIERS[tier], civilized=True, floor_count=floors)
    plan = site_plan(poi, floor, config, world)
    assert plan is not None
    return plan


def _box(mask: np.ndarray) -> tuple[int, int, int, int]:
    """The bounding box ``(row0, row1, col0, col1)`` (end exclusive) of the True cells of ``mask``."""
    rows, cols = np.nonzero(mask)
    return int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_every_tier_has_its_centre_building(config: Config, tier: str) -> None:
    # The tier's centre kind (hamlet gathering point ... capital palace) is seen from outside, whatever else stands.
    plan = _plan(config, tier)
    assert roof_cell(config, CENTRES[tier]) in plan.outside


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_the_centre_stands_at_the_plaza(config: Config, tier: str) -> None:
    # On flat ground the plaza is the middle of the extent, and the centre building is centred on it.
    plan = _plan(config, tier)
    row0, row1, col0, col1 = _box(plan.outside == roof_cell(config, CENTRES[tier]))
    rows, cols = plan.outside.shape
    assert abs((row0 + row1) / 2 - rows / 2) <= 3 and abs((col0 + col1) / 2 - cols / 2) <= 6


@pytest.mark.parametrize("tier", sorted(TIERS))
def test_the_centres_door_opens_on_the_street(config: Config, tier: str) -> None:
    # A door of the centre building has street (its forecourt) beside it on the outside.
    plan = _plan(config, tier)
    footprint = plan.outside == roof_cell(config, CENTRES[tier])
    doors = (plan.cells == int(Cell.DOOR)) & ndimage.binary_dilation(footprint, iterations=1)
    near = ndimage.binary_dilation(doors, iterations=1) & ~footprint
    assert doors.any() and (plan.cells[near] == int(Cell.PATH)).any()


def test_the_centre_is_deterministic(config: Config) -> None:
    first = _plan(config, "village")
    clear_cache()
    second = _plan(config, "village")
    assert np.array_equal(first.cells, second.cells)


def test_the_centre_rises_to_the_tops_floor(config: Config) -> None:
    # The lot nearest the plaza is the tallest: the city's cathedral has a storey on the top floor.
    top = _plan(config, "city", floor=2, floors=3)
    footprint = _plan(config, "city").outside == roof_cell(config, "cathedral")
    assert (top.cells[footprint] == int(Cell.FLOOR)).any()


SWAPS = {  # a smaller or equal civic kind drawn in the same plot
    "hamlet": "chapel",
    "village": "gathering_point",
    "town": "chapel",
    "city": "hall",
    "capital": "cathedral",
}


@pytest.mark.parametrize("tier", sorted(SWAPS))
def test_a_centre_kind_swap_changes_nothing_outside_the_plot(config: Config, tier: str) -> None:
    # The plot is sized by the reserve kind, so drawing another centre in it leaves every other cell as it was.
    other = load_config(None)
    other.data["sites"]["size_jitter"] = 0.0
    other.data["sites"]["pop_scale"] = [1.0, 1.0]
    other.data["tables"]["tiers"][tier]["reserve"] = tier_reserve(config, tier)  # the capital reserves its own centre
    other.data["tables"]["tiers"][tier]["centre"] = SWAPS[tier]
    a, b = _plan(config, tier), _plan(other, tier)
    changed = (a.cells != b.cells) | (a.outside != b.outside)
    reserve = tier_reserve(config, tier)
    apron = int(config.get(f"tables.buildings.{reserve}.apron"))
    plot_rows = lot_rows(config, reserve)[1] + 2 * apron
    plot_cols = lot_widths(config, reserve, 2.0)[1] + 2 * round(apron * 2.0)
    row0, row1, col0, col1 = _box(changed)
    assert changed.any() and row1 - row0 <= plot_rows and col1 - col0 <= plot_cols


def test_a_larger_reserve_makes_a_larger_plaza_square(config: Config) -> None:
    # The forecourt follows the reserve kind: reserving a palace paves more than reserving the town's own hall.
    wide = load_config(None)
    wide.data["sites"]["size_jitter"] = 0.0
    wide.data["sites"]["pop_scale"] = [1.0, 1.0]
    wide.data["tables"]["tiers"]["village"]["reserve"] = "palace"
    own = _plan(config, "village")
    big = _plan(wide, "village")
    assert (big.cells == int(Cell.PATH)).sum() > (own.cells == int(Cell.PATH)).sum()
