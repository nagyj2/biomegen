"""Tests for the World container: per-tile fields and km scale metadata."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, ChronicleEvent, Realm
from biomegen.world.tile import Relief
from biomegen.world.world import World

PHYSICAL_FIELDS = ("elevation_m", "temperature_c", "rain_mm", "relief", "landmass_id")


def test_bare_world_has_unit_km_cells() -> None:
    # Without a scale, one cell is 1 km square.
    world = World(8, 4, seed=1)
    assert (world.km_per_col, world.km_per_row) == (1.0, 1.0)


def test_world_reads_metadata_through_its_scale() -> None:
    # The four metadata accessors are the GridScale's values.
    scale = grid_scale(8, 4, (800.0, 200.0), 30.0, 10.0)
    world = World(8, 4, seed=1, scale=scale)
    assert (world.km_per_col, world.km_per_row, world.lat_top, world.lon_left) == (
        scale.km_per_col,
        scale.km_per_row,
        scale.lat_top,
        scale.lon_left,
    )


def test_fingerprint_ignores_scale_metadata() -> None:
    # Scale is metadata, not a per-tile field: two otherwise equal worlds hash the same.
    plain = World(8, 4, seed=1)
    scaled = World(8, 4, seed=1, scale=grid_scale(8, 4, (6000.0, 3000.0), 45.0, 0.0))
    assert plain.fingerprint() == scaled.fingerprint()


def test_physical_fields_are_registered() -> None:
    # The phase-3 arrays are in FIELDS, so fingerprint() and generic field loops cover them.
    assert set(PHYSICAL_FIELDS) <= set(World.FIELDS)


def test_new_world_has_flat_relief_and_no_landmass() -> None:
    # Before generation: no relief anywhere and every cell outside any landmass.
    world = World(8, 4, seed=1)
    assert (world.relief == int(Relief.NONE)).all() and (world.landmass_id == -1).all()


@pytest.mark.parametrize("name", PHYSICAL_FIELDS)
def test_fingerprint_covers_physical_field(name: str) -> None:
    world = World(8, 4, seed=1)
    before = world.fingerprint()
    getattr(world, name)[0, 0] = 3
    assert world.fingerprint() != before


def test_view_reads_physical_fields() -> None:
    world = World(8, 4, seed=1)
    world.elevation_m[1, 2] = 1250.0
    world.temperature_c[1, 2] = -4.5
    world.rain_mm[1, 2] = 640.0
    world.relief[1, 2] = int(Relief.HILLS)
    world.landmass_id[1, 2] = 0
    tile = world.view(2, 1)
    assert (tile.elevation_m, tile.temperature_c, tile.rain_mm, tile.relief, tile.landmass_id) == (
        1250.0,
        -4.5,
        640.0,
        Relief.HILLS,
        0,
    )


def test_physical_field_shapes_match_grid() -> None:
    world = World(8, 4, seed=1)
    assert all(np.shape(getattr(world, name)) == (4, 8) for name in PHYSICAL_FIELDS)


def test_normalised_legacy_fields_are_gone() -> None:
    # Phase 3 replaced the normalised elevation / temperature with metres and °C.
    world = World(8, 4, seed=1)
    assert not {"elevation", "temperature"} & set(World.FIELDS)
    assert not hasattr(world, "elevation") and not hasattr(world, "temperature")


def test_new_world_has_no_realms() -> None:
    # Before the realms stage every cell is wild and nothing is a war front.
    world = World(8, 4, seed=1)
    assert (world.realm_id == -1).all() and not world.front.any()


def test_realm_arrays_have_expected_dtypes() -> None:
    # realm_id is int16 (a few dozen realms at most); front is a bool mask.
    world = World(8, 4, seed=1)
    assert (world.realm_id.dtype, world.front.dtype) == (np.dtype(np.int16), np.dtype(bool))


@pytest.mark.parametrize("name", ("realm_id", "front"))
def test_fingerprint_covers_political_field(name: str) -> None:
    world = World(8, 4, seed=1)
    before = world.fingerprint()
    getattr(world, name)[0, 0] = 1
    assert world.fingerprint() != before


def test_realm_at_reads_the_realm_array() -> None:
    # realm_at returns the Realm indexed by realm_id, and None for wild cells.
    world = World(8, 4, seed=1)
    world.realms.append(Realm(id=0, kind="major"))
    world.realm_id[1, 2] = 0
    assert (world.realm_at(2, 1), world.realm_at(0, 0)) == (world.realms[0], None)


def test_view_reads_realm_id() -> None:
    world = World(8, 4, seed=1)
    world.realm_id[1, 2] = 3
    assert world.view(2, 1).realm_id == 3


def _history_world() -> World:
    world = World(6, 3, seed=1)
    world.pois.append(POI(kind="town", x=2, y=1, interior_seed=1))
    world.poi_index[1, 2] = 0
    world.chronicle = [
        ChronicleEvent(id=0, year=10, kind="founding", realm_ids=[0], location=(0, 0)),
        ChronicleEvent(id=1, year=20, kind="settling", realm_ids=[0], poi_ids=[0]),
        ChronicleEvent(id=2, year=30, kind="war", realm_ids=[0, 1]),
    ]
    return world


def test_new_world_has_no_history() -> None:
    # Before the history stage: year 0, no events and no fallen realms.
    world = World(6, 3, seed=1)
    assert (world.year, world.chronicle, world.fallen_realms) == (0, [], [])


def test_events_until_keeps_events_up_to_the_year() -> None:
    # The year bound is inclusive.
    assert [e.id for e in _history_world().events_until(20)] == [0, 1]


def test_events_at_matches_a_location() -> None:
    assert [e.id for e in _history_world().events_at(0, 0)] == [0]


def test_events_at_matches_the_poi_on_the_cell() -> None:
    # An event naming the settlement at a cell is found there though its own location is unset.
    assert [e.id for e in _history_world().events_at(2, 1)] == [1]


def test_events_of_lists_the_events_naming_a_realm() -> None:
    assert [e.id for e in _history_world().events_of(1)] == [2]


def test_events_at_matches_an_event_the_poi_is_marked_by() -> None:
    # A POI made by an event lists it in event_ids, so it is found at the POI's cell though the event names no POI.
    world = _history_world()
    world.pois[0].event_ids = [2]
    assert [e.id for e in world.events_at(2, 1)] == [1, 2]


def test_the_ruler_in_a_year_is_the_reign_that_began_before_it() -> None:
    from biomegen.world.entities import Ruler

    world = World(4, 4, 1)
    world.rulers = [
        Ruler(id=0, realm_id=0, from_year=10, to_year=300, style="martial"),
        Ruler(id=1, realm_id=0, from_year=300, to_year=None, style="gentle"),
        Ruler(id=2, realm_id=1, from_year=50, to_year=None, style="pious"),
    ]
    assert [world.ruler_at(0, y).id for y in (10, 299, 300, 900)] == [0, 0, 1, 1]  # type: ignore[union-attr]


def test_the_ruler_before_a_founding_is_the_founder_and_a_realm_without_rulers_has_none() -> None:
    from biomegen.world.entities import Ruler

    world = World(4, 4, 1)
    world.rulers = [Ruler(id=0, realm_id=0, from_year=10, to_year=None, style="martial")]
    assert world.ruler_at(0, 1).id == 0 and world.ruler_at(5, 100) is None  # type: ignore[union-attr]


def test_a_new_world_has_no_predecessors() -> None:
    assert World(4, 4, 1).predecessors == []
