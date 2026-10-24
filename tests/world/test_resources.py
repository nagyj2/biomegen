"""Tests for what a realm's land yields (``world/resources.py``)."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.world.entities import Realm
from biomegen.world.resources import goods_word, land_resources, realm_supply
from biomegen.world.tile import Biome, Relief
from biomegen.world.world import World

CONFIG = load_config(None)


def _world() -> World:
    # Two realms side by side: realm 0 holds grass and forest, realm 1 holds a hilly desert and a mountain.
    world = World(4, 2, 1)
    world.realms = [Realm(id=0, kind="major"), Realm(id=1, kind="major")]
    world.realm_id[:, :2] = 0
    world.realm_id[:, 2:] = 1
    world.biome[:, :] = int(Biome.GRASS)
    world.biome[1, 1] = int(Biome.FOREST)
    world.biome[:, 2:] = int(Biome.DESERT)
    world.relief[0, 2] = int(Relief.HILLS)
    world.relief[1, 3] = int(Relief.MOUNTAIN)
    return world


def test_land_resources_leave_out_the_currency() -> None:
    assert land_resources(CONFIG) == ["food", "luxury", "metal", "stone", "wood"]


def test_a_realm_supply_is_the_share_of_its_cells_per_resource() -> None:
    supply = realm_supply(_world(), CONFIG)[0]
    assert (supply["food"], supply["wood"]) == (0.75, 0.25)


def test_relief_yields_before_the_biome() -> None:
    # In realm 1 the hill cell yields stone and the mountain metal; only two desert cells yield luxury.
    supply = realm_supply(_world(), CONFIG)[1]
    assert (supply["stone"], supply["metal"], supply["luxury"]) == (0.25, 0.25, 0.5)


def test_a_realm_with_no_land_supplies_nothing() -> None:
    world = _world()
    world.realm_id[:] = 0
    world.realms.append(Realm(id=2, kind="tribal"))
    assert sum(realm_supply(world, CONFIG)[2].values()) == 0.0


def test_goods_word_is_the_name_of_the_main_yielding_row() -> None:
    assert goods_word(_world(), CONFIG, 0, "food") == "grain"


def test_goods_word_of_a_resource_the_land_lacks_is_empty() -> None:
    assert goods_word(_world(), CONFIG, 0, "metal") == ""


def test_goods_word_names_a_relief_row() -> None:
    assert goods_word(_world(), CONFIG, 1, "metal") == "iron"
