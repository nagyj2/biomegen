"""Tests for the naming stage (island/region names, lore, order invariance)."""

from __future__ import annotations

import random

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.pipeline import naming


@pytest.fixture(scope="module")
def cfg():
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg):
    return pipeline.generate(cfg, 9999)


# --------------------------------------------------------------------------- naming + lore
def test_island_and_regions_named(world):
    assert world.island_name
    assert all(r.name for r in world.regions)


def test_region_lore_nonempty(world, cfg):
    lore_min = int(cfg.get("naming.lore_min"))
    for r in world.regions:
        assert len(r.lore) >= lore_min


def test_every_poi_has_a_name(world):
    assert all(p.name for p in world.pois)


def test_naming_is_order_invariant(cfg):
    """Shuffling the entity lists before naming must not change any name (identity-keyed)."""
    w = pipeline.generate(cfg, 777)
    before = (w.island_name, {r.id: r.name for r in w.regions}, {(p.x, p.y): p.name for p in w.pois})
    w2 = pipeline.generate(cfg, 777)
    random.Random(1).shuffle(w2.regions)
    random.Random(2).shuffle(w2.pois)
    naming.run(w2, cfg, w2.seed)
    after = (w2.island_name, {r.id: r.name for r in w2.regions}, {(p.x, p.y): p.name for p in w2.pois})
    assert before == after


def test_naming_does_not_change_fingerprint(cfg):
    """Names live on entities, not arrays, so re-running naming must not alter the world fingerprint."""
    w = pipeline.generate(cfg, 321)
    fp = w.fingerprint()
    naming.run(w, cfg, w.seed)
    assert w.fingerprint() == fp


# --------------------------------------------------------------------------- geographic features
def test_every_feature_is_named(world):
    assert world.features and all(f.name for f in world.features)


def test_lake_and_river_features_reuse_entity_names(world):
    # One river, one name: the feature carries the River / Lake entity's name.
    for f in world.features:
        if f.kind == "lake":
            assert f.name == world.lakes[f.ref].name
        elif f.kind == "river":
            assert f.name == world.rivers[f.ref].name


@pytest.mark.parametrize("kind", ["range", "peak", "sea"])
def test_feature_names_follow_a_configured_form(world, cfg, kind):
    # Each name is one of the kind's forms with a root word in place of {n}.
    forms = cfg.get(f"tables.geo_names.{kind}.forms")
    prefix_suffix = [tuple(form.split("{n}")) for form in forms]
    for f in (f for f in world.features if f.kind == kind):
        assert any(f.name.startswith(a) and f.name.endswith(b) and len(f.name) > len(a + b) for a, b in prefix_suffix)


def test_overridden_forms_are_used():
    cfg = load_config(None)
    cfg.data["tables"]["geo_names"]["sea"]["forms"] = ["Sea of {n}"]
    world = pipeline.generate(cfg, 9999)
    seas = [f.name for f in world.features if f.kind == "sea"]
    assert seas and all(name.startswith("Sea of ") for name in seas)


def test_feature_name_is_keyed_on_its_anchor(cfg):
    from biomegen.naming import forge

    row = cfg.get("tables.geo_names.range")
    generators, naming_cfg = cfg.get("naming.generators"), cfg.section("naming")
    first = forge.name_feature(7, "range", (10, 4), "norse", row, generators, naming_cfg)
    again = forge.name_feature(7, "range", (10, 4), "norse", row, generators, naming_cfg)
    others = {forge.name_feature(7, "range", (x, 4), "norse", row, generators, naming_cfg) for x in range(11, 21)}
    assert first == again and len(others) > 1


def test_form_without_placeholder_is_rejected():
    from biomegen.config.defaults import get_defaults
    from biomegen.config.validate import ConfigError, validate

    bad = get_defaults()
    bad["tables"]["geo_names"]["peak"]["forms"] = ["Mount Doom"]
    with pytest.raises(ConfigError, match="geo_names.peak.forms"):
        validate(bad)
