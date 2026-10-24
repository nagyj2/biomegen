"""Tests for the camp layout: clearing, tents (a roof outside, bedrolls inside), wagon, supplies and the road track."""

from __future__ import annotations

import numpy as np

from biomegen.config.model import Config
from biomegen.sites import read_patch, site_geometry, site_plan, site_roof_floor
from biomegen.sites.kinds import roof_cell
from biomegen.world.tile import Biome, Cell, WaterType
from tests.sites.conftest import add_poi, flat_world

VOID, BED, FIRE = (int(c) for c in (Cell.VOID, Cell.BED, Cell.CAMPFIRE))


def _camp(config: Config, world=None):
    world = world or flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return poi, world, plan


def test_a_camp_has_one_campfire(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int((plan.cells == FIRE).sum()) == 1


def test_the_campfire_is_near_the_middle_of_the_clearing(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    ys, xs = np.nonzero(plan.cells != VOID)
    fy, fx = (int(v[0]) for v in np.nonzero(plan.cells == FIRE))
    assert abs(fx - (xs.min() + xs.max()) / 2) <= 3 and abs(fy - (ys.min() + ys.max()) / 2) <= 3


def test_a_camp_has_at_least_the_minimum_tents(config: Config) -> None:
    # Tents are separate blobs of TENT cells; overlapping pitches may merge, so count cells instead of blobs.
    _poi, _world, plan = _camp(config)
    assert int((plan.outside == roof_cell(config, "tent")).sum()) >= int(config.get("sites.camp.min_tents")) * 4


def test_the_clearing_is_bare_ground_outside_the_plan_edge(config: Config) -> None:
    # The clearing is an ellipse: the corners of the plan stay void so terrain shows through.
    _poi, _world, plan = _camp(config)
    assert plan.cells[0, 0] == VOID and plan.cells[-1, -1] == VOID


def test_a_camp_has_no_walls(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert int(Cell.WALL) not in plan.cells


def test_a_camp_is_open_air_but_for_its_tents(config: Config) -> None:
    # The sky view differs from the inside only where a tent's roof covers it.
    _poi, _world, plan = _camp(config)
    assert (plan.cells != plan.outside).any() and (
        plan.outside[plan.cells != plan.outside] == roof_cell(config, "tent")
    ).all()


def _founding_camp(config: Config, seed: int):
    """A founding camp (one tent) for a seed: its plan, so the bedding of a single tent can be read on its own."""
    world = flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5, purpose="founding", interior_seed=seed)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None and len(plan.buildings) == 1
    return plan


def _bedding_box(plan) -> tuple[int, int, int, int, int, int]:
    """Return ``(tent width, tent height, bedding left, top, width, height)`` of the plan's one tent."""
    tent = plan.buildings[0]
    bed = plan.cells[tent.y : tent.y + tent.height, tent.x : tent.x + tent.width] == BED
    ys, xs = np.nonzero(bed)
    return (
        tent.width,
        tent.height,
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )


def test_the_bedding_of_a_tent_never_reaches_its_edge(config: Config) -> None:
    # A margin of at least one cell is left on every side between the bedrolls and the tent's edge.
    for seed in range(12):
        width, height, left, top, bed_w, bed_h = _bedding_box(_founding_camp(config, seed))
        assert left >= 1 and top >= 1 and left + bed_w <= width - 1 and top + bed_h <= height - 1


def test_the_bedding_is_not_always_one_smaller_than_the_tent(config: Config) -> None:
    # Its size varies: across seeds the room left round it takes more than one value.
    margins = set()
    for seed in range(12):
        width, height, _left, _top, bed_w, bed_h = _bedding_box(_founding_camp(config, seed))
        margins.add((width - bed_w, height - bed_h))
    assert len(margins) > 1


def test_gear_lies_on_the_bare_floor_of_a_tent(config: Config) -> None:
    # Some gear lies under a roof, and every cell under a tent roof is bedding, floor or gear.
    world = flat_world(14, 10)
    poi = add_poi(world, "camp", 7, 5, purpose="army", interior_seed=9)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    under = plan.cells[plan.outside == roof_cell(config, "tent")]
    gear = [int(Cell.CHEST), int(Cell.CRATE), int(Cell.BARREL), int(Cell.SHELF)]
    assert np.isin(under, gear).any() and np.isin(under, [BED, int(Cell.FLOOR), *gear]).all()


def test_a_camp_has_a_roof_level_that_shows_its_tents_as_roofs(config: Config) -> None:
    poi, world, plan = _camp(config)
    roof = site_plan(poi, site_roof_floor(poi, config), config, world)
    assert roof is not None and np.array_equal(roof.cells, plan.outside) and (roof.cells == FIRE).any()


def test_every_tent_of_a_camp_is_a_listed_building(config: Config) -> None:
    _poi, _world, plan = _camp(config)
    assert plan.buildings and {building.kind for building in plan.buildings} == {"tent"}


def test_a_camp_keeps_off_water(config: Config) -> None:
    world = flat_world(14, 10, Biome.GRASS)
    world.biome[:, :6] = int(Biome.SHALLOW)
    world.water_type[:, :6] = int(WaterType.SALT)
    poi, world, plan = _camp(config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert not ((plan.cells != VOID) & patch.water).any()


def test_a_road_runs_through_the_camp_clear_of_the_tents(config: Config) -> None:
    # The road arrives from the east and runs on to the fire: the plan leaves its cells void and pitches no tent on it.
    world = flat_world(14, 10)
    world.road[5, 7:14] = 1
    poi, _world, plan = _camp(config, world)
    patch = read_patch(poi, site_geometry(poi, config), world, config)
    assert patch.gates and not (patch.road & (plan.outside == roof_cell(config, "tent"))).any()


def test_a_camp_without_a_road_has_no_gate(config: Config) -> None:
    poi, world, _plan = _camp(config)
    assert read_patch(poi, site_geometry(poi, config), world, config).gates == ()


def test_a_purpose_selects_its_own_site_row(config: Config) -> None:
    # An army camp's row (camp_army) is larger than the plain camp row, so its site spans more of the window.
    world = flat_world(14, 10)
    plain, army = add_poi(world, "camp", 3, 5), add_poi(world, "camp", 10, 5, purpose="army")
    first, second = site_geometry(plain, config), site_geometry(army, config)
    assert (
        first is not None
        and second is not None
        and second.extent[2] - second.extent[0] > first.extent[2] - first.extent[0]
    )


def test_a_purpose_without_a_row_falls_back_to_the_plain_kind(config: Config) -> None:
    world = flat_world(14, 10)
    odd, plain = add_poi(world, "camp", 3, 5, purpose="picnic"), add_poi(world, "camp", 3, 5)
    assert site_geometry(odd, config) == site_geometry(plain, config)


def test_every_camp_purpose_row_builds_a_plan(config: Config) -> None:
    for purpose in ("founding", "bandit", "army"):
        world = flat_world(14, 10)
        assert site_plan(add_poi(world, "camp", 7, 5, purpose=purpose), 0, config, world) is not None


def test_an_army_camp_pitches_more_tents_than_a_bandit_camp(config: Config) -> None:
    # Same site seed, so only the purpose row differs.
    world = flat_world(14, 10)
    counts = {}
    for purpose in ("army", "bandit"):
        poi = add_poi(world, "camp", 7, 5, purpose=purpose, interior_seed=9)
        plan = site_plan(poi, 0, config, world)
        assert plan is not None
        counts[purpose] = int((plan.outside == roof_cell(config, "tent")).sum())
        world.poi_index[5, 7] = -1
        world.pois.pop()
    assert counts["army"] > counts["bandit"]


def test_a_founding_camp_keeps_fewer_tents_than_a_bandit_camp(config: Config) -> None:
    world = flat_world(14, 10)
    counts = {}
    for purpose in ("founding", "bandit"):
        poi = add_poi(world, "camp", 7, 5, purpose=purpose, interior_seed=9)
        plan = site_plan(poi, 0, config, world)
        assert plan is not None
        counts[purpose] = int((plan.outside == roof_cell(config, "tent")).sum())
        world.poi_index[5, 7] = -1
        world.pois.pop()
    assert counts["founding"] < counts["bandit"]
