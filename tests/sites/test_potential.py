"""Tests for the potential: the largest tier a site could grow into, stored on the POI."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites.potential import assign_potentials, land_capacity, potential_floor, potential_tier
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from biomegen.world.world import World
from tests.sites.conftest import add_poi, flat_world

# A world 40 cells wide of 25 x 50 km cells (the default grid), so 1000 km across: room of 300 km is 12 cells.
WIDE = 40


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


def _rank(config: Config, tier: str) -> int:
    return int(config.get(f"tables.tiers.{tier}.rank"))


def _world(config: Config) -> World:
    world = flat_world(WIDE, 12)
    world.scale = grid_scale(WIDE, 12, (WIDE * 25.0, 12 * 50.0), 30.0, 0.0)
    return world


def _village(world: World, x: int, y: int) -> POI:
    return add_poi(world, "village", x, y, civilized=True, pop=300)


# --- what a POI is at least ---------------------------------------------------------------------------------------


def test_a_settlement_is_at_least_its_own_tier(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="town", x=0, y=0, interior_seed=1, civilized=True)) == "town"


def test_a_ruin_is_at_least_the_tier_it_was(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="ruin", x=0, y=0, interior_seed=1, ruin_of="city")) == "city"


def test_a_homestead_whose_style_grows_is_at_least_a_hamlet(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="homestead", x=0, y=0, interior_seed=1, style="farm")) == "hamlet"


def test_a_homestead_whose_style_never_grows_has_no_plan(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="homestead", x=0, y=0, interior_seed=1, style="mine")) == ""


def test_a_tower_has_no_plan(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="tower", x=0, y=0, interior_seed=1)) == ""


def test_a_ruin_with_no_origin_has_no_plan(cfg: Config) -> None:
    assert potential_floor(cfg, POI(kind="ruin", x=0, y=0, interior_seed=1)) == ""


# --- the land ----------------------------------------------------------------------------------------------------


def test_the_capacity_of_open_water_is_zero(cfg: Config) -> None:
    world = _world(cfg)
    world.water_type[:] = int(WaterType.SALT)
    assert land_capacity(world, cfg, _village(world, 20, 6)) == 0.0


def test_the_capacity_of_one_biome_is_that_biomes_habitability(cfg: Config) -> None:
    world = _world(cfg)
    expected = float(cfg.get("tables.biomes.grass.habitability")) * float(
        cfg.get("tables.relief.none.habitability_mul")
    )
    assert land_capacity(world, cfg, _village(world, 20, 6)) == pytest.approx(expected)


def test_poor_land_keeps_a_village_a_village(cfg: Config) -> None:
    world = _world(cfg)
    world.biome[:] = int(Biome.DESERT)
    assert potential_tier(world, cfg, _village(world, 20, 6)) == "village"


# --- the room ----------------------------------------------------------------------------------------------------


def test_a_village_alone_on_good_land_could_grow_into_a_city(cfg: Config) -> None:
    world = _world(cfg)
    assert potential_tier(world, cfg, _village(world, 20, 6)) == "city"


def test_a_settlement_of_note_close_by_takes_the_room_a_town_needs(cfg: Config) -> None:
    world = _world(cfg)
    site = _village(world, 20, 6)
    _village(world, 28, 6)  # 8 columns = 200 km, under a town's 300 km spacing
    assert potential_tier(world, cfg, site) == "village"


def test_a_settlement_beyond_a_towns_spacing_leaves_it_room(cfg: Config) -> None:
    world = _world(cfg)
    site = _village(world, 6, 6)
    _village(world, 19, 6)  # 13 columns = 325 km, past a town's 300 km but under a city's 420 km
    assert potential_tier(world, cfg, site) == "town"


def test_a_hamlet_beside_a_site_takes_no_room(cfg: Config) -> None:
    # A hamlet is not a settlement of note (near_target is false), so it does not crowd a site's room.
    world = _world(cfg)
    site = _village(world, 20, 6)
    add_poi(world, "hamlet", 21, 6, civilized=True, pop=30)
    assert potential_tier(world, cfg, site) == "city"


# --- the floor ---------------------------------------------------------------------------------------------------


def test_a_city_on_poor_land_keeps_a_citys_plan(cfg: Config) -> None:
    world = _world(cfg)
    world.biome[:] = int(Biome.DESERT)
    city = add_poi(world, "city", 20, 6, civilized=True, pop=12000)
    assert potential_tier(world, cfg, city) == "city"


def test_a_capital_is_never_anyone_elses_potential(cfg: Config) -> None:
    world = _world(cfg)
    assert potential_tier(world, cfg, _village(world, 20, 6)) != "capital"


def test_a_poi_not_yet_in_the_world_is_judged_against_the_settlements_that_stand(cfg: Config) -> None:
    # A simulation prices the site of a POI it is about to mint.
    world = _world(cfg)
    _village(world, 28, 6)
    minted = POI(kind="village", x=20, y=6, interior_seed=5, civilized=True)
    assert potential_tier(world, cfg, minted) == "village"


def test_a_poi_with_no_plan_has_an_empty_potential(cfg: Config) -> None:
    world = _world(cfg)
    assert potential_tier(world, cfg, add_poi(world, "tower", 5, 5)) == ""


# --- the pass over a world ---------------------------------------------------------------------------------------


def test_the_pass_stores_each_pois_potential(cfg: Config) -> None:
    world = _world(cfg)
    site = _village(world, 20, 6)
    tower = add_poi(world, "tower", 5, 5)
    assign_potentials(world, cfg)
    assert (site.potential, tower.potential) == ("city", "")


def test_the_pass_leaves_the_same_potentials_on_a_second_run(cfg: Config) -> None:
    world = _world(cfg)
    _village(world, 20, 6)
    _village(world, 28, 6)
    assign_potentials(world, cfg)
    first = [poi.potential for poi in world.pois]
    assign_potentials(world, cfg)
    assert [poi.potential for poi in world.pois] == first


@pytest.fixture(scope="module", params=(42, 7))
def generated(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def test_every_poi_with_a_plan_has_a_potential_and_the_rest_none(generated: World, cfg: Config) -> None:
    assert all(bool(poi.potential) == bool(potential_floor(cfg, poi)) for poi in generated.pois)


def test_no_potential_is_below_what_the_poi_is(generated: World, cfg: Config) -> None:
    assert all(
        _rank(cfg, poi.potential) <= _rank(cfg, potential_floor(cfg, poi)) for poi in generated.pois if poi.potential
    )


def test_only_a_capital_has_the_capital_potential(generated: World) -> None:
    # The tier row has no potential_land, so no other settlement, ruin or homestead can grow into it.
    assert all(
        poi.kind == "capital" or poi.ruin_of == "capital" for poi in generated.pois if poi.potential == "capital"
    )


def test_a_generated_world_has_some_site_that_could_grow_beyond_its_tier(generated: World, cfg: Config) -> None:
    assert any(
        _rank(cfg, poi.potential) < _rank(cfg, potential_floor(cfg, poi)) for poi in generated.pois if poi.potential
    )


def test_the_potentials_are_the_same_on_a_second_generation(generated: World, cfg: Config) -> None:
    again = pipeline.generate(cfg, generated.seed)
    assert [poi.potential for poi in again.pois] == [poi.potential for poi in generated.pois]
