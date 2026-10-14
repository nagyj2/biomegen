"""Tests for the config.defaults package (section modules assembled into DEFAULTS)."""

from __future__ import annotations

import importlib
import pkgutil
import tomllib
from pathlib import Path

import pytest

from biomegen.config import defaults, load_config
from biomegen.config.defaults import DEFAULTS, get_defaults

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "config.example.toml"


def test_every_section_module_is_assembled_into_defaults():
    # A section module that is not wired into DEFAULTS would silently lose its tunables.
    modules = {m.name for m in pkgutil.iter_modules(defaults.__path__)}
    assert modules == set(DEFAULTS)


@pytest.mark.parametrize("section", sorted(DEFAULTS))
def test_defaults_section_is_the_module_values(section):
    # DEFAULTS[section] is the very VALUES dict of biomegen.config.defaults.<section>.
    module = importlib.import_module(f"biomegen.config.defaults.{section}")
    assert DEFAULTS[section] is module.VALUES


def test_get_defaults_returns_an_independent_copy():
    # Mutating the returned tree must not leak back into the shared DEFAULTS.
    copy = get_defaults()
    copy["world"]["width"] = -1
    assert DEFAULTS["world"]["width"] != -1


def test_example_config_sections_exist_in_defaults():
    # config.example.toml may only override sections the defaults define.
    example = tomllib.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert set(example) <= set(DEFAULTS)


def test_example_config_loads_and_validates():
    # The shipped example is a valid sparse overlay on the defaults.
    assert load_config(str(EXAMPLE_PATH)).get("world.width") is not None


def _leaves(tree: dict, prefix: str = "") -> dict:
    """Flatten a nested table into ``{"section.key": value}``; lists and scalars are leaves."""
    flat = {}
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_leaves(value, path))
        else:
            flat[path] = value
    return flat


def test_example_config_keys_exist_in_defaults():
    # Every key the example names is a real tunable (catches typos and removed keys).
    example = _leaves(tomllib.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    assert set(example) - set(_leaves(DEFAULTS)) == set()


def test_example_config_values_equal_defaults():
    # The example documents the defaults: a value that differs is config drift.
    example = _leaves(tomllib.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    defaults_flat = _leaves(DEFAULTS)
    drift = {
        path: (value, defaults_flat.get(path)) for path, value in example.items() if value != defaults_flat.get(path)
    }
    assert drift == {}
