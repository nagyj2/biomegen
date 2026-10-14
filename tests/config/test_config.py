"""Tests for config loading, deep-merge, validation, and the Config accessor."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.loader import _deep_merge
from biomegen.config.validate import ConfigError, validate


def test_defaults_load_without_a_file() -> None:
    cfg = load_config(None)
    assert cfg.get("world.width") == 192
    assert cfg.get("terrain.noise_backend") == "perlin"


def test_dotted_get_and_section() -> None:
    cfg = load_config(None)
    assert cfg.get("render.zoom_scale") == 5
    render = cfg.section("render")
    assert render.get("zoom_scale") == 5


def test_missing_key_raises_without_default() -> None:
    cfg = load_config(None)
    with pytest.raises(KeyError):
        cfg.get("nope.not.here")
    assert cfg.get("nope.not.here", 123) == 123


def test_deep_merge_is_sparse() -> None:
    original = get_defaults()
    base = get_defaults()
    _deep_merge(base, {"world": {"width": 64}})
    assert base["world"]["width"] == 64
    # Untouched sibling keys survive the merge (compare against the pristine defaults, not literals).
    assert base["world"]["height"] == original["world"]["height"]
    assert base["terrain"]["octaves"] == original["terrain"]["octaves"]


def test_validate_coerces_hex_color() -> None:
    cfg = get_defaults()
    cfg["render"]["palette"]["ocean"] = "#102030"
    validate(cfg)
    assert cfg["render"]["palette"]["ocean"] == [16, 32, 48]


def test_validate_collects_errors() -> None:
    cfg = get_defaults()
    cfg["world"]["width"] = -5
    cfg["climate"]["orientation"] = "sideways"
    with pytest.raises(ConfigError) as exc:
        validate(cfg)
    msg = str(exc.value)
    assert "world.width" in msg and "orientation" in msg


def test_whittaker_matrix_shape_matches_bands() -> None:
    cfg = get_defaults()
    rows = len(cfg["biomes"]["temp_bands"]) + 1
    cols = len(cfg["biomes"]["moisture_bands"]) + 1
    assert len(cfg["biomes"]["matrix"]) == rows
    assert all(len(row) == cols for row in cfg["biomes"]["matrix"])
