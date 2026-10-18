"""Tests for the specialized slots of a settlement plan: fixed spots, of which the manifest says how many are built."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.sites.kinds import kind_row, roof_cell
from biomegen.sites.surroundings import settlement_kinds
from biomegen.world.manifest import SiteManifest
from biomegen.world.tile import Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

TREE_CELLS = [int(Cell.TREE), int(Cell.BUSH)]
HOUSES = 3


@pytest.fixture(scope="module")
def cfg() -> Config:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _setup(config: Config, specialized: int, walled: bool = False, tier: str = "town", river: bool = True):
    """A river town (potential city) whose manifest has ``specialized`` slots built; returns its plan and kind list."""
    world = flat_world(16, 12)
    if river:
        world.water_type[:, 7] = int(WaterType.FRESH)
    poi = add_poi(world, tier, 6, 6, civilized=True, pop=3000, potential="city", tags=("river",) if river else ())
    kinds = settlement_kinds(world, config, poi)
    clear_cache()
    plan = site_plan(poi, 0, config, world, SiteManifest(tier, HOUSES, specialized, walled))
    assert plan is not None
    return plan, kinds


def _production(config: Config, plan) -> list[tuple[str, int, int, int, int]]:
    skip = {"house", "hall", "chapel", "cathedral", "palace", "gathering_point"}
    return [(b.kind, b.x, b.y, b.width, b.height) for b in plan.buildings if b.kind not in skip]


def test_the_river_town_is_chosen_several_specialized_kinds(cfg: Config) -> None:
    _, kinds = _setup(cfg, 0)
    assert len(kinds) >= 3 and "mill" in kinds


@pytest.mark.parametrize("built", [0, 1, 2, 3])
def test_a_manifest_builds_the_first_slots_it_names(cfg: Config, built: int) -> None:
    plan, kinds = _setup(cfg, built)
    assert sorted(kind for kind, *_ in _production(cfg, plan)) == sorted(kinds[:built])


@pytest.mark.parametrize("built", [0, 1, 2])
def test_one_more_slot_adds_one_building_and_moves_none(cfg: Config, built: int) -> None:
    smaller, _ = _setup(cfg, built)
    larger, _ = _setup(cfg, built + 1)
    small, large = set(_production(cfg, smaller)), set(_production(cfg, larger))
    assert small < large and len(large - small) == 1


@pytest.mark.parametrize("built", [0, 1, 2])
def test_one_more_slot_leaves_every_house_and_the_centre_where_it_was(cfg: Config, built: int) -> None:
    smaller, _ = _setup(cfg, built)
    larger, _ = _setup(cfg, built + 1)

    def others(plan):
        return [(b.kind, b.x, b.y) for b in plan.buildings if b.kind in ("house", "hall")]

    assert others(smaller) == others(larger)


@pytest.mark.parametrize("built", [0, 1, 2])
def test_an_unbuilt_slots_ground_stays_clear(cfg: Config, built: int) -> None:
    # The spot the next slot will take has no building, tree or bush on it until it is built.
    smaller, _ = _setup(cfg, built)
    larger, _ = _setup(cfg, built + 1)
    (kind, x, y, width, height) = sorted(set(_production(cfg, larger)) - set(_production(cfg, smaller)))[0]
    spot = smaller.outside[y : y + height, x : x + width]
    assert not np.isin(spot, TREE_CELLS + [roof_cell(cfg, kind), roof_cell(cfg, "house")]).any()


@pytest.mark.parametrize("built", [0, 1, 2])
def test_one_more_slot_changes_the_plan_only_round_its_spot(cfg: Config, built: int) -> None:
    smaller, _ = _setup(cfg, built)
    larger, _ = _setup(cfg, built + 1)
    (kind, x, y, width, height) = sorted(set(_production(cfg, larger)) - set(_production(cfg, smaller)))[0]
    near = np.zeros(smaller.cells.shape, dtype=bool)
    near[max(0, y - 20) : y + height + 20, max(0, x - 30) : x + width + 30] = True  # the field reaches up the plan
    differs = (smaller.cells != larger.cells) | (smaller.outside != larger.outside)
    assert differs.any() and not (differs & ~near).any()


def test_a_mill_has_its_wheel_only_when_its_slot_is_built(cfg: Config) -> None:
    kinds = _setup(cfg, 0)[1]
    slot = kinds.index("mill")
    unbuilt, built = _setup(cfg, slot), _setup(cfg, slot + 1)
    assert int(Cell.WHEEL) not in unbuilt[0].cells and int(Cell.WHEEL) in built[0].cells


def test_a_slot_that_finds_no_spot_is_left_out(cfg: Config) -> None:
    cramped = load_config(None)
    cramped.data["sites"]["size_jitter"] = 0.0
    cramped.data["tables"]["buildings"]["farmhouse"]["rows"] = [40, 40]
    plan, kinds = _setup(cramped, 3, river=False)
    assert "farmhouse" in kinds and roof_cell(cramped, "farmhouse") not in plan.outside


# --- the wall -------------------------------------------------------------------------------------------------------


def _city(config: Config, walled: bool):
    world = flat_world(24, 16)
    poi = add_poi(world, "city", 12, 8, civilized=True, pop=20000, potential="city")
    clear_cache()
    plan = site_plan(poi, 0, config, world, SiteManifest("city", HOUSES, 2, walled))
    assert plan is not None
    return plan


def test_a_wall_adds_no_building_and_moves_none(cfg: Config) -> None:
    free, walled = _city(cfg, False), _city(cfg, True)
    assert [(b.kind, b.x, b.y) for b in free.buildings] == [(b.kind, b.x, b.y) for b in walled.buildings]


def test_a_wall_changes_the_plan_only_along_the_wall(cfg: Config) -> None:
    # What differs lies within a few cells of the wall: the wall itself and the trees it clears.
    free, walled = _city(cfg, False), _city(cfg, True)
    stone = walled.outside == int(Cell.STONE)
    differs = (free.cells != walled.cells) | (free.outside != walled.outside)
    reach = ndimage.binary_dilation(stone, iterations=3)
    assert stone.any() and not (differs & ~reach).any()


def test_every_production_kind_has_a_siting_the_slots_know(cfg: Config) -> None:
    # A new siting needs a placement in _place_kinds; this fails until it has one.
    sitings = {
        kind_row(cfg, kind)["siting"]
        for kind in cfg.get("tables.buildings")
        if kind_row(cfg, kind)["function"] == "production"
    }
    assert sitings <= {"edge", "any", "shore", "river"}
