"""Tests for the realms stage: seeds, claiming over the move-cost surface, tribes and the recorded realms."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.civilization import realms
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, Relief, WaterType
from biomegen.world.world import World

CELL_KM = 30.0  # one column; rows are 60 km, so a strip's cells are 30 km apart along x


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def generated(cfg: Config) -> World:
    return pipeline.generate(cfg, 42)


def _config(**politics: float) -> Config:
    """Defaults with no tribes, every major of strength 1, a huge budget, and ``politics`` overrides."""
    config = load_config(None)
    config.data["politics"].update({"tribe_max": 0, "claim_budget_km": 1.0e6, "city_state_chance": 0.0})
    config.data["politics"]["city_state_far_chance"] = 0.0
    config.data["politics"].update(politics)
    for kind in ("major", "city_state", "tribal"):
        config.data["tables"]["realm_kinds"][kind]["strength"] = [1.0, 1.0]
    return config


def _strip(width: int = 40, height: int = 1) -> World:
    """A flat grass land of ``width x height`` cells, 30 km wide and 60 km tall."""
    world = World(width, height, 1, grid_scale(width, height, (width * CELL_KM, height * 60.0), 30.0, 0.0))
    world.biome[:] = int(Biome.GRASS)
    world.dist_to_ocean[:] = 100.0
    return world


def _settle(world: World, kind: str, x: int, y: int = 0, pop: int = 1000) -> int:
    poi = POI(kind=kind, x=x, y=y, interior_seed=1, civilized=True, pop=pop)
    world.poi_index[y, x] = len(world.pois)
    world.pois.append(poi)
    return len(world.pois) - 1


def _run(world: World, config: Config) -> World:
    realms.run(world, config, 1)
    return world


# --- a whole generated world ------------------------------------------------------------------------------------------


def test_every_capital_founds_one_major_realm(generated: World) -> None:
    # One seat per major realm: the majors' seats are exactly the capitals, each used once.
    seats = sorted(r.seat_poi for r in generated.realms if r.kind == "major")
    assert seats == sorted(i for i, p in enumerate(generated.pois) if p.kind == "capital")


def test_realm_ids_index_the_realm_list(generated: World) -> None:
    # Every claimed cell names a real realm; the rest are -1.
    ids = generated.realm_id
    assert ids.max() < len(generated.realms) and ids.min() >= -1


def test_water_is_never_claimed(generated: World) -> None:
    # Coastal hops are stepping stones: no water cell ends up in a realm.
    assert (
        generated.realm_id[np.isin(generated.biome, [int(Biome.DEEP), int(Biome.SHALLOW), int(Biome.LAKE)])] == -1
    ).all()


def test_a_realm_holds_its_seat(generated: World) -> None:
    # A realm's seat settlement lies inside the realm.
    seated = [r for r in generated.realms if r.seat_poi >= 0]
    assert all(generated.pois[r.seat_poi].realm_id == r.id for r in seated)


def test_every_poi_takes_the_realm_under_its_anchor(generated: World) -> None:
    assert all(p.realm_id == int(generated.realm_id[p.y, p.x]) for p in generated.pois)


def test_realm_ids_follow_seed_order(generated: World) -> None:
    # Majors come first (capital order), then city-states, then tribes.
    order = {"major": 0, "city_state": 1, "tribal": 2}
    kinds = [order[r.kind] for r in generated.realms]
    assert kinds == sorted(kinds) and [r.id for r in generated.realms] == list(range(len(generated.realms)))


# --- claiming ---------------------------------------------------------------------------------------------------------


def test_a_stronger_realm_claims_more_ground() -> None:
    # A city-state of a quarter the strength, 40 cells from the capital, holds well under half of what the capital does.
    config = _config(city_state_chance=1.0)
    config.data["tables"]["realm_kinds"]["city_state"]["strength"] = [0.25, 0.25]
    world = _strip(60)
    _settle(world, "capital", 10)
    _settle(world, "city", 50)
    _run(world, config)
    assert (world.realm_id == 0).sum() > 2 * (world.realm_id == 1).sum()


def test_a_tie_goes_to_the_earlier_cell() -> None:
    # Two equal seeds meet at a cell equally far from both; the frontier earlier in row-major order wins it.
    world = _strip(31)
    _settle(world, "capital", 10)
    _settle(world, "capital", 20)
    _run(world, _config())
    assert int(world.realm_id[0, 15]) == 0


def test_the_budget_limits_how_far_a_realm_reaches() -> None:
    # 300 km is ten 30 km steps: a cell seven steps out is claimed, one thirty out is wild.
    world = _strip(60)
    _settle(world, "capital", 5)
    _run(world, _config(claim_budget_km=300.0))
    assert (int(world.realm_id[0, 12]), int(world.realm_id[0, 40])) == (0, -1)


def test_costly_terrain_slows_a_realm() -> None:
    # Mountains (move cost 8 more per cell) stop a realm that open grass would let through.
    world = _strip(60)
    world.relief[0, 10:20] = int(Relief.MOUNTAIN)
    _settle(world, "capital", 5)
    _run(world, _config(claim_budget_km=600.0))
    assert int(world.realm_id[0, 30]) == -1


def test_a_river_cell_is_claimed() -> None:
    # A river keeps its land biome under fresh water and is part of the realm it crosses.
    world = _strip(10)
    world.water_type[0, 6] = int(WaterType.FRESH)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert int(world.realm_id[0, 6]) == 0


def test_a_lake_is_not_claimed() -> None:
    world = _strip(10)
    world.biome[0, 6] = int(Biome.LAKE)
    world.water_type[0, 6] = int(WaterType.FRESH)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert int(world.realm_id[0, 6]) == -1


def _islet() -> World:
    """Land at columns 0-9, a three-column strait of salt water, then land at columns 13-19."""
    world = _strip(20)
    world.biome[0, 10:13] = int(Biome.SHALLOW)
    world.water_type[0, 10:13] = int(WaterType.SALT)
    return world


def test_a_realm_hops_a_strait_to_reach_an_islet() -> None:
    world = _islet()
    _settle(world, "capital", 2)
    _run(world, _config())
    assert int(world.realm_id[0, 17]) == 0


def test_the_strait_itself_is_not_claimed() -> None:
    world = _islet()
    _settle(world, "capital", 2)
    _run(world, _config())
    assert (world.realm_id[0, 10:13] == -1).all()


def test_no_hop_leaves_the_islet_wild() -> None:
    world = _islet()
    _settle(world, "capital", 2)
    _run(world, _config(coastal_hop_km=0.0))
    assert int(world.realm_id[0, 17]) == -1


# --- seeds ------------------------------------------------------------------------------------------------------------


def test_a_far_city_founds_a_city_state_when_it_is_certain() -> None:
    world = _strip(60)
    _settle(world, "capital", 2)
    _settle(world, "city", 55)
    _run(world, _config(city_state_far_km=500.0, city_state_far_chance=1.0))
    assert [r.kind for r in world.realms] == ["major", "city_state"]


def test_a_near_city_stays_a_city_when_only_far_ones_qualify() -> None:
    world = _strip(60)
    _settle(world, "capital", 2)
    _settle(world, "city", 10)
    _run(world, _config(city_state_far_km=500.0, city_state_far_chance=1.0))
    assert [r.kind for r in world.realms] == ["major"]


def test_a_city_state_is_seated_in_its_city() -> None:
    world = _strip(60)
    _settle(world, "capital", 2)
    city = _settle(world, "city", 55)
    _run(world, _config(city_state_chance=1.0))
    assert world.realms[1].seat_poi == city


def test_a_world_without_capitals_has_no_major_realm() -> None:
    world = _strip(20)
    _settle(world, "city", 5)
    _run(world, _config(city_state_chance=1.0))
    assert [r.kind for r in world.realms] == ["city_state"]


# --- tribes -----------------------------------------------------------------------------------------------------------


def _tribe_config(**politics: float) -> Config:
    return _config(**{"claim_budget_km": 300.0, "tribe_max": 1, "tribe_min_area_km2": 1000.0, **politics})


def test_a_tribe_takes_a_large_unclaimed_area() -> None:
    world = _strip(60)
    _settle(world, "capital", 5)
    _run(world, _tribe_config())
    assert [r.kind for r in world.realms] == ["major", "tribal"]


def test_a_tribe_is_seated_at_the_most_populous_settlement() -> None:
    world = _strip(60)
    _settle(world, "capital", 5)
    _settle(world, "village", 40, pop=50)
    town = _settle(world, "town", 45, pop=900)
    _run(world, _tribe_config())
    assert world.realms[1].seat_poi == town


def test_a_tribe_without_a_settlement_has_no_seat() -> None:
    world = _strip(60)
    _settle(world, "capital", 5)
    _run(world, _tribe_config())
    assert world.realms[1].seat_poi == -1


def test_a_small_unclaimed_area_founds_no_tribe() -> None:
    world = _strip(60)
    _settle(world, "capital", 5)
    _run(world, _tribe_config(tribe_min_area_km2=1.0e9))
    assert [r.kind for r in world.realms] == ["major"]


# --- the recorded realm -----------------------------------------------------------------------------------------------


def test_realm_area_is_its_cells_in_km2() -> None:
    world = _strip(20)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert world.realms[0].area_km2 == pytest.approx(20 * world.scale.cell_area_km2)


def test_realm_population_counts_its_settlements() -> None:
    world = _strip(20)
    _settle(world, "capital", 2, pop=5000)
    _settle(world, "village", 9, pop=70)
    _run(world, _config())
    assert world.realms[0].pop >= 5070


def test_dominant_biome_is_the_most_common_one() -> None:
    world = _strip(20)
    world.biome[0, :13] = int(Biome.FOREST)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert world.realms[0].dominant_biome == int(Biome.FOREST)


def test_a_mostly_hilly_realm_is_highland() -> None:
    world = _strip(20)
    world.relief[0, :12] = int(Relief.HILLS)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert world.realms[0].highland


def test_a_flat_realm_is_not_highland() -> None:
    world = _strip(20)
    _settle(world, "capital", 2)
    _run(world, _config())
    assert not world.realms[0].highland


def test_running_twice_gives_the_same_partition() -> None:
    first, second = _strip(60), _strip(60)
    for world in (first, second):
        _settle(world, "capital", 5)
        _settle(world, "capital", 50)
        _settle(world, "city", 28)
        _run(world, _config(city_state_chance=1.0))
    assert (first.realm_id == second.realm_id).all()
