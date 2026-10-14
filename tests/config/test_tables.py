"""Tests for the attribute tables (data/*.toml loaded under ``tables``) and their schema validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.defaults.tables import DATA_DIR, DATA_FILES, _load
from biomegen.config.validate import ConfigError, validate
from biomegen.world.tile import RELIEF_BY_NAME


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
    }


def test_shipped_tables_load_and_validate() -> None:
    # The packaged data files give their tables and pass their own schema.
    assert sorted(load_config(None).get("tables")) == ["biomes", "relief", "styles", "tiers"]


def test_relief_table_covers_every_relief_member() -> None:
    # One relief row per enum member, keyed by lower-case name.
    assert set(get_defaults()["tables"]["relief"]) == set(RELIEF_BY_NAME)


def test_tier_ranks_order_capital_to_village() -> None:
    # Placement order is data: rank 0 is the capital, then city, town, village.
    tiers = get_defaults()["tables"]["tiers"]
    assert sorted(tiers, key=lambda name: tiers[name]["rank"]) == ["capital", "city", "town", "village"]


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
    # biomes.toml supplies biomes and relief; tiers.toml tiers; terrain.toml styles.
    assert sorted(_load(DATA_DIR, DATA_FILES)) == ["biomes", "relief", "styles", "tiers"]


def test_loader_rejects_a_table_defined_twice(tmp_path: Path) -> None:
    # Two data files defining the same table would make one silently win.
    (tmp_path / "a.toml").write_text("[tiers.x]\nrank = 0\n", encoding="utf-8")
    (tmp_path / "b.toml").write_text("[tiers.y]\nrank = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="defined twice"):
        _load(tmp_path, ("a.toml", "b.toml"))
