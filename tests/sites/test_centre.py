"""Tests for the centre building: one civic kind per settlement tier, standing in its reserved plot at the plaza."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.sites.kinds import lot_rows, lot_widths, roof_cell, tier_centre
from biomegen.world.manifest import SiteManifest
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


LADDER = ("hamlet", "village", "town", "city")  # what a settlement whose potential is a city is promoted through


def _plan_as(config: Config, tier: str, potential: str, floors: int = 1):
    """The ground floor of a POI whose potential is ``potential``, with the manifest of a settlement of ``tier``."""
    world = flat_world(20, 14)
    poi = add_poi(world, tier, 10, 7, pop=TIERS[tier], civilized=True, floor_count=floors, potential=potential)
    plan = site_plan(poi, 0, config, world, SiteManifest(tier, 1, 1, False))
    assert plan is not None
    return plan


@pytest.mark.parametrize("tier", LADDER[:-1])
def test_a_promotion_changes_nothing_outside_the_plot(config: Config, tier: str) -> None:
    # The plot is sized for the potential's centre, so a promotion (a new centre kind) leaves every other cell alone.
    before, after = _plan_as(config, tier, "city"), _plan_as(config, "city", "city")
    changed = (before.cells != after.cells) | (before.outside != after.outside)
    reserve = tier_centre(config, "city")
    apron = int(config.get(f"tables.buildings.{reserve}.apron"))
    plot_rows = lot_rows(config, reserve)[1] + 2 * apron
    plot_cols = lot_widths(config, reserve, 2.0)[1] + 2 * round(apron * 2.0)
    row0, row1, col0, col1 = _box(changed)
    assert changed.any() and row1 - row0 <= plot_rows and col1 - col0 <= plot_cols


def test_the_centre_follows_the_manifests_tier_not_the_potentials(config: Config) -> None:
    # A village that could be a city stands with a chapel at its plaza until it is promoted.
    plan = _plan_as(config, "village", "city")
    assert roof_cell(config, "chapel") in plan.outside and roof_cell(config, "cathedral") not in plan.outside
