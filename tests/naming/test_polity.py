"""Tests for realm naming (forms, habitats, rulers) and the wording of relation reasons."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.naming import cultures, polity
from biomegen.world.entities import POI, GeoFeature, Realm, Relation
from biomegen.world.tile import Biome
from biomegen.world.world import World


def _realm(kind: str = "major", biome: Biome = Biome.GRASS, **fields: object) -> Realm:
    base = {"id": 0, "kind": kind, "dominant_biome": int(biome), "culture": "common"}
    return Realm(**{**base, **fields})  # type: ignore[arg-type]


def _only(config: Config, *names: str) -> Config:
    """Keep only the realm forms called ``names``."""
    rows = config.data["tables"]["realm_forms"]
    config.data["tables"]["realm_forms"] = {name: rows[name] for name in names}
    return config


@pytest.fixture
def config() -> Config:
    return load_config(None)


# --- habitats and the forms open to a realm ---------------------------------------------------------------------------


def test_a_desert_realm_is_dry(config: Config) -> None:
    assert polity.habitats(_realm(biome=Biome.DESERT), config) == {"dry"}


def test_taiga_is_cold_and_wooded(config: Config) -> None:
    assert polity.habitats(_realm(biome=Biome.TAIGA), config) == {"cold", "wood"}


def test_a_highland_realm_has_only_the_high_habitat(config: Config) -> None:
    assert polity.habitats(_realm(biome=Biome.DESERT, highland=True), config) == {"high"}


def test_grassland_has_no_habitat(config: Config) -> None:
    assert polity.habitats(_realm(biome=Biome.GRASS), config) == set()


def _form_names(realm: Realm, config: Config) -> set[str]:
    return {name for name, _ in polity._candidate_forms(realm, config)}


def test_a_dry_major_may_be_a_khanate(config: Config) -> None:
    assert "khanate" in _form_names(_realm(biome=Biome.DESERT), config)


def test_a_grassland_major_is_never_a_khanate(config: Config) -> None:
    assert "khanate" not in _form_names(_realm(biome=Biome.GRASS), config)


def test_a_tribe_of_open_land_takes_the_open_forms(config: Config) -> None:
    assert _form_names(_realm("tribal", Biome.GRASS), config) == {"horde", "clans", "tribes"}


def test_a_tribe_in_a_desert_falls_back_to_the_open_forms(config: Config) -> None:
    # No tribal form favours a dry habitat, so the open ones are used.
    assert _form_names(_realm("tribal", Biome.DESERT), config) == {"horde", "clans", "tribes"}


def test_a_highland_tribe_takes_the_hold_forms(config: Config) -> None:
    assert _form_names(_realm("tribal", Biome.GRASS, highland=True), config) == {"holds", "free_holds"}


# --- names ------------------------------------------------------------------------------------------------------------


def test_a_major_is_named_from_its_form_and_base_word(config: Config) -> None:
    realm = _realm()
    polity.name_realm(5, realm, "", _only(config, "kingdom"))
    assert realm.name == f"Kingdom of {realm.short}"


def test_a_ruler_style_takes_the_personal_name(config: Config) -> None:
    realm = _realm()
    polity.name_realm(5, realm, "", _only(config, "kingdom"))
    assert realm.ruler.split()[0] in ("King", "Queen") and len(realm.ruler.split()) == 2


def test_a_city_state_is_named_after_its_seat(config: Config) -> None:
    realm = _realm("city_state")
    polity.name_realm(5, realm, "Vexford", _only(config, "free_city"))
    assert (realm.name, realm.short) == ("Free City of Vexford", "Vexford")


def test_a_tribe_without_a_seat_uses_its_base_word(config: Config) -> None:
    realm = _realm("tribal")
    polity.name_realm(5, realm, "", _only(config, "horde"))
    assert realm.name == f"The {realm.short} Horde"


def test_a_realm_name_is_keyed_on_its_id(config: Config) -> None:
    first, second = _realm(id=3), _realm(id=3)
    for realm in (first, second):
        polity.name_realm(9, realm, "", config)
    assert (first.name, first.ruler) == (second.name, second.ruler)


def test_realms_of_different_ids_get_different_names(config: Config) -> None:
    names = set()
    for index in range(12):
        realm = _realm(id=index)
        polity.name_realm(9, realm, "", config)
        names.add(realm.short)
    assert len(names) > 6


def test_culture_follows_the_dominant_biome() -> None:
    # Only the southern people live in deserts.
    assert cultures.culture_for_realm(1, _realm(biome=Biome.DESERT)) == "southern"


def test_culture_is_seeded_on_the_realm_id() -> None:
    picks = {cultures.culture_for_realm(1, _realm(id=index, biome=Biome.FOREST)) for index in range(30)}
    assert len(picks) > 1


# --- relation reasons -------------------------------------------------------------------------------------------------


def _pair(config: Config, kind: str, template: str, **claim: int) -> World:
    world = World(10, 4, 1)
    world.realms = [
        _realm(id=0, biome=Biome.GRASS, short="Alda"),
        _realm(id=1, biome=Biome.FOREST, short="Brevia"),
    ]
    world.relations = [Relation(a=0, b=1, kind=kind, why=template, **claim)]
    return world


def test_trade_names_the_goods_and_the_realms(config: Config) -> None:
    world = _pair(config, "trade", "{goods_a} from {short_a} for {goods_b} from {short_b}")
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "grain from Alda for timber from Brevia"


def test_realms_of_the_same_good_trade_a_different_one(config: Config) -> None:
    world = _pair(config, "trade", "{goods_a} {goods_b}")
    world.realms[1] = _realm(id=1, biome=Biome.GRASS, short="Brevia")
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "grain wine"


def test_a_realm_with_no_good_uses_the_fallback(config: Config) -> None:
    world = _pair(config, "trade", "{goods_a} {goods_b}")
    world.realms[0] = _realm(id=0, biome=Biome.BEACH, short="Alda")
    config.data["tables"]["biomes"]["beach"]["goods"] = ""
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why.startswith("wool ")


def test_a_highland_realm_trades_iron(config: Config) -> None:
    world = _pair(config, "trade", "{goods_a}")
    world.realms[0] = _realm(id=0, highland=True, short="Alda")
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "iron"


def test_a_war_names_its_claimed_town(config: Config) -> None:
    world = _pair(config, "war", "the border town of {town}", claim_poi=0)
    world.pois.append(POI(kind="town", x=1, y=1, interior_seed=1, civilized=True, name="Dunmere"))
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "the border town of Dunmere"


def test_a_town_of_neither_power_is_not_named_when_one_of_theirs_exists(config: Config) -> None:
    world = _pair(config, "rivalry", "a cold war over {town}")
    world.pois.append(POI(kind="town", x=1, y=1, interior_seed=1, civilized=True, name="Faraway", realm_id=5))
    world.pois.append(POI(kind="village", x=2, y=1, interior_seed=2, civilized=True, name="Homestead", realm_id=1))
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "a cold war over Homestead"


def test_a_world_without_towns_uses_the_fallback_words(config: Config) -> None:
    world = _pair(config, "rivalry", "a cold war over {town}")
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "a cold war over Nowhere"


def _features() -> list[GeoFeature]:
    return [
        GeoFeature(id=0, kind="river", anchor=(0, 0), name="Short"),
        GeoFeature(id=1, kind="river", anchor=(0, 0), name="Long"),
        GeoFeature(id=2, kind="range", anchor=(0, 0), name="The Grey Peaks"),
        GeoFeature(id=3, kind="sea", anchor=(0, 0), name="The Deep"),
    ]


def test_places_are_the_features_diplomacy_chose_without_their_article(config: Config) -> None:
    world = _pair(config, "war", "{river} {range} {sea}")
    world.features = _features()
    world.relations[0].places = {"river": 0, "range": 2, "sea": 3}
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "Short Grey Peaks Deep"


def test_a_place_diplomacy_did_not_choose_uses_the_fallback_words(config: Config) -> None:
    world = _pair(config, "war", "{river} {range} {sea}")
    world.features = _features()
    polity.describe_relations(world, config, 1)
    assert world.relations[0].why == "river crossings border hills open sea"
