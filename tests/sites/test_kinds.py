"""Tests for the building kinds' plan cells (the reserved roof block)."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.sites.cells import OUTSIDE_PRIORITY
from biomegen.sites.kinds import cell_name, centre_kind, kind_of_cell, kind_row, roof_cell
from biomegen.world.entities import POI
from biomegen.world.tile import KIND_ROOF_BASE, KIND_ROOF_SLOTS, Cell

_CONFIG = load_config(None)
_KINDS = sorted(_CONFIG.get("tables.buildings"))


def test_a_kinds_roof_cell_is_the_block_base_plus_its_rank() -> None:
    assert [roof_cell(_CONFIG, kind) for kind in _KINDS] == [
        KIND_ROOF_BASE + kind_row(_CONFIG, kind)["rank"] for kind in _KINDS
    ]


def test_every_roof_cell_lies_in_the_block_clear_of_the_cell_enum() -> None:
    cells = [roof_cell(_CONFIG, kind) for kind in _KINDS]
    assert all(max(int(c) for c in Cell) < cell < KIND_ROOF_BASE + KIND_ROOF_SLOTS for cell in cells)


def test_a_roof_cell_names_its_kind_back() -> None:
    assert [kind_of_cell(_CONFIG, roof_cell(_CONFIG, kind)) for kind in _KINDS] == _KINDS


def test_a_cell_outside_the_block_is_no_kind() -> None:
    assert kind_of_cell(_CONFIG, int(Cell.TABLE)) is None


def test_an_unused_block_cell_is_no_kind() -> None:
    assert kind_of_cell(_CONFIG, KIND_ROOF_BASE + KIND_ROOF_SLOTS - 1) is None


def test_the_legend_names_a_kind_by_its_label_and_an_enum_cell_by_its_name() -> None:
    assert (cell_name(_CONFIG, roof_cell(_CONFIG, "gathering_point")), cell_name(_CONFIG, int(Cell.TABLE))) == (
        "gathering point",
        "table",
    )


def test_a_kind_roof_draws_over_a_street_and_ties_with_a_solid_wall() -> None:
    # A roof of any kind beats a street when a plan is drawn smaller, as a solid wall does.
    house = OUTSIDE_PRIORITY[roof_cell(_CONFIG, "house")]
    assert house == OUTSIDE_PRIORITY[int(Cell.STONE)] > OUTSIDE_PRIORITY[int(Cell.PATH)]


def _poi(kind: str, ruin_of: str = "") -> POI:
    return POI(kind=kind, x=0, y=0, interior_seed=1, ruin_of=ruin_of)


def test_a_settlement_poi_has_its_tiers_centre() -> None:
    assert [centre_kind(_CONFIG, _poi(tier)) for tier in ("hamlet", "village", "town", "city", "capital")] == [
        "gathering_point",
        "chapel",
        "hall",
        "cathedral",
        "palace",
    ]


def test_a_ruin_has_the_centre_of_the_tier_it_was() -> None:
    assert centre_kind(_CONFIG, _poi("ruin", ruin_of="town")) == "hall"


def test_a_homestead_or_a_wild_site_has_no_centre() -> None:
    assert [centre_kind(_CONFIG, _poi(kind)) for kind in ("homestead", "tower", "dungeon", "ruin")] == [None] * 4


# --- the buildings of a plan ---------------------------------------------------------------------------------------


def _town_plan():
    from biomegen.sites import site_plan
    from tests.sites.conftest import add_poi, flat_world

    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    world = flat_world(16, 12)
    poi = add_poi(world, "town", 8, 6, pop=3000, civilized=True)
    plan = site_plan(poi, 0, config, world)
    assert plan is not None
    return config, plan


def test_a_plan_lists_its_buildings_centre_first() -> None:
    _config, plan = _town_plan()
    assert plan.buildings[0].kind == "hall" and len(plan.buildings) >= 2


def test_building_counts_group_the_kinds_in_order() -> None:
    import numpy as np

    from biomegen.sites.layout import SiteBuilding

    one = np.ones((2, 2), dtype=bool)
    buildings = tuple(SiteBuilding(kind, 0, 0, 2, 2, one) for kind in ("hall", "house", "house", "mill"))
    from biomegen.sites.kinds import building_counts

    assert building_counts(buildings) == [("hall", 1), ("house", 2), ("mill", 1)]


def test_a_cell_under_a_roof_names_its_building() -> None:
    from biomegen.sites.kinds import building_at

    _config, plan = _town_plan()
    hall = plan.buildings[0]
    left, top, _r, _b = plan.geometry.box
    cell = (left + hall.x + hall.width // 2, top + hall.y + hall.height // 2)
    assert building_at(plan, *cell) == "hall"


def test_a_cell_off_every_roof_names_no_building() -> None:
    from biomegen.sites.kinds import building_at

    _config, plan = _town_plan()
    assert building_at(plan, plan.geometry.box[0], plan.geometry.box[1]) is None


def test_a_ruin_lists_only_the_buildings_that_stand() -> None:
    from biomegen.sites import site_plan
    from tests.sites.conftest import add_poi, flat_world

    config = load_config(None)
    world = flat_world(16, 12)
    world.year = 1200
    ruin = add_poi(world, "ruin", 8, 6, pop=3000, ruin_of="town", floor_count=1)
    plan = site_plan(ruin, 0, config, world)
    assert plan is not None and plan.buildings[0].kind == "hall"


def test_a_homestead_lists_its_one_building() -> None:
    from biomegen.sites import site_plan
    from tests.sites.conftest import add_poi, flat_world

    config = load_config(None)
    world = flat_world(16, 12)
    plan = site_plan(add_poi(world, "homestead", 7, 5, style="mine"), 0, config, world)
    assert plan is not None and [b.kind for b in plan.buildings] == ["mine"]
