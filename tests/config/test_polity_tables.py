"""Tests for the political tables (data/polity.toml, data/reasons.toml) and the politics defaults."""

from __future__ import annotations

import pytest

from biomegen.config.defaults import get_defaults
from biomegen.config.validate import ConfigError, validate
from biomegen.world.entities import REALM_KINDS, RELATION_KINDS


def test_realm_kind_rows_match_the_kind_constants() -> None:
    # One realm_kinds row per kind the Realm entity allows.
    assert set(get_defaults()["tables"]["realm_kinds"]) == set(REALM_KINDS)


def test_reason_rows_match_the_relation_kinds() -> None:
    # Every relation kind has reason templates.
    assert set(get_defaults()["tables"]["reasons"]) == set(RELATION_KINDS)


def test_every_realm_kind_has_a_fallback_form() -> None:
    # A realm of any habitat can be named: each kind has an "any" or "open" form.
    forms = get_defaults()["tables"]["realm_forms"].values()
    for kind in REALM_KINDS:
        assert any(row["kind"] == kind and row["habitat"] in ("any", "open") for row in forms)


def test_shipped_politics_validate() -> None:
    # The packaged data and the politics section pass validation together.
    validate(get_defaults())


def test_realm_form_for_unknown_kind_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["realm_forms"]["kingdom"]["kind"] = "empire"
    with pytest.raises(ConfigError, match=r"tables\.realm_forms\.kingdom\.kind"):
        validate(cfg)


def test_realm_form_for_unknown_habitat_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["realm_forms"]["khanate"]["habitat"] = "swamp"
    with pytest.raises(ConfigError, match=r"tables\.realm_forms\.khanate\.habitat"):
        validate(cfg)


def test_kind_without_a_fallback_form_is_rejected() -> None:
    # Removing every "any" form of the majors leaves a dry realm with a form but a wet one with none.
    cfg = get_defaults()
    for row in cfg["tables"]["realm_forms"].values():
        if row["kind"] == "major":
            row["habitat"] = "dry"
    with pytest.raises(ConfigError, match="'major' needs a form"):
        validate(cfg)


def test_form_with_an_unknown_token_is_rejected() -> None:
    # {n} and {s} are the only tokens of a realm name.
    cfg = get_defaults()
    cfg["tables"]["realm_forms"]["kingdom"]["form"] = "Kingdom of {name}"
    with pytest.raises(ConfigError, match=r"unknown token \{name\}"):
        validate(cfg)


def test_reason_with_a_token_of_another_relation_is_rejected() -> None:
    # An alliance reason has no places to name.
    cfg = get_defaults()
    cfg["tables"]["reasons"]["alliance"]["templates"] = ["sealed at {town}"]
    with pytest.raises(ConfigError, match=r"tables\.reasons\.alliance\.templates: unknown token \{town\}"):
        validate(cfg)


def test_all_zero_relation_weights_are_rejected() -> None:
    # A neighbour pair needs some outcome to draw.
    cfg = get_defaults()
    for key in cfg["tables"]["relation_weights"]["major_pair"]:
        cfg["tables"]["relation_weights"]["major_pair"][key] = 0.0
    with pytest.raises(ConfigError, match="major_pair: needs at least one weight above 0"):
        validate(cfg)


def test_strength_span_must_be_ordered() -> None:
    cfg = get_defaults()
    cfg["tables"]["realm_kinds"]["major"]["strength"] = [1.4, 0.6]
    with pytest.raises(ConfigError, match=r"tables\.realm_kinds\.major\.strength: expected span"):
        validate(cfg)


def test_unknown_habitat_biome_is_rejected() -> None:
    # politics.habitats names biomes, checked like every other biome name in config.
    cfg = get_defaults()
    cfg["politics"]["habitats"]["dry"] = ["dunes"]
    with pytest.raises(ConfigError, match=r"politics\.habitats\.dry: unknown biome 'dunes'"):
        validate(cfg)
