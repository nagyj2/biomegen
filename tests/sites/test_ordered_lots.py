"""Tests for the ordered lots of a settlement: the houses a manifest says stand are the first lots of one fixed plan."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_plan
from biomegen.sites.kinds import building_counts
from biomegen.world.manifest import SiteManifest
from tests.sites.conftest import add_poi, flat_world


@pytest.fixture(scope="module")
def cfg() -> Config:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _plan(config: Config, houses: int, floor: int = 0, floors: int = 1, tier: str = "town"):
    world = flat_world(24, 16)
    poi = add_poi(world, tier, 12, 8, civilized=True, pop=3000, floor_count=floors, potential="city")
    clear_cache()
    plan = site_plan(poi, floor, config, world, SiteManifest(tier, houses, 1, False))
    assert plan is not None
    return plan


def _houses(plan) -> list[tuple[int, int, int, int]]:
    return [(b.x, b.y, b.width, b.height) for b in plan.buildings if b.kind == "house"]


@pytest.mark.parametrize("houses", [0, 1, 3, 6])
def test_a_manifest_with_n_houses_draws_n_houses(cfg: Config, houses: int) -> None:
    assert len(_houses(_plan(cfg, houses))) == houses


@pytest.mark.parametrize("houses", [1, 2, 4, 7])
def test_one_more_house_is_the_same_plan_with_one_more_lot(cfg: Config, houses: int) -> None:
    # The houses of the smaller plan are the first houses of the larger, in the same places.
    smaller, larger = _houses(_plan(cfg, houses)), _houses(_plan(cfg, houses + 1))
    assert larger[:houses] == smaller and len(larger) == houses + 1


@pytest.mark.parametrize("houses", [1, 2, 4, 7])
def test_one_more_house_changes_the_plan_only_near_it(cfg: Config, houses: int) -> None:
    # Streets, plaza, centre and every other building stay; only ground by the new lot (its door's path, trees) changes.
    smaller, larger = _plan(cfg, houses), _plan(cfg, houses + 1)
    x, y, width, height = _houses(larger)[-1]
    changed = np.argwhere((smaller.cells != larger.cells) | (smaller.outside != larger.outside))
    margin_rows, margin_cols = 6, 12
    assert changed.size and (
        (changed[:, 0] >= y - margin_rows).all()
        and (changed[:, 0] < y + height + margin_rows).all()
        and (changed[:, 1] >= x - margin_cols).all()
        and (changed[:, 1] < x + width + margin_cols).all()
    )


@pytest.mark.parametrize("houses", [1, 3, 5])
def test_one_more_house_leaves_the_storeys_of_the_others_alone(cfg: Config, houses: int) -> None:
    # The upper floor of the smaller plan shows the same buildings, whichever lots stand beside them.
    smaller, larger = _plan(cfg, houses, floor=1, floors=2), _plan(cfg, houses + 1, floor=1, floors=2)
    x, y, width, height = _houses(_plan(cfg, houses + 1))[-1]
    outside = np.ones(smaller.cells.shape, dtype=bool)
    outside[max(0, y - 6) : y + height + 6, max(0, x - 12) : x + width + 12] = False
    assert np.array_equal(smaller.cells[outside], larger.cells[outside])


def test_the_centre_and_the_specialized_buildings_do_not_depend_on_the_houses(cfg: Config) -> None:
    few, many = _plan(cfg, 1), _plan(cfg, 6)
    kinds = [(b.kind, b.x, b.y) for b in few.buildings if b.kind != "house"]
    assert kinds == [(b.kind, b.x, b.y) for b in many.buildings if b.kind != "house"]


def test_a_manifest_with_more_houses_than_the_ground_holds_fills_it_and_stops(cfg: Config) -> None:
    packed = building_counts(_plan(cfg, 999).buildings)
    assert 0 < dict(packed)["house"] < 999


def test_a_manifest_with_no_houses_still_has_its_centre(cfg: Config) -> None:
    assert ("hall", 1) in building_counts(_plan(cfg, 0).buildings)
