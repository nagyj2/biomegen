"""Tests for the attribute tables (data/*.toml loaded under ``tables``) and their schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.defaults.tables import DATA_DIR, DATA_FILES, _load
from biomegen.config.validate import ConfigError, validate
from biomegen.world.tile import BIOME_BY_NAME, RELIEF_BY_NAME


def _new_biome_row() -> dict:
    return {
        "label": "Steppe",
        "glyph": ";",
        "ascii": ";",
        "fg": [1, 2, 3],
        "bg": [4, 5, 6],
        "water": False,
        "sparse": True,
        "habitability": 0.5,
        "move_cost": 1.0,
        "goods": "horses",
        "priority": 30,
    }


def test_shipped_tables_load_and_validate() -> None:
    # The packaged data files give their tables and pass their own schema.
    assert sorted(load_config(None).get("tables")) == [
        "biomes",
        "chronicle",
        "detail",
        "detail_relief",
        "free_fates",
        "furniture",
        "geo_names",
        "poi_fates",
        "poi_sites",
        "poi_styles",
        "pois",
        "realm_colors",
        "realm_forms",
        "realm_kinds",
        "reason_tokens",
        "reasons",
        "relation_weights",
        "relief",
        "ruling_styles",
        "secession_forms",
        "secession_relations",
        "secession_terms",
        "sites",
        "styles",
        "tiers",
    ]


def test_relief_table_covers_every_relief_member() -> None:
    # One relief row per enum member, keyed by lower-case name.
    assert set(get_defaults()["tables"]["relief"]) == set(RELIEF_BY_NAME)


def test_tier_ranks_order_capital_to_hamlet() -> None:
    # Placement order is data: rank 0 is the capital, then city, town, village and the simulation-minted hamlet.
    tiers = get_defaults()["tables"]["tiers"]
    assert sorted(tiers, key=lambda name: tiers[name]["rank"]) == ["capital", "city", "town", "village", "hamlet"]


def test_user_override_changes_one_attribute_and_keeps_the_row(tmp_path: Path) -> None:
    # A sparse [tables.biomes.desert] override deep-merges into the packaged row.
    path = tmp_path / "config.toml"
    path.write_text('[tables.biomes.desert]\ngoods = "glass"\n', encoding="utf-8")
    desert = load_config(str(path)).get("tables.biomes.desert")
    assert (desert["goods"], desert["label"]) == ("glass", "Desert")


def test_biome_row_without_an_enum_member_is_rejected() -> None:
    # Biome rows are tied to the Biome enum: a complete row for a name with no member is an error.
    cfg = get_defaults()
    cfg["tables"]["biomes"]["steppe"] = _new_biome_row()
    with pytest.raises(ConfigError, match="one row per Biome member"):
        validate(cfg)


def test_new_row_missing_a_key_is_rejected() -> None:
    # A new row must carry every required key, since there is nothing to merge it over.
    cfg = get_defaults()
    row = _new_biome_row()
    del row["goods"]
    cfg["tables"]["biomes"]["steppe"] = row
    with pytest.raises(ConfigError, match=r"tables\.biomes\.steppe: missing key 'goods'"):
        validate(cfg)


def test_unknown_row_key_is_rejected() -> None:
    # A typo in an override is reported instead of silently ignored.
    cfg = get_defaults()
    cfg["tables"]["biomes"]["desert"]["habitabilty"] = 0.2
    with pytest.raises(ConfigError, match=r"tables\.biomes\.desert: unknown key 'habitabilty'"):
        validate(cfg)


def test_unknown_table_is_rejected() -> None:
    # Only tables with a schema may appear under [tables].
    cfg = get_defaults()
    cfg["tables"]["weather"] = {}
    with pytest.raises(ConfigError, match=r"tables\.weather: unknown table"):
        validate(cfg)


@pytest.mark.parametrize(
    ("table", "row", "key", "value"),
    [
        ("biomes", "grass", "glyph", "ab"),
        ("biomes", "grass", "habitability", 1.5),
        ("biomes", "grass", "move_cost", 0.5),
        ("biomes", "grass", "water", "no"),
        ("relief", "hills", "move_cost", -1.0),
        ("tiers", "town", "pop", [800, 100]),
        ("tiers", "town", "spacing_km", 0.0),
        ("tiers", "town", "rank", 1.5),
    ],
)
def test_value_of_the_wrong_kind_is_rejected(table: str, row: str, key: str, value: object) -> None:
    # Each value is checked against its column's kind (character, range, bound, type).
    cfg = get_defaults()
    cfg["tables"][table][row][key] = value
    with pytest.raises(ConfigError, match=rf"tables\.{table}\.{row}\.{key}: expected"):
        validate(cfg)


def test_hex_colour_is_coerced_to_rgb() -> None:
    # Table colours accept "#rrggbb", like render.palette.
    cfg = get_defaults()
    cfg["tables"]["biomes"]["grass"]["fg"] = "#102030"
    validate(cfg)
    assert cfg["tables"]["biomes"]["grass"]["fg"] == [16, 32, 48]


def test_tier_background_is_optional() -> None:
    # Towns and villages have no marker background; omitting bg is valid.
    cfg = get_defaults()
    cfg["tables"]["tiers"]["city"].pop("bg")
    validate(cfg)


def test_relief_row_for_unknown_member_is_rejected() -> None:
    # Relief rows are tied to the Relief enum: an extra name has no member to describe.
    cfg = get_defaults()
    cfg["tables"]["relief"]["mesa"] = dict(cfg["tables"]["relief"]["hills"])
    with pytest.raises(ConfigError, match="one row per Relief member"):
        validate(cfg)


def test_duplicate_tier_rank_is_rejected() -> None:
    # Placement order must be total, so two tiers cannot share a rank.
    cfg = get_defaults()
    cfg["tables"]["tiers"]["town"]["rank"] = 0
    with pytest.raises(ConfigError, match="unique rank"):
        validate(cfg)


def test_loader_combines_the_shipped_files() -> None:
    # biomes.toml supplies biomes and relief; detail.toml detail and detail_relief; tiers.toml tiers;
    # terrain.toml styles; geography.toml geo_names; sites.toml sites; pois.toml pois; furniture.toml furniture;
    # polity.toml the four realm and relation tables; reasons.toml reasons and reason_tokens; rulers.toml ruling_styles;
    # chronicle.toml chronicle.
    assert sorted(_load(DATA_DIR, DATA_FILES)) == [
        "biomes",
        "chronicle",
        "detail",
        "detail_relief",
        "free_fates",
        "furniture",
        "geo_names",
        "poi_fates",
        "poi_sites",
        "poi_styles",
        "pois",
        "realm_colors",
        "realm_forms",
        "realm_kinds",
        "reason_tokens",
        "reasons",
        "relation_weights",
        "relief",
        "ruling_styles",
        "secession_forms",
        "secession_relations",
        "secession_terms",
        "sites",
        "styles",
        "tiers",
    ]


def test_detail_table_covers_every_biome_member() -> None:
    # One detail row per Biome member, keyed by lower-case name.
    assert set(get_defaults()["tables"]["detail"]) == set(BIOME_BY_NAME)


def test_detail_relief_table_covers_every_relief_member() -> None:
    # One detail_relief row per Relief member, keyed by lower-case name.
    assert set(get_defaults()["tables"]["detail_relief"]) == set(RELIEF_BY_NAME)


def test_detail_row_for_unknown_biome_is_rejected() -> None:
    # Detail rows are tied to the Biome enum: an extra name has no member to describe.
    cfg = get_defaults()
    cfg["tables"]["detail"]["steppe"] = dict(cfg["tables"]["detail"]["grass"])
    with pytest.raises(ConfigError, match="tables.detail must have exactly one row per Biome member"):
        validate(cfg)


@pytest.mark.parametrize(
    ("table", "row", "key", "value"),
    [
        ("detail", "forest", "factor", "wetness"),
        ("detail", "forest", "density", 1.5),
        ("detail", "forest", "floor_ascii", "·"),
        ("detail", "forest", "clutter_ascii", "♣"),
        ("detail_relief", "mountain", "floor_ascii", "▲"),
        ("detail_relief", "mountain", "floor", "^^"),
    ],
)
def test_detail_value_of_the_wrong_kind_is_rejected(table: str, row: str, key: str, value: object) -> None:
    # Detail columns are checked for kind: ASCII columns stay 7-bit, factor is one of the known names.
    cfg = get_defaults()
    cfg["tables"][table][row][key] = value
    with pytest.raises(ConfigError, match=rf"tables\.{table}\.{row}\.{key}: expected"):
        validate(cfg)


def test_loader_rejects_a_table_defined_twice(tmp_path: Path) -> None:
    # Two data files defining the same table would make one silently win.
    (tmp_path / "a.toml").write_text("[tiers.x]\nrank = 0\n", encoding="utf-8")
    (tmp_path / "b.toml").write_text("[tiers.y]\nrank = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="defined twice"):
        _load(tmp_path, ("a.toml", "b.toml"))


def test_every_site_row_has_a_layout_and_a_positive_extent() -> None:
    # sites.toml names a layout and a w x h extent for every kind, so no site can be zero-sized.
    sites = get_defaults()["tables"]["sites"]
    assert sites and all(row["layout"] and min(row["extent_tiles"]) > 0 for row in sites.values())


def test_site_extent_must_be_two_positive_numbers() -> None:
    cfg = get_defaults()
    cfg["tables"]["sites"]["village"]["extent_tiles"] = [1.0, 0.0]
    with pytest.raises(ConfigError):
        validate(cfg)


def test_site_rows_per_tile_must_be_a_positive_integer() -> None:
    cfg = get_defaults()
    cfg["tables"]["sites"]["village"]["rows_per_tile"] = 0
    with pytest.raises(ConfigError):
        validate(cfg)


def test_every_settlement_tier_has_a_site_row() -> None:
    # Each tier in tiers.toml needs a site, or its POIs could never be zoomed into.
    tables = get_defaults()["tables"]
    assert set(tables["tiers"]) <= set(tables["sites"])


def test_every_furniture_set_names_real_cells_and_positive_weights() -> None:
    # furniture.toml validates: each key is a Cell name, each weight a non-negative number.
    validate(get_defaults())


def test_an_unknown_furniture_cell_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["furniture"]["home"]["sofa"] = 3.0
    with pytest.raises(ConfigError):
        validate(cfg)


def test_a_negative_furniture_weight_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["furniture"]["home"]["bed"] = -1.0
    with pytest.raises(ConfigError):
        validate(cfg)


def test_a_site_row_must_name_an_existing_furniture_set() -> None:
    cfg = get_defaults()
    cfg["tables"]["sites"]["village"]["furniture"] = "palace"
    with pytest.raises(ConfigError):
        validate(cfg)


def test_every_poi_kind_has_a_site_row_and_a_marker() -> None:
    # Each kind in pois.toml needs a site row and a map marker, or it could not be zoomed into or drawn.
    cfg = get_defaults()
    assert set(cfg["tables"]["pois"]) <= set(cfg["tables"]["sites"])
    assert set(cfg["tables"]["pois"]) <= set(cfg["render"]["markers"])


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source", "both_ways"),
        ("owner", "faction"),
        ("floors", [0, 3]),
        ("connect", "yes"),
        ("bandit_strength", 0),
        ("min_spacing_km", -5.0),
    ],
)
def test_a_poi_row_value_of_the_wrong_kind_is_rejected(key: str, value: object) -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["tower"][key] = value
    with pytest.raises(ConfigError, match=rf"tables\.pois\.tower\.{key}: expected"):
        validate(cfg)


def test_a_poi_row_without_a_seam_field_is_rejected() -> None:
    # owner, dynamic and connect are required on every kind so a later simulation never has to guess.
    cfg = get_defaults()
    del cfg["tables"]["pois"]["tower"]["connect"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.tower: missing key 'connect'"):
        validate(cfg)


def test_a_poi_biome_name_must_exist() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["tower"]["biomes"] = ["moonscape"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.tower\.biomes: unknown biome"):
        validate(cfg)


def test_a_poi_purpose_has_a_site_row() -> None:
    # A row's purpose names a `<kind>_<purpose>` site row, or its POIs would silently use the plain kind's look.
    tables = get_defaults()["tables"]
    assert all(
        f"{kind}_{row['purpose']}" in tables["sites"] for kind, row in tables["pois"].items() if "purpose" in row
    )


def test_every_ruling_style_has_a_temper() -> None:
    # The shrine rule reads the temper of the style a succession leaves, so no style may lack one.
    styles = get_defaults()["tables"]["ruling_styles"]
    assert styles and all(row["temper"] in ("aggressive", "passive") for row in styles.values())


def test_an_unknown_ruling_temper_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["ruling_styles"]["gentle"]["temper"] = "meek"
    with pytest.raises(ConfigError, match=r"tables\.ruling_styles\.gentle\.temper: expected"):
        validate(cfg)


def test_a_poi_row_naming_an_unknown_event_kind_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["ruin"]["events"] = ["earthquake"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.ruin\.events: unknown event kind"):
        validate(cfg)


def test_a_poi_tag_naming_an_unknown_style_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["shrine"]["tags"] = ["to:heroic"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.shrine\.tags: 'to:heroic' names no ruling style"):
        validate(cfg)


def test_a_kind_with_sites_needs_one_for_each_temper() -> None:
    cfg = get_defaults()
    del cfg["tables"]["poi_sites"]["shrine_wild"]
    with pytest.raises(ConfigError, match=r"kind 'shrine' needs a site for each temper"):
        validate(cfg)


def test_a_site_band_must_run_from_near_to_far() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_sites"]["shrine_near_seat"]["min_km"] = 500.0
    with pytest.raises(ConfigError, match=r"min_km must be below max_km"):
        validate(cfg)


def test_a_history_kind_without_events_is_rejected() -> None:
    cfg = get_defaults()
    del cfg["tables"]["pois"]["battlefield"]["events"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.battlefield: a history kind needs events"):
        validate(cfg)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("names", ["{n} {castle}"], r"tables\.pois\.tower\.names: unknown token \{castle\}"),
        ("names_fallen", ["Ruins of {n}"], r"tables\.pois\.ruin\.names_fallen: 'Ruins of \{n\}' must use \{fallen\}"),
        ("hooks", ["{name} watches {near}."], r"tables\.pois\.ruin\.hooks: unknown token \{near\}"),
        ("hooks_near", ["{name} stands."], r"tables\.pois\.ruin\.hooks_near: .* must use \{near\}"),
    ],
)
def test_a_poi_text_may_use_only_its_tokens(key: str, value: list, message: str) -> None:
    cfg = get_defaults()
    kind = "tower" if key == "names" else "ruin"
    cfg["tables"]["pois"][kind][key] = value
    with pytest.raises(ConfigError, match=message):
        validate(cfg)


def test_a_poi_name_pattern_needs_its_root() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["tower"]["names"] = ["The Tower"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.tower\.names: expected forms"):
        validate(cfg)


def test_a_kind_placed_by_location_needs_hooks() -> None:
    cfg = get_defaults()
    del cfg["tables"]["pois"]["camp"]["hooks"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.camp: a kind placed by location needs hooks"):
        validate(cfg)


def test_a_ruin_origin_must_be_a_settlement_tier() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["ruin"]["holding_origins"] = {"fortress": 1.0}
    with pytest.raises(ConfigError, match=r"tables\.pois\.ruin: origin 'fortress' is no settlement tier"):
        validate(cfg)


def test_ruin_origin_weights_need_one_above_zero() -> None:
    cfg = get_defaults()
    cfg["tables"]["pois"]["ruin"]["origins"] = {"village": 0.0}
    with pytest.raises(ConfigError, match=r"tables\.pois\.ruin\.origins: expected weights"):
        validate(cfg)


def test_the_ruin_row_needs_its_origins() -> None:
    cfg = get_defaults()
    del cfg["tables"]["pois"]["ruin"]["fall_origin"]
    with pytest.raises(ConfigError, match=r"tables\.pois\.ruin: needs fall_origin"):
        validate(cfg)


def test_a_tier_a_ruin_may_have_been_needs_its_ruin_numbers() -> None:
    cfg = get_defaults()
    del cfg["tables"]["sites"]["town"]["ruin_standing"]
    with pytest.raises(ConfigError, match=r"tables\.sites\.town: needs ruin_standing"):
        validate(cfg)


@pytest.mark.parametrize("key", ["ruin_standing", "ruin_wall_fall"])
def test_a_ruin_share_pair_must_be_two_shares(key: str) -> None:
    cfg = get_defaults()
    cfg["tables"]["sites"]["town"][key] = [0.5, 1.5]
    with pytest.raises(ConfigError, match=rf"tables\.sites\.town\.{key}: expected unit_pair"):
        validate(cfg)


def test_a_free_marker_colour_must_be_a_colour() -> None:
    cfg = get_defaults()
    cfg["tables"]["tiers"]["town"]["free_fg"] = "teal-ish"
    with pytest.raises(ConfigError, match=r"tables\.tiers\.town\.free_fg"):
        validate(cfg)


def test_a_free_text_may_use_only_the_settlements_name() -> None:
    cfg = get_defaults()
    cfg["tables"]["tiers"]["town"]["hooks_free"] = ["{name} and {fallen}."]
    with pytest.raises(ConfigError, match=r"tables\.tiers\.town\.hooks_free"):
        validate(cfg)


def test_a_remnant_text_must_name_the_fallen_realm() -> None:
    cfg = get_defaults()
    cfg["tables"]["tiers"]["town"]["hooks_remnant"] = ["{name} stands."]
    with pytest.raises(ConfigError, match=r"tables\.tiers\.town\.hooks_remnant: .* must use \{fallen\}"):
        validate(cfg)


def test_every_free_fate_is_simulation_only() -> None:
    assert all(row["sim_only"] for row in get_defaults()["tables"]["free_fates"].values())


def test_the_free_fates_are_join_found_and_bandit() -> None:
    assert sorted(get_defaults()["tables"]["free_fates"]) == ["bandit", "found", "join"]


def test_a_free_fate_without_factors_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["free_fates"]["join"]["factors"] = []
    with pytest.raises(ConfigError, match=r"tables\.free_fates\.join\.factors: expected text_list"):
        validate(cfg)


def test_every_ruling_style_has_all_five_traits() -> None:
    from biomegen.world.entities import TRAITS

    assert all(set(row["traits"]) == set(TRAITS) for row in get_defaults()["tables"]["ruling_styles"].values())


def test_a_style_missing_a_trait_is_rejected() -> None:
    cfg = get_defaults()
    del cfg["tables"]["ruling_styles"]["martial"]["traits"]["greed"]
    with pytest.raises(ConfigError, match=r"tables\.ruling_styles\.martial\.traits: expected traits"):
        validate(cfg)


def test_a_trait_outside_zero_to_one_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["ruling_styles"]["martial"]["traits"]["greed"] = 1.5
    with pytest.raises(ConfigError, match=r"tables\.ruling_styles\.martial\.traits: expected traits"):
        validate(cfg)


def test_the_secession_tables_have_exactly_their_rows() -> None:
    from biomegen.world.entities import RELATION_KINDS

    tables = get_defaults()["tables"]
    assert sorted(tables["secession_terms"]) == [
        "age",
        "leader",
        "prosperity",
        "proximity",
        "relation",
        "size",
        "strength",
    ]
    assert sorted(tables["secession_forms"]) == ["defection", "offshoot", "split"]
    assert sorted(tables["secession_relations"]) == sorted((*RELATION_KINDS, "none"))


def test_a_secession_term_row_cannot_be_left_out() -> None:
    cfg = get_defaults()
    del cfg["tables"]["secession_terms"]["leader"]
    with pytest.raises(ConfigError, match=r"tables\.secession_terms must have exactly the rows"):
        validate(cfg)


def test_a_secession_relation_tag_must_be_known() -> None:
    cfg = get_defaults()
    cfg["tables"]["secession_relations"]["war"]["tag"] = "furious"
    with pytest.raises(ConfigError, match=r"tables\.secession_relations\.war\.tag: expected secession_tag"):
        validate(cfg)


def test_a_secession_relation_score_is_a_share() -> None:
    cfg = get_defaults()
    cfg["tables"]["secession_relations"]["war"]["score"] = 1.5
    with pytest.raises(ConfigError, match=r"tables\.secession_relations\.war\.score: expected unit"):
        validate(cfg)


def test_the_secession_forms_need_a_weight_above_zero() -> None:
    cfg = get_defaults()
    for row in cfg["tables"]["secession_forms"].values():
        row["weight"] = 0.0
    with pytest.raises(ConfigError, match=r"tables\.secession_forms: needs at least one weight above 0"):
        validate(cfg)


def test_every_wording_of_a_secession_exists_for_both_tags() -> None:
    rows = get_defaults()["tables"]["chronicle"]
    names = {f"secession_{form}_{tag}" for form in ("offshoot", "split", "defection") for tag in ("bitter", "amicable")}
    assert names <= set(rows)


def test_the_shipped_styles_are_the_five_homestead_styles() -> None:
    assert sorted(get_defaults()["tables"]["poi_styles"]) == ["farm", "fishery", "lodge", "mill", "mine"]


def test_only_the_growing_styles_make_hamlets() -> None:
    # A hamlet is generated only for a style a homestead could grow by (farm, mill, lodge); mine and fishery never grow.
    styles = get_defaults()["tables"]["poi_styles"]
    hamlet_styles = sorted(name for name, row in styles.items() if "hamlet_km2_per_poi" in row)
    grows = sorted(name for name, row in styles.items() if "grows_into" in row)
    assert hamlet_styles == grows == ["farm", "lodge", "mill"]


def test_a_growing_style_grows_into_a_settlement_tier() -> None:
    tables = get_defaults()["tables"]
    assert all(row["grows_into"] in tables["tiers"] for row in tables["poi_styles"].values() if "grows_into" in row)


def test_the_hamlet_is_never_another_places_nearby_settlement() -> None:
    # near_target is false on the hamlet tier only; the other tiers keep the default (true).
    tiers = get_defaults()["tables"]["tiers"]
    assert {name: row.get("near_target", True) for name, row in tiers.items()} == {
        "capital": True,
        "city": True,
        "town": True,
        "village": True,
        "hamlet": False,
    }


def test_a_generated_style_needs_a_count() -> None:
    cfg = get_defaults()
    del cfg["tables"]["poi_styles"]["mine"]["homestead_km2_per_poi"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.mine: a generated style needs"):
        validate(cfg)


def test_a_style_with_a_hamlet_count_must_grow() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["fishery"]["hamlet_km2_per_poi"] = 500000.0
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.fishery: a style that makes hamlets needs grows_into"):
        validate(cfg)


def test_a_style_cannot_grow_into_an_unknown_tier() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["farm"]["grows_into"] = "metropolis"
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm\.grows_into: 'metropolis' is no settlement tier"):
        validate(cfg)


def test_a_style_needs_its_homestead_hooks() -> None:
    cfg = get_defaults()
    del cfg["tables"]["poi_styles"]["mine"]["hooks_homestead"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.mine: needs hooks_homestead"):
        validate(cfg)


def test_a_growing_style_needs_its_hamlet_hooks() -> None:
    cfg = get_defaults()
    del cfg["tables"]["poi_styles"]["lodge"]["hooks_hamlet"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.lodge: a style that grows needs hooks_hamlet"):
        validate(cfg)


def test_a_weighted_distance_term_needs_its_scale() -> None:
    cfg = get_defaults()
    del cfg["tables"]["poi_styles"]["farm"]["near_settlement_km"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm: near_settlement needs near_settlement_km"):
        validate(cfg)


def test_a_style_near_text_must_name_the_settlement() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["mill"]["hooks_homestead_near"] = ["{name} grinds."]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.mill\.hooks_homestead_near: .* must use \{near\}"):
        validate(cfg)


def test_a_style_hook_may_use_only_its_tokens() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["mill"]["hooks_homestead"] = ["{name} grinds for {near}."]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.mill\.hooks_homestead: unknown token \{near\}"):
        validate(cfg)


def test_a_style_name_pattern_needs_its_root() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["farm"]["names"] = ["The Farm"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm\.names: expected forms"):
        validate(cfg)


def test_a_style_biome_name_must_exist() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["farm"]["biomes"] = ["moonscape"]
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm\.biomes: unknown biome"):
        validate(cfg)


def test_a_style_row_value_of_the_wrong_kind_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["farm"]["fertility"] = -1.0
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm\.fertility: expected nonneg"):
        validate(cfg)


def test_a_style_row_with_an_unknown_key_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["poi_styles"]["farm"]["soil"] = 1.0
    with pytest.raises(ConfigError, match=r"tables\.poi_styles\.farm: unknown key 'soil'"):
        validate(cfg)


def test_a_poi_row_may_be_placed_by_style_and_hide_its_marker() -> None:
    # `source = "style"` and `marker = false` are valid row values (the homestead kind row uses both).
    cfg = get_defaults()
    cfg["tables"]["pois"]["boat"]["source"] = "style"
    cfg["tables"]["pois"]["boat"]["marker"] = False
    validate(cfg)
