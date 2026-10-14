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


def test_named_pois_have_names_bridges_unnamed(world):
    for p in world.pois:
        if p.kind == "bridge":
            assert p.name == ""
        else:
            assert p.name


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
