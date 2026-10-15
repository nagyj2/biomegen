"""Tests for the chronicle wording table (data/chronicle.toml) and the history defaults."""

from __future__ import annotations

import pytest

from biomegen.config.defaults import get_defaults
from biomegen.config.validate import ConfigError, validate
from biomegen.world.entities import EVENT_KINDS


def test_shipped_history_validates() -> None:
    # The packaged chronicle rows and the history section pass validation together.
    validate(get_defaults())


def test_every_event_kind_is_enabled_by_default() -> None:
    assert set(get_defaults()["history"]["kinds"]) == set(EVENT_KINDS)


def test_every_event_kind_has_wording() -> None:
    # A kind is worded by the row of its name, or by the treaty rows for the treaty kind.
    rows = get_defaults()["tables"]["chronicle"]
    needed = {"treaty_alliance", "treaty_trade"} | (set(EVENT_KINDS) - {"treaty"})
    assert set(rows) == needed


def test_unknown_start_is_rejected() -> None:
    cfg = get_defaults()
    cfg["history"]["start"] = "noon"
    with pytest.raises(ConfigError, match=r"history\.start"):
        validate(cfg)


def test_unknown_event_kind_is_rejected() -> None:
    cfg = get_defaults()
    cfg["history"]["kinds"] = ["founding", "plague"]
    with pytest.raises(ConfigError, match=r"history\.kinds"):
        validate(cfg)


def test_age_range_must_name_every_realm_kind() -> None:
    cfg = get_defaults()
    del cfg["history"]["age_range"]["tribal"]
    with pytest.raises(ConfigError, match=r"history\.age_range"):
        validate(cfg)


def test_age_range_outside_the_span_is_rejected() -> None:
    cfg = get_defaults()
    cfg["history"]["age_range"]["major"] = [0.5, 1.5]
    with pytest.raises(ConfigError, match=r"history\.age_range"):
        validate(cfg)


def test_template_with_an_unknown_token_is_rejected() -> None:
    # {liege} belongs to conquest, not founding.
    cfg = get_defaults()
    cfg["tables"]["chronicle"]["founding"]["templates"] = ["{realm} bows to {liege}."]
    with pytest.raises(ConfigError, match=r"tables\.chronicle\.founding\.templates: unknown token \{liege\}"):
        validate(cfg)


def test_near_in_a_plain_template_is_rejected() -> None:
    # {near} may only appear in templates_near, so a plain sentence never names a far place.
    cfg = get_defaults()
    cfg["tables"]["chronicle"]["war"]["templates"] = ["War breaks out near {near}."]
    with pytest.raises(ConfigError, match=r"tables\.chronicle\.war\.templates: unknown token \{near\}"):
        validate(cfg)


def test_near_template_without_near_is_rejected() -> None:
    cfg = get_defaults()
    cfg["tables"]["chronicle"]["battle"]["templates_near"] = ["A battle is fought."]
    with pytest.raises(ConfigError, match=r"templates_near: 'A battle is fought\.' must use \{near\}"):
        validate(cfg)


def test_missing_chronicle_row_is_rejected() -> None:
    cfg = get_defaults()
    del cfg["tables"]["chronicle"]["fall"]
    with pytest.raises(ConfigError, match=r"tables\.chronicle must have exactly the rows"):
        validate(cfg)


def test_chronicle_row_may_omit_the_near_list() -> None:
    # templates_near is optional.
    cfg = get_defaults()
    del cfg["tables"]["chronicle"]["battle"]["templates_near"]
    validate(cfg)


def test_year_is_a_token_of_every_row() -> None:
    cfg = get_defaults()
    cfg["tables"]["chronicle"]["conquest"]["templates"] = ["In {year}, {liege} conquers {realm}."]
    validate(cfg)
