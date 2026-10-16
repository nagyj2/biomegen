"""Tests for config loading, deep-merge, validation, and the Config accessor."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.defaults import get_defaults
from biomegen.config.loader import _deep_merge
from biomegen.config.validate import ConfigError, validate


def test_defaults_load_without_a_file() -> None:
    cfg = load_config(None)
    assert cfg.get("world.width") == 240
    assert cfg.get("terrain.noise_backend") == "perlin"


def test_dotted_get_and_section() -> None:
    cfg = load_config(None)
    assert cfg.get("render.zoom_scale") == 4
    render = cfg.section("render")
    assert render.get("zoom_scale") == 4


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
    assert base["terrain"]["base_octaves"] == original["terrain"]["base_octaves"]


def test_validate_collects_errors() -> None:
    cfg = get_defaults()
    cfg["world"]["width"] = -5
    cfg["world"]["size_mode"] = "sideways"
    with pytest.raises(ConfigError) as exc:
        validate(cfg)
    msg = str(exc.value)
    assert "world.width" in msg and "size_mode" in msg


@pytest.mark.parametrize("size_km", [[6000.0], [6000.0, 0.0], ["6000", 3000.0], 6000.0])
def test_validate_rejects_malformed_size_km(size_km: object) -> None:
    # world.size_km must be exactly two positive numbers.
    cfg = get_defaults()
    cfg["world"]["size_km"] = size_km
    with pytest.raises(ConfigError, match="world.size_km"):
        validate(cfg)


def test_validate_rejects_an_unknown_pan_mode() -> None:
    cfg = get_defaults()
    cfg["controls"]["pan"] = "sideways"
    with pytest.raises(ConfigError, match="controls.pan"):
        validate(cfg)


def test_validate_clamps_center_lat() -> None:
    # An out-of-range latitude is clamped, not fatal.
    cfg = get_defaults()
    cfg["world"]["center_lat"] = 120.0
    validate(cfg)
    assert cfg["world"]["center_lat"] == 90.0


def test_validate_accepts_seed_center_lat() -> None:
    # "seed" is a mode, not a number: it passes validation untouched.
    cfg = get_defaults()
    cfg["world"]["center_lat"] = "seed"
    validate(cfg)
    assert cfg["world"]["center_lat"] == "seed"


@pytest.mark.parametrize("lat_range", [[48.0, 18.0], [-5.0, 20.0], [10.0, 95.0], [18.0], "18-48"])
def test_validate_rejects_malformed_center_lat_range(lat_range: object) -> None:
    # world.center_lat_range_deg must be [min, max] with 0 <= min <= max <= 89.
    cfg = get_defaults()
    cfg["world"]["center_lat_range_deg"] = lat_range
    with pytest.raises(ConfigError, match="center_lat_range_deg"):
        validate(cfg)


def test_cached_builds_a_value_once_per_key() -> None:
    # A second lookup of the same key returns the first build without calling the builder again.
    config = load_config(None)
    calls: list[int] = []

    def build() -> int:
        calls.append(1)
        return len(calls)

    assert (config.cached("key", build), config.cached("key", build), calls) == (1, 1, [1])


def test_cached_values_belong_to_one_config() -> None:
    # Two configs never share a cached value, even for the same key.
    first, second = load_config(None), load_config(None)
    first.cached("key", lambda: "first")
    assert second.cached("key", lambda: "second") == "second"
