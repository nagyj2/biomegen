"""Tests for the specialized buildings a settlement is chosen to have, from what lies round it."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.sites.surroundings import settlement_kinds
from biomegen.util.rng import LABELS
from biomegen.world.tile import Biome, WaterType
from tests.sites.conftest import add_poi, flat_world

TIERS = ["hamlet", "village", "town", "city", "capital"]


def _world(biome: Biome = Biome.GRASS, fresh: bool = False, sea: bool = False):
    world = flat_world(40, 24, biome)
    if fresh:
        world.water_type[:, 4:6] = int(WaterType.FRESH)  # a river: about 5% of the land round
    if sea:
        world.water_type[:, 0:4] = int(WaterType.SALT)  # a sea: about 10%
    return world


def _kinds(world, config: Config, tier: str = "town", pop: int | None = None, **fields) -> list[str]:
    poi = add_poi(world, tier, 20, 12, pop=pop if pop is not None else 3000, civilized=True, **fields)
    return settlement_kinds(world, config, poi)


def test_the_tie_break_stream_has_a_registered_label() -> None:
    assert "site.kinds" in LABELS


def test_fertile_grassland_is_chosen_for_farmhouses(config: Config) -> None:
    assert "farmhouse" in _kinds(_world(Biome.GRASS), config)


def test_forest_is_chosen_for_a_lodge(config: Config) -> None:
    assert "lodge" in _kinds(_world(Biome.FOREST), config, "city", 20000)


def test_a_mill_needs_the_river_tag(config: Config) -> None:
    world = _world(fresh=True)
    assert (
        "mill" in _kinds(world, config, "capital", 90000, tags=("river",)),
        "mill" in _kinds(world, config, "capital", 90000),
    ) == (True, False)


def test_a_fishery_needs_the_port_tag(config: Config) -> None:
    world = _world(sea=True)
    assert (
        "fishery" in _kinds(world, config, "capital", 90000, tags=("port",)),
        "fishery" in _kinds(world, config, "capital", 90000),
    ) == (True, False)


def test_a_kind_without_suited_land_is_not_chosen(config: Config) -> None:
    # No water, no forest: neither a mill, a fishery nor a lodge, tagged or not.
    kinds = _kinds(_world(Biome.GRASS), config, "capital", 90000, tags=("river", "port"))
    assert not {"mill", "fishery", "lodge"} & set(kinds)


def test_the_choice_follows_the_terrain(config: Config) -> None:
    assert _kinds(_world(Biome.GRASS), config, "city", 20000) != _kinds(_world(Biome.FOREST), config, "city", 20000)


@pytest.mark.parametrize("tier", TIERS)
def test_a_settlement_has_no_more_buildings_than_its_slots(config: Config, tier: str) -> None:
    high = config.get(f"tables.sites.{tier}.specialized")[1]
    assert len(_kinds(_world(Biome.FOREST, fresh=True, sea=True), config, tier, 90000, tags=("river", "port"))) <= high


def test_a_bigger_settlement_of_a_tier_has_at_least_as_many(config: Config) -> None:
    world = _world(Biome.FOREST, fresh=True, sea=True)
    small, big = (len(_kinds(world, config, "city", pop, tags=("river", "port"))) for pop in (9000, 40000))
    assert small <= big


def test_a_kind_is_capped_at_its_max_per_kind(config: Config) -> None:
    many = load_config(None)
    many.data["tables"]["sites"]["capital"]["specialized"] = [12, 12]
    kinds = _kinds(_world(Biome.GRASS), many, "capital", 90000)
    assert kinds.count("farmhouse") == config.get("tables.buildings.farmhouse.max_per_kind")


def test_a_hamlets_own_style_kind_is_first_and_alone(config: Config) -> None:
    # A mill hamlet has the mill whatever its land and tags say; a hamlet has one slot.
    assert _kinds(_world(Biome.GRASS), config, "hamlet", 40, style="mill") == ["mill"]


def test_a_homestead_is_no_settlement(config: Config) -> None:
    world = _world()
    poi = add_poi(world, "homestead", 20, 12, style="farm")
    assert settlement_kinds(world, config, poi) == []


def test_a_ruin_is_chosen_as_the_tier_it_was(config: Config) -> None:
    world = _world(Biome.FOREST)
    ruin = add_poi(world, "ruin", 20, 12, ruin_of="city", pop=20000)
    assert settlement_kinds(world, config, ruin) == _kinds(_world(Biome.FOREST), config, "city", 20000)


def test_the_choice_is_pure(config: Config) -> None:
    assert _kinds(_world(Biome.FOREST, fresh=True), config, "town", tags=("river",)) == _kinds(
        _world(Biome.FOREST, fresh=True), config, "town", tags=("river",)
    )


def test_the_choice_is_remembered_per_world(config: Config) -> None:
    world = _world(Biome.FOREST)
    poi = add_poi(world, "city", 20, 12, pop=20000, civilized=True)
    first = settlement_kinds(world, config, poi)
    world.biome[:] = int(Biome.GRASS)  # a changed world is the same world to the cache: the answer stays
    assert settlement_kinds(world, config, poi) == first


def test_hills_beyond_the_roughness_radius_do_not_suit_a_mine(config: Config) -> None:
    # Roughness has its own radius (hills are rare beside a settlement): a belt of hills 12 to 20 km off is read at the
    # default 150 km and missed when the radius is 10 km.
    from biomegen.world.tile import Relief

    near = load_config(None)
    near.data["sites"]["kinds"]["radius_km"]["roughness"] = 10.0
    world = _world(Biome.GRASS)
    world.relief[:, :8] = int(Relief.HILLS)
    assert "mine" in _kinds(world, config, "city", 20000) and "mine" not in _kinds(world, near, "city", 20000)


def test_the_hilly_share_is_the_roughness_term(config: Config) -> None:
    from biomegen.sites.surroundings import _terms
    from biomegen.world.tile import Relief

    world = _world(Biome.GRASS)
    poi = add_poi(world, "town", 20, 12, pop=3000, civilized=True)
    flat = _terms(world, config, poi)["roughness"]
    world.relief[:] = int(Relief.HILLS)
    assert (flat, _terms(world, config, poi)["roughness"]) == (0.0, 1.0)
