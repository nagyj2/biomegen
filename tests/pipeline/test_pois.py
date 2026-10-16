"""Tests for wild POI placement: counts, km spacing, surfaces, elevation, floors and determinism."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline import pois
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World

WILD = ("tower", "dungeon", "ruin", "camp", "boat")


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, 9999)


def _island(width: int = 60, height: int = 30) -> World:
    """A grass island (30 km cells, 100 m high) ringed by sea, with no settlements."""
    world = World(width, height, 1, grid_scale(width, height, (width * 30.0, height * 30.0), 30.0, 0.0))
    world.water_type[:] = int(WaterType.SALT)
    world.biome[:] = int(Biome.SHALLOW)
    world.dist_to_ocean[:] = 1000.0
    land = (slice(3, height - 3), slice(3, width - 3))
    world.water_type[land] = int(WaterType.NONE)
    world.biome[land] = int(Biome.GRASS)
    world.elevation_m[land] = 100.0
    return world


def _wild_config(**rows: dict) -> Config:
    """Defaults with ``tables.pois`` replaced by the given kinds."""
    config = load_config(None)
    config.data["tables"]["pois"] = rows
    return config


def _camp(**overrides: object) -> dict:
    return {"km2_per_poi": 20000.0, "min_spacing_km": 60.0, "biomes": ["grass"], "floors": 1, **overrides}


# --------------------------------------------------------------------------- generated world
def test_only_location_kinds_are_placed_by_the_poi_stage(world: World, cfg: Config) -> None:
    # Settlements come from another stage, history kinds from events and style kinds from the styles pass: the location
    # pass places the rest.
    rows = cfg.get("tables.pois")
    assert {kind for kind, row in rows.items() if row["source"] not in ("history", "style")} == set(WILD)


def test_poi_index_refs_are_consistent(world: World) -> None:
    # Every POI's anchor cell points back at it.
    assert all(int(world.poi_index[p.y, p.x]) == i for i, p in enumerate(world.pois))


def test_land_pois_on_land_boats_on_water(world: World) -> None:
    for p in world.pois:
        if p.kind == "boat":
            assert world.water_type[p.y, p.x] != int(WaterType.NONE)
        else:
            assert world.water_type[p.y, p.x] == int(WaterType.NONE)


def test_a_wild_poi_keeps_its_spacing_from_every_earlier_poi(world: World, cfg: Config) -> None:
    # Each POI placed by location was placed no closer than its kind's min_spacing_km to any POI placed before it
    # (a POI an event made is placed by its own rule and is not held to it).
    types = cfg.get("tables.pois")
    scale = world.scale
    for i, p in enumerate(world.pois):
        if p.kind not in types or p.event_ids:
            continue
        spacing = float(types[p.kind]["min_spacing_km"])
        for q in world.pois[:i]:
            km = float(np.hypot((p.x - q.x) * scale.km_per_col, (p.y - q.y) * scale.km_per_row))
            assert km >= spacing - 1e-6


def test_placement_deterministic(cfg: Config) -> None:
    a = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    b = [(p.kind, p.x, p.y) for p in pipeline.generate(cfg, 4242).pois]
    assert a == b


def test_pois_respect_their_metre_elevation_limits(world: World, cfg: Config) -> None:
    # Every placed POI anchor sits within its kind's elevation_min_m / elevation_max_m band.
    for p in world.pois:
        rule = cfg.get(f"tables.pois.{p.kind}", {})
        height = float(world.elevation_m[p.y, p.x])
        assert height >= rule.get("elevation_min_m", float("-inf"))
        assert height <= rule.get("elevation_max_m", float("inf"))


def test_dungeons_descend_and_other_kinds_start_at_the_ground(world: World) -> None:
    for p in world.pois:
        if p.kind == "dungeon":
            assert p.lowest_floor == -(p.floor_count - 1)
        elif p.kind in WILD:
            assert p.lowest_floor == 0


# --------------------------------------------------------------------------- synthetic island
def test_count_is_land_area_over_km2_per_poi() -> None:
    # 54 x 24 land cells of 900 km2 hold 1,166,400 km2: one camp per 200,000 km2 asks for six.
    island = _island()
    pois.place_by_location(island, _wild_config(camp=_camp(km2_per_poi=200000.0)), 5)
    assert sum(1 for p in island.pois if p.kind == "camp") == 6


def test_density_multiplies_the_count() -> None:
    one, two = _island(), _island()
    pois.place_by_location(one, _wild_config(camp=_camp(km2_per_poi=200000.0)), 5)
    config = _wild_config(camp=_camp(km2_per_poi=200000.0))
    config.data["poi"]["density"] = 2.0
    pois.place_by_location(two, config, 5)
    assert len(two.pois) == 2 * len(one.pois)


def test_boats_count_sea_area_and_stand_on_water() -> None:
    island = _island()
    boat = _camp(km2_per_poi=500000.0, biomes=["shallow"], on_water=True)
    pois.place_by_location(island, _wild_config(boat=boat), 5)
    assert island.pois and all(island.water_type[p.y, p.x] != int(WaterType.NONE) for p in island.pois)


def test_elevation_cap_keeps_a_kind_off_high_ground() -> None:
    island = _island()
    island.elevation_m[:, 30:] = 900.0
    pois.place_by_location(island, _wild_config(camp=_camp(elevation_max_m=500.0)), 5)
    assert island.pois and all(p.x < 30 for p in island.pois)


def test_stage_is_deterministic_on_an_island() -> None:
    first, second = _island(), _island()
    config = _wild_config(camp=_camp())
    pois.place_by_location(first, config, 5)
    pois.place_by_location(second, config, 5)
    assert [(p.x, p.y) for p in first.pois] == [(p.x, p.y) for p in second.pois]


def test_remoteness_pushes_a_kind_away_from_a_settlement() -> None:
    # With no jitter and ties broken row-major, a kind without remoteness would take the north-west corner; with
    # remoteness and a settlement on the west side, its single pick lands in the east half.
    island = _island()
    island.pois.append(POI(kind="village", x=10, y=15, interior_seed=0, civilized=True))
    island.poi_index[15, 10] = 0
    config = _wild_config(camp=_camp(km2_per_poi=2000000.0, remoteness=5.0))
    config.data["poi"]["jitter"] = 0.0
    pois.place_by_location(island, config, 5)
    assert island.pois[1].x > 30


def test_footprint_mask_needs_enough_dry_land() -> None:
    # A 3x3 footprint on a 5x5 land patch with one water cell: half the footprint must be land to qualify.
    world = World(5, 5, 1)
    world.water_type[:] = int(WaterType.NONE)
    world.water_type[2, 2] = int(WaterType.SALT)
    assert pois.footprint_land_fraction_mask(world, 3, 3, 0.9)[2, 2] is np.False_
    assert pois.footprint_land_fraction_mask(world, 3, 3, 0.5)[2, 2] is np.True_


def test_generated_camps_take_their_row_purpose(world: World, cfg: Config) -> None:
    # The camp row names a purpose; every placed camp carries it and no other kind has one.
    purpose = cfg.get("tables.pois.camp.purpose")
    assert purpose and all((p.purpose == purpose) == (p.kind == "camp") for p in world.pois)


def _two_realm_island() -> World:
    """The island with its west half held by realm 0 (seated at the far west) and its east half wild."""
    from biomegen.world.entities import Realm

    island = _island()
    island.realm_id[:, :30] = 0
    island.pois.append(POI(kind="village", x=4, y=15, interior_seed=0, civilized=True))
    island.poi_index[15, 4] = 0
    island.realms = [Realm(id=0, kind="major", seat_poi=0)]
    return island


def test_a_wild_weight_pulls_a_kind_onto_wild_land() -> None:
    # With no jitter and a flat island, only the wild weight tells the halves apart: the pick lands in the east.
    island = _two_realm_island()
    config = _wild_config(camp=_camp(km2_per_poi=2000000.0, wild=5.0))
    config.data["poi"]["jitter"] = 0.0
    pois.place_by_location(island, config, 5)
    assert island.pois[-1].x >= 30 and island.pois[-1].realm_id == -1


def test_a_seat_remoteness_weight_pushes_a_kind_away_from_the_seat() -> None:
    island = _two_realm_island()
    config = _wild_config(camp=_camp(km2_per_poi=2000000.0, seat_remoteness=5.0))
    config.data["poi"]["jitter"] = 0.0
    pois.place_by_location(island, config, 5)
    assert island.pois[-1].x > 30


def test_a_poi_takes_the_realm_of_its_cell_when_placed() -> None:
    island = _two_realm_island()
    pois.place_by_location(island, _wild_config(camp=_camp(km2_per_poi=200000.0)), 5)
    placed = island.pois[1:]  # the village was there before the stage
    assert placed and all(p.realm_id == int(island.realm_id[p.y, p.x]) for p in placed)


# --------------------------------------------------------------------------- build_poi and commit
def test_commit_appends_exactly_what_build_poi_builds() -> None:
    # commit is build_poi plus the append: same POI, taking its realm from the map, indexed at its cell.
    world = _island()
    world.realm_id[10, 12] = 3
    index = pois.commit(world, 7, "camp", 12, 10, (1, 0), purpose="bandit", connect=False, founded=40)
    expected = pois.build_poi(7, "camp", 12, 10, (1, 0), realm_id=3, purpose="bandit", connect=False, founded=40)
    assert (world.pois[index], int(world.poi_index[10, 12])) == (expected, index)


def test_build_poi_makes_a_settlement_with_every_field() -> None:
    # A hamlet-like POI: civilized, a population, tags, a style and a founding year all land on the POI.
    poi = pois.build_poi(
        7, "hamlet", 5, 6, (1, 0), civilized=True, pop=42, tags=("river",), style="farm", founded=900, realm_id=2
    )
    assert (poi.civilized, poi.pop, poi.tags, poi.style, poi.founded, poi.realm_id) == (
        True,
        42,
        ("river",),
        "farm",
        900,
        2,
    )


def test_build_poi_seeds_its_interior_from_its_cell() -> None:
    # The interior seed is keyed on the cell (as commit always did), so the same cell always draws the same plan.
    a = pois.build_poi(7, "tower", 5, 6, (3, 0))
    b = pois.build_poi(7, "tower", 5, 6, (3, 0))
    assert a.interior_seed == b.interior_seed != pois.build_poi(7, "tower", 6, 5, (3, 0)).interior_seed


def test_build_poi_keeps_at_least_one_floor() -> None:
    assert pois.build_poi(7, "camp", 1, 1, (0, 0)).floor_count == 1
