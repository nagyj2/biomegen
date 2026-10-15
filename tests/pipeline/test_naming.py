"""Tests for the naming stage (island, realm and place names, order invariance)."""

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


# --------------------------------------------------------------------------- naming
def test_island_is_named(world):
    assert world.island_name


def test_every_realm_is_named_and_ruled(world):
    assert world.realms and all(r.name and r.short and r.ruler and r.culture for r in world.realms)


def test_no_reason_keeps_an_unfilled_token(world):
    assert world.relations and all("{" not in r.why for r in world.relations)


def test_every_poi_has_a_name(world):
    assert all(p.name for p in world.pois)


def test_a_city_state_is_short_named_after_its_seat(world):
    states = [r for r in world.realms if r.kind == "city_state"]
    assert states and all(r.short == world.pois[r.seat_poi].name for r in states)


def test_poi_names_do_not_depend_on_poi_order(cfg):
    """Shuffling the POI list before naming must not change any POI name (identity-keyed)."""
    w = pipeline.generate(cfg, 777)
    before = (w.island_name, {(p.x, p.y): p.name for p in w.pois})
    w2 = pipeline.generate(cfg, 777)
    random.Random(2).shuffle(w2.pois)
    naming.run(w2, cfg, w2.seed)
    after = (w2.island_name, {(p.x, p.y): p.name for p in w2.pois})
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
