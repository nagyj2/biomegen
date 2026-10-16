"""Tests for dress variants: which cell a variant is, and which one a condition and a POI kind pick."""

from __future__ import annotations

import random

import pytest

from biomegen.config import load_config
from biomegen.sites.cells import OUTSIDE_PRIORITY
from biomegen.sites.dress import pick_variant, variant_cell, variant_of_cell, variants_for
from biomegen.sites.kinds import cell_name
from biomegen.world.tile import DRESS_BASE, DRESS_SLOTS, Cell

_CONFIG = load_config(None)


def _draws(condition: str, kind: str, count: int = 400, config=_CONFIG) -> set[str]:
    stream = random.Random(5)
    return {pick_variant(config, "field", condition, kind, stream) for _ in range(count)}


def test_full_wheat_is_the_existing_wheat_cell() -> None:
    assert variant_cell(_CONFIG, "field", "full") == int(Cell.WHEAT)


def test_a_variant_with_a_look_takes_a_cell_in_the_dress_block() -> None:
    cells = [variant_cell(_CONFIG, "field", name) for name in ("harvested", "dead")]
    assert cells == [DRESS_BASE, DRESS_BASE + 1] and all(
        max(int(c) for c in Cell) < c < DRESS_BASE + DRESS_SLOTS for c in cells
    )


def test_a_standing_site_draws_full_and_harvested_never_dead() -> None:
    assert _draws("standing", "homestead") == {"full", "harvested"}


def test_a_ruin_draws_harvested_and_dead_never_full() -> None:
    assert _draws("ruin", "ruin") == {"harvested", "dead"}


def test_the_draw_follows_the_weights() -> None:
    # Standing weights are 3 full to 1 harvested: full is drawn about three times as often.
    stream = random.Random(9)
    drawn = [pick_variant(_CONFIG, "field", "standing", "village", stream) for _ in range(4000)]
    assert 2.5 < drawn.count("full") / drawn.count("harvested") < 3.6


def test_a_variants_kinds_filter_keeps_it_from_other_kinds() -> None:
    config = load_config(None)
    config.data["tables"]["dress"]["field"]["variants"]["full"]["kinds"] = ["homestead"]
    assert (_draws("standing", "village", config=config), _draws("standing", "homestead", config=config)) == (
        {"harvested"},
        {"full", "harvested"},
    )


def test_no_variant_for_a_kind_and_condition_is_an_error() -> None:
    config = load_config(None)
    for variant in config.data["tables"]["dress"]["field"]["variants"].values():
        variant["kinds"] = ["homestead"]
    with pytest.raises(ValueError, match="no variant of dress 'field'"):
        pick_variant(config, "field", "standing", "village", random.Random(1))


def test_variants_for_lists_the_weights_in_name_order() -> None:
    assert variants_for(_CONFIG, "field", "ruin", "ruin") == [("dead", 2.0), ("harvested", 1.0)]


def test_a_dress_cell_names_its_variant_back() -> None:
    assert variant_of_cell(_CONFIG, DRESS_BASE + 1) == ("field", "dead")


def test_a_cell_outside_the_dress_block_is_no_variant() -> None:
    assert variant_of_cell(_CONFIG, int(Cell.WHEAT)) is None


def test_a_dress_variant_is_ground_cover_when_a_plan_is_drawn_smaller() -> None:
    assert OUTSIDE_PRIORITY[DRESS_BASE] == OUTSIDE_PRIORITY[int(Cell.WHEAT)]


def test_the_legend_names_a_dress_variant_by_its_label() -> None:
    assert cell_name(_CONFIG, DRESS_BASE) == "tilled field"


# --- laying a dressing (moved out of homestead.py) ---------------------------------------------------------------


def test_a_wheat_field_is_sown_with_the_full_wheat_cell_for_now() -> None:
    # Task 10 moves the dressing without changing it: a field still sows the one wheat cell (variants come in task 15).
    from biomegen.sites import site_plan
    from tests.sites.conftest import add_poi, flat_world

    world = flat_world(14, 10)
    poi = add_poi(world, "homestead", 7, 5, style="farm")
    plan = site_plan(poi, 0, _CONFIG, world)
    assert plan is not None and (plan.cells == int(Cell.WHEAT)).any()


def test_the_dressing_draws_are_a_pure_function_of_the_site_seed() -> None:
    from biomegen.sites import clear_cache, site_plan
    from tests.sites.conftest import add_poi, flat_world

    world = flat_world(14, 10)
    poi = add_poi(world, "homestead", 7, 5, style="lodge", interior_seed=11)
    first = site_plan(poi, 0, _CONFIG, world)
    clear_cache()
    second = site_plan(poi, 0, _CONFIG, world)
    assert first is not None and second is not None and (first.cells == second.cells).all()
