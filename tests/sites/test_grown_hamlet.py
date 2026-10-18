"""Tests for a hamlet that grew from a homestead: the homestead's building is the hamlet's first, where it stood."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites import clear_cache, site_geometry, site_plan
from biomegen.sites.kinds import roof_cell
from biomegen.world.entities import POI
from biomegen.world.manifest import SiteManifest
from biomegen.world.tile import Cell
from tests.sites.conftest import add_poi, flat_world


@pytest.fixture(scope="module")
def cfg() -> Config:
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    return config


def _homestead(style: str = "farm", potential: str = "village") -> POI:
    return POI(kind="homestead", x=10, y=7, interior_seed=77, style=style, potential=potential)


def _plans(config: Config, style: str = "farm", potential: str = "village"):
    """The homestead's plan and the plan of the hamlet it grew into (same cell and seed), on one terrain."""
    world = flat_world(20, 14)
    homestead = add_poi(world, "homestead", 10, 7, interior_seed=77, style=style, potential=potential)
    clear_cache()
    before = site_plan(homestead, 0, config, world)
    other = flat_world(20, 14)
    hamlet = add_poi(other, "hamlet", 10, 7, interior_seed=77, style=style, potential=potential, civilized=True, pop=40)
    after = site_plan(hamlet, 0, config, other, SiteManifest("hamlet", 1, 1, False, grown_from=style))
    assert before is not None and after is not None
    return before, after


def _building(plan, kind: str):
    """The first building of ``kind``: its absolute cell rectangle (both plans share the cell grid) and footprint."""
    geometry = plan.geometry
    left, top = geometry.cam_x * geometry.cell_w + geometry.box[0], geometry.cam_y * geometry.cell_h + geometry.box[1]
    found = next(b for b in plan.buildings if b.kind == kind)
    return (left + found.x, top + found.y, found.width, found.height), found


def test_a_growing_homestead_is_drawn_on_its_potentials_grid(cfg: Config) -> None:
    homestead = site_geometry(_homestead(), cfg)
    village = cfg.get("tables.sites.village.rows_per_tile")
    assert homestead is not None and homestead.cell_h == village


def test_a_homestead_and_the_hamlet_it_grows_into_share_a_cell_grid(cfg: Config) -> None:
    hamlet = POI(kind="hamlet", x=10, y=7, interior_seed=77, style="farm", potential="village", civilized=True)
    homestead, grown = site_geometry(_homestead(), cfg), site_geometry(hamlet, cfg)
    assert homestead is not None and grown is not None
    assert (homestead.cell_w, homestead.cell_h) == (grown.cell_w, grown.cell_h)


def test_a_homestead_that_never_grows_keeps_its_own_grid(cfg: Config) -> None:
    mine = site_geometry(_homestead("mine", ""), cfg)
    assert mine is not None and mine.cell_h == cfg.get("tables.sites.homestead_mine.rows_per_tile")


@pytest.mark.parametrize("style", ["farm", "lodge"])
def test_the_hamlet_stamps_the_homesteads_building_where_it_stood(cfg: Config, style: str) -> None:
    before, after = _plans(cfg, style)
    kind = cfg.get(f"tables.poi_styles.{style}.building")
    (rect_before, _), (rect_after, _) = _building(before, kind), _building(after, kind)
    assert rect_before == rect_after


def test_the_stamped_building_has_the_homesteads_own_cells(cfg: Config) -> None:
    before, after = _plans(cfg, "farm")
    kind = cfg.get("tables.poi_styles.farm.building")
    (_, found_before), (_, found_after) = _building(before, kind), _building(after, kind)
    mine = before.cells[found_before.y : found_before.y + found_before.height, found_before.x :][
        : found_before.height, : found_before.width
    ]
    theirs = after.cells[found_after.y : found_after.y + found_after.height, found_after.x :][
        : found_after.height, : found_after.width
    ]
    assert np.array_equal(mine[found_before.footprint], theirs[found_after.footprint])


def test_the_homesteads_building_is_the_hamlets_only_one_of_its_kind(cfg: Config) -> None:
    _, after = _plans(cfg, "farm")
    kind = cfg.get("tables.poi_styles.farm.building")
    assert sum(1 for b in after.buildings if b.kind == kind) == 1


def test_the_door_of_the_stamped_building_opens_on_a_street(cfg: Config) -> None:
    _, after = _plans(cfg, "farm")
    kind = cfg.get("tables.poi_styles.farm.building")
    _, found = _building(after, kind)
    footprint = np.zeros(after.cells.shape, dtype=bool)
    footprint[found.y : found.y + found.height, found.x : found.x + found.width] = found.footprint
    doors = (after.cells == int(Cell.DOOR)) & ndimage.binary_dilation(footprint, iterations=1)
    near = ndimage.binary_dilation(doors, iterations=1) & ~footprint
    assert doors.any() and (after.cells[near] == int(Cell.PATH)).any()


def test_the_hamlet_still_has_its_centre_beside_the_homestead(cfg: Config) -> None:
    _, after = _plans(cfg, "farm")
    assert roof_cell(cfg, "gathering_point") in after.outside


def test_a_hamlet_whose_homestead_has_no_room_still_builds(cfg: Config) -> None:
    # A homestead that finds no spot gives the hamlet nothing to carry over: it places its own farmhouse.
    cramped = load_config(None)
    cramped.data["sites"]["size_jitter"] = 0.0
    cramped.data["tables"]["buildings"]["farmhouse"]["rows"] = [40, 40]
    world = flat_world(20, 14)
    hamlet = add_poi(
        world, "hamlet", 10, 7, interior_seed=77, style="farm", potential="village", civilized=True, pop=40
    )
    plan = site_plan(hamlet, 0, cramped, world, SiteManifest("hamlet", 1, 1, False, grown_from="farm"))
    assert plan is not None and roof_cell(cramped, "gathering_point") in plan.outside
