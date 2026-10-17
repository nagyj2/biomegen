"""Tests for the territory planner's static fields (``pipeline/story/territory_fields.py``)."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.pipeline.story.territory_fields import territory_fields
from biomegen.world.entities import POI, Realm
from biomegen.world.world import World


def _small_world() -> World:
    # Realm 0 holds columns 0-3 and seats at a POI on (1, 1); realm 1 holds columns 5-7 and has no seat.
    world = World(8, 4, 1)
    world.realm_id[:, :4] = 0
    world.realm_id[:, 5:] = 1
    world.realms = [Realm(id=0, kind="major", seat_poi=0), Realm(id=1, kind="tribal")]
    world.pois = [POI(kind="capital", x=1, y=1, interior_seed=1)]
    return world


def test_a_seat_settlement_is_the_realms_seat() -> None:
    assert territory_fields(_small_world()).seats[0] == (1, 1)


def test_a_seatless_realm_is_seated_at_its_middle() -> None:
    assert territory_fields(_small_world()).seats[1] == (6, 1)  # the held cell nearest the mean, first in row order


def test_the_seat_is_zero_km_from_itself() -> None:
    fields = territory_fields(_small_world())
    assert float(fields.seat_km[1, 1]) == 0.0


def test_distance_grows_with_the_gap_to_the_seat() -> None:
    fields = territory_fields(_small_world())
    assert float(fields.seat_km[1, 3]) == pytest.approx(2.0)  # two 1 km columns away


def test_cells_no_realm_holds_have_no_distance() -> None:
    fields = territory_fields(_small_world())
    assert np.isinf(fields.seat_km[:, 4]).all()


@pytest.fixture(scope="module")
def generated() -> World:
    return pipeline.generate(load_config(None), 42)


def test_every_held_cell_of_a_generated_world_has_a_finite_distance(generated: World) -> None:
    fields = territory_fields(generated)
    held = generated.realm_id >= 0
    assert np.isfinite(fields.seat_km[held]).all() and np.isinf(fields.seat_km[~held]).all()


def test_the_fields_are_deterministic(generated: World) -> None:
    first, second = territory_fields(generated), territory_fields(generated)
    assert first.seats == second.seats and np.array_equal(first.seat_km, second.seat_km)
