"""Tests for the render.views / render.ramps config and its validation."""

from __future__ import annotations

import pytest

from biomegen.config.defaults import get_defaults
from biomegen.config.validate import ConfigError, validate


def test_default_views_tint_with_a_defined_ramp() -> None:
    # Every default view that names a tint ramp names one that render.ramps defines (or the realm tint).
    render = get_defaults()["render"]
    tints = {view["tint"] for view in render["views"].values() if view["tint"]}
    assert tints <= set(render["ramps"]) | {"realm"}


def test_default_ramps_are_ascending() -> None:
    # Stops must ascend so a value falls between exactly one pair of stops.
    for ramp in get_defaults()["render"]["ramps"].values():
        values = [value for value, _ in ramp["stops"]]
        assert values == sorted(values)


def test_validate_coerces_ramp_hex_colour() -> None:
    cfg = get_defaults()
    cfg["render"]["ramps"]["rainfall"]["stops"][0][1] = "#102030"
    validate(cfg)
    assert cfg["render"]["ramps"]["rainfall"]["stops"][0][1] == [16, 32, 48]


def test_validate_rejects_a_descending_ramp() -> None:
    cfg = get_defaults()
    cfg["render"]["ramps"]["rainfall"]["stops"].reverse()
    with pytest.raises(ConfigError, match="ascending"):
        validate(cfg)


def test_validate_rejects_a_one_stop_ramp() -> None:
    cfg = get_defaults()
    cfg["render"]["ramps"]["rainfall"]["stops"] = [[0, [1, 2, 3]]]
    with pytest.raises(ConfigError, match="at least two"):
        validate(cfg)


def test_validate_rejects_a_tint_without_a_ramp() -> None:
    cfg = get_defaults()
    cfg["render"]["views"]["elevation"]["tint"] = "nope"
    with pytest.raises(ConfigError, match="not a render.ramps entry"):
        validate(cfg)


def test_validate_rejects_non_list_layers() -> None:
    cfg = get_defaults()
    cfg["render"]["views"]["terrain"]["layers"] = "terrain"
    with pytest.raises(ConfigError, match="list of layer names"):
        validate(cfg)


def test_validate_rejects_a_ramp_over_an_unknown_field() -> None:
    cfg = get_defaults()
    cfg["render"]["ramps"]["rainfall"]["field"] = "rainfall"
    with pytest.raises(ConfigError, match="World array"):
        validate(cfg)


def test_validate_coerces_a_water_colour() -> None:
    cfg = get_defaults()
    cfg["render"]["ramps"]["rainfall"]["water_color"] = "#010203"
    validate(cfg)
    assert cfg["render"]["ramps"]["rainfall"]["water_color"] == [1, 2, 3]


@pytest.mark.parametrize("name", ["elevation", "temperature", "rainfall", "political"])
def test_tinted_views_draw_clutter_roads_and_sites_at_the_detail_scales(name: str) -> None:
    # Clutter sits under the tint; roads, markers and sites are drawn over it, so the ground shows through the tint.
    layers = get_defaults()["render"]["views"][name]["detail_layers"]
    assert layers.index("clutter") < layers.index("tint") < layers.index("roads") < layers.index("sites")
