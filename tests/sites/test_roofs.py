"""Tests for the roof system every site shares: a roof is a building kind's, and every roofed building is listed."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.config.model import Config
from biomegen.sites import site_plan, site_roof_floor
from biomegen.sites.kinds import kind_of_cell
from tests.sites.conftest import add_poi, flat_world

ROOFED = ["tower", "watchtower", "dungeon", "ruin", "shrine", "camp", "homestead", "village"]


def _roofs(config: Config, cells: np.ndarray) -> set[str]:
    """The building kinds whose roof is drawn in ``cells``."""
    return {kind_of_cell(config, int(cell)) for cell in np.unique(cells)} - {None}  # type: ignore[arg-type]


def _poi(kind: str):
    world = flat_world(16, 12)
    fields = {"pop": 500, "civilized": True} if kind == "village" else {}
    return world, add_poi(world, kind, 8, 6, **fields)


@pytest.mark.parametrize("kind", ROOFED)
def test_every_roof_seen_from_outside_belongs_to_a_listed_building(config: Config, kind: str) -> None:
    # The sky view holds only kind roofs, and each kind drawn there is a building the plan lists.
    world, poi = _poi(kind)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None and _roofs(config, plan.outside) == {building.kind for building in plan.buildings}


@pytest.mark.parametrize("kind", ROOFED)
def test_the_roof_level_is_the_sky_view_of_the_roofed_buildings(config: Config, kind: str) -> None:
    # Above the top storey every building shows as its roof, whichever layout built the site.
    world, poi = _poi(kind)
    ground = site_plan(poi, 0, config, world)
    roof = site_plan(poi, site_roof_floor(poi, config), config, world)
    assert ground is not None and roof is not None and _roofs(config, roof.cells) == _roofs(config, ground.outside)


def test_a_structure_roofs_its_own_kind(config: Config) -> None:
    # A tower, a watchtower and a dungeon's gatehouse each have a roof of their own, not a shared plain one.
    kinds = {}
    for kind in ("tower", "watchtower", "dungeon"):
        world, poi = _poi(kind)
        plan = site_plan(poi, 0, config, world)
        assert plan is not None
        kinds[kind] = _roofs(config, plan.outside)
    assert kinds == {"tower": {"tower"}, "watchtower": {"watchtower"}, "dungeon": {"gatehouse"}}


def test_a_battlefield_has_no_roof_level(config: Config) -> None:
    # Nothing is built on a battlefield, so it has no roof to show.
    _world, poi = _poi("battlefield")
    assert site_roof_floor(poi, config) is None
