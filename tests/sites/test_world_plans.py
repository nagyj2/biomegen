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

VOID = int(Cell.VOID)
OVER_WATER = {int(Cell.BRIDGE), int(Cell.BRIDGE_WALL)}
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
    # Away from boats and underground floors, every non-void plan cell is dry ground, except bridge decks and railings.
    for poi, geometry, plan in _plans(world, cfg):
        if poi.kind == "boat" or plan.floor < 0:
            continue  # a boat floats; an underground floor is rock and has no surface to be on
        dry = read_patch(poi, geometry, world, cfg).dry
        bad = (plan.cells != VOID) & ~dry & ~np.isin(plan.cells, list(OVER_WATER))
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
        if poi.kind in ("camp", "boat") or poi.kind in {"capital", "city", "town", "village"}:
            continue
        labels, _ = ndimage.label(np.isin(plan.cells, _PASSABLE))
        marks = {int(labels[y, x]) for y, x in np.argwhere(np.isin(plan.cells, special)).tolist()}
        assert len(marks - {0}) <= 1, f"{poi.kind} at {poi.x},{poi.y} floor {plan.floor}"


def test_no_building_door_opens_onto_bare_ground(world: World, cfg: Config) -> None:
    # In a settlement a door joins two rooms, or a room and a street: never a room and the empty terrain. (A gate in a
    # city wall has street on both ends, so it is skipped; a structure with no road may open onto bare ground.)
    street = {int(Cell.PATH), int(Cell.BRIDGE)}
    for poi, _geometry, plan in _plans(world, cfg):
        if poi.kind not in {"capital", "city", "town", "village"}:
            continue
        cells = plan.cells
        rows, cols = cells.shape
        for y, x in np.argwhere(cells == int(Cell.DOOR)).tolist():
            above = int(cells[y - 1, x]) if y else VOID
            below = int(cells[y + 1, x]) if y + 1 < rows else VOID
            left = int(cells[y, x - 1]) if x else VOID
            right = int(cells[y, x + 1]) if x + 1 < cols else VOID
            if (above in street and below in street) or (left in street and right in street):
                continue
            assert VOID not in (above, below, left, right), f"{poi.kind} at {poi.x},{poi.y} floor {plan.floor}"


def test_the_ground_floor_of_a_structure_has_a_door(world: World, cfg: Config) -> None:
    for poi, _geometry, plan in _plans(world, cfg):
        if poi.kind in ("dungeon", "tower", "ruin") and plan.floor == 0:
            assert int(Cell.DOOR) in plan.cells, f"{poi.kind} at {poi.x},{poi.y}"
