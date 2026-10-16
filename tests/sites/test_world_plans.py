"""Tests that hold for every site of a generated world: terrain-awareness, reachability and coverage."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import PASSABLE, read_patch, site_geometry, site_plan
from biomegen.world.tile import Cell
from biomegen.world.world import World
from tests.sites.conftest import HOUSE_ROOF

VOID = int(Cell.VOID)
OVER_WATER = {int(Cell.BRIDGE), int(Cell.BRIDGE_WALL)}
AFLOAT = {
    int(c) for c in (Cell.FLOOR, Cell.HULL, Cell.CARGO, Cell.WHEEL, Cell.AXLE_H, Cell.AXLE_V)
}  # boats, wheel, axle
_PASSABLE = np.array(sorted(PASSABLE))


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, 9999)


def _plans(world: World, cfg: Config):
    for poi in world.pois:
        geometry = site_geometry(poi, cfg)
        if geometry is None:
            continue
        for floor in range(poi.lowest_floor, poi.lowest_floor + poi.floor_count):
            plan = site_plan(poi, floor, cfg, world)
            if plan is not None:
                yield poi, geometry, plan


def test_nearly_every_site_has_a_plan(world: World, cfg: Config) -> None:
    sites = [poi for poi in world.pois if site_geometry(poi, cfg) is not None]
    planned = [poi for poi in sites if site_plan(poi, 0, cfg, world) is not None]
    assert sites and len(planned) >= 0.9 * len(sites)


def test_no_structure_stands_on_water(world: World, cfg: Config) -> None:
    # Away from boats and underground floors, every non-void plan cell is dry ground, except bridge decks and railings
    # (and a settlement's or a homestead's moored boats and its mill's wheel and axle).
    for poi, geometry, plan in _plans(world, cfg):
        if poi.kind == "boat" or plan.floor < 0:
            continue  # a boat floats; an underground floor is rock and has no surface to be on
        dry = read_patch(poi, geometry, world, cfg).dry
        allowed = OVER_WATER | AFLOAT if poi.civilized or poi.kind == "homestead" else OVER_WATER
        bad = (plan.cells != VOID) & ~dry & ~np.isin(plan.cells, list(allowed))
        assert not bad.any(), f"{poi.kind} at {poi.x},{poi.y} has {int(bad.sum())} cells over water"


def test_a_boat_is_all_on_water(world: World, cfg: Config) -> None:
    for poi, geometry, plan in _plans(world, cfg):
        if poi.kind == "boat":
            patch = read_patch(poi, geometry, world, cfg)
            assert not ((plan.cells != VOID) & ~patch.water).any()


def test_doors_and_stairs_are_mutually_reachable(world: World, cfg: Config) -> None:
    # Furniture must never trap a door or a stair: all of a floor's doors and stairs share one walkable component.
    special = [int(Cell.DOOR), int(Cell.STAIRS_UP), int(Cell.STAIRS_DOWN)]
    for poi, _geometry, plan in _plans(world, cfg):
        if poi.kind in ("camp", "boat") or poi.kind in {"capital", "city", "town", "village"} or poi.ruin_of:
            continue  # a settlement, or the ruin of one, is a town of buildings, not one structure
        labels, _ = ndimage.label(np.isin(plan.cells, _PASSABLE))
        marks = {int(labels[y, x]) for y, x in np.argwhere(np.isin(plan.cells, special)).tolist()}
        assert len(marks - {0}) <= 1, f"{poi.kind} at {poi.x},{poi.y} floor {plan.floor}"


def _side(cells: np.ndarray, road: np.ndarray, y: int, x: int) -> int:
    """The cell at ``(y, x)``, where the road's own cells (void in the plan) count as path and off the plan as void."""
    if not (0 <= y < cells.shape[0] and 0 <= x < cells.shape[1]):
        return VOID
    return int(Cell.PATH) if road[y, x] else int(cells[y, x])


def test_no_building_door_opens_onto_bare_ground(world: World, cfg: Config) -> None:
    # A door from a room (floor or furniture on one side) opens onto a street or road, never the empty terrain. A gate
    # cut in a city wall has no room beside it, and the road's own cells (void in the plan) count as path.
    outdoors = {VOID, int(Cell.WALL), int(Cell.DOOR), int(Cell.PATH), int(Cell.BRIDGE), int(Cell.TREE), int(Cell.BUSH)}
    for poi, geometry, plan in _plans(world, cfg):
        if poi.kind not in {"capital", "city", "town", "village"}:
            continue
        cells = plan.cells
        road = read_patch(poi, geometry, world, cfg).road
        for y, x in np.argwhere(cells == int(Cell.DOOR)).tolist():
            for (ay, ax), (by, bx) in (((y - 1, x), (y + 1, x)), ((y, x - 1), (y, x + 1))):
                a, b = _side(cells, road, ay, ax), _side(cells, road, by, bx)
                if (a in outdoors) != (b in outdoors):  # a room on one side
                    assert (a if a in outdoors else b) != VOID, f"{poi.kind} at {poi.x},{poi.y} floor {plan.floor}"


def test_the_ground_floor_of_a_structure_has_a_door(world: World, cfg: Config) -> None:
    for poi, _geometry, plan in _plans(world, cfg):
        if poi.kind in ("dungeon", "tower", "ruin") and plan.floor == 0:
            assert int(Cell.DOOR) in plan.cells, f"{poi.kind} at {poi.x},{poi.y}"


def test_every_settlement_has_at_least_one_house(world: World, cfg: Config) -> None:
    # A settlement is at least one house: some roof is seen from outside, whatever the shore does to its lots.
    empty = []
    for poi in world.pois:
        if poi.civilized:
            plan = site_plan(poi, 0, cfg, world)
            if plan is None or not (plan.outside == HOUSE_ROOF).any():
                empty.append((poi.kind, poi.x, poi.y))
    assert empty == []


def test_a_village_on_a_shore_with_no_room_for_lots_still_has_a_house(cfg: Config) -> None:
    # Seed 42's village at (165, 7) is half water; its lots found no room, and it used to have no building at all.
    shore = pipeline.generate(cfg, 42)
    poi = next(p for p in shore.pois if (p.x, p.y) == (165, 7))
    plan = site_plan(poi, 0, cfg, shore)
    assert plan is not None and (plan.outside == HOUSE_ROOF).any() and (plan.cells == int(Cell.DOOR)).any()


def test_the_house_of_a_crowded_shore_village_is_reached_by_a_street(cfg: Config) -> None:
    from scipy import ndimage as nd

    shore = pipeline.generate(cfg, 42)
    poi = next(p for p in shore.pois if (p.x, p.y) == (165, 7))
    plan = site_plan(poi, 0, cfg, shore)
    assert plan is not None
    streets = nd.binary_dilation(plan.cells == int(Cell.PATH), structure=np.ones((3, 3), bool))
    assert (streets & (plan.cells == int(Cell.DOOR))).any()
