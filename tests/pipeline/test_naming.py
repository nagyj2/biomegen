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


# --------------------------------------------------------------------------- POI names and hooks
SEEDS = (42, 7)


@pytest.fixture(scope="module", params=SEEDS)
def story(request, cfg):
    return pipeline.generate(cfg, request.param)


def test_no_poi_name_or_hook_keeps_an_unfilled_token(story):
    assert all("{" not in p.name and "}" not in p.name and "{" not in p.hook for p in story.pois)


def test_a_poi_placed_by_location_has_a_hook(story):
    assert all(p.hook for p in story.pois if not p.event_ids and not p.civilized)


def test_a_poi_an_event_made_takes_that_events_text_as_its_hook(story):
    # A free settlement has its own text (hooks_free), not the event's.
    made = [p for p in story.pois if p.event_ids and not p.free]
    assert made and all(p.hook == story.chronicle[p.event_ids[0]].text for p in made)


def test_a_settlement_with_a_founding_event_has_its_hook(story):
    seats = [story.pois[r.seat_poi] for r in story.realms if r.seat_poi >= 0]
    assert seats and all(seat.hook == story.chronicle[seat.event_ids[0]].text for seat in seats)


def test_a_hooks_name_spans_cut_out_the_names(story):
    for p in story.pois:
        for start, end, kind, ident in p.hook_refs:
            if not p.event_ids and kind == "poi":
                assert p.hook[start:end] == story.pois[ident].name


def test_a_capital_ruin_is_named_for_its_fallen_realm(story):
    for fallen in story.fallen_realms:
        ruin = story.pois[int(story.poi_index[fallen.location[1], fallen.location[0]])]
        assert fallen.name.removeprefix("The ") in ruin.name


def test_a_holding_is_not_named_for_the_fallen_realm(story):
    capitals = {fallen.location for fallen in story.fallen_realms}
    for p in story.pois:
        if p.kind == "ruin" and p.event_ids and (p.x, p.y) not in capitals:
            assert all(f.name.removeprefix("The ") not in p.name for f in story.fallen_realms)


def test_a_shrine_name_uses_a_shrine_word(story):
    assert all("Shrine" in p.name or "Chapel" in p.name for p in story.pois if p.kind == "shrine")


def _style_pois(story, kind):
    return [p for p in story.pois if p.kind == kind and p.style]


def test_a_homestead_is_named_from_its_styles_patterns(story, cfg):
    # Each pattern of the style has a fixed word ("Farm", "Mill", ...): the name carries one of them.
    homesteads = _style_pois(story, "homestead")
    assert homesteads

    def words(style):
        patterns = cfg.get(f"tables.poi_styles.{style}.names")
        return {w for pattern in patterns for w in pattern.replace("{n}'s", "").replace("{n}", "").split()}

    assert all(any(word in p.name for word in words(p.style)) for p in homesteads)


def test_a_homestead_hook_comes_from_its_style_and_names_it(story):
    homesteads = _style_pois(story, "homestead")
    assert homesteads and all(p.name in p.hook for p in homesteads)


def test_a_generated_hamlet_has_a_hook(story):
    hamlets = _style_pois(story, "hamlet")
    assert hamlets and all(p.hook for p in hamlets)


def test_a_hamlet_is_never_named_as_another_places_nearby_settlement(story):
    from biomegen.world.entities import REF_POI

    hamlets = {i for i, p in enumerate(story.pois) if p.kind == "hamlet"}
    named = {ref[3] for i, p in enumerate(story.pois) for ref in p.hook_refs if ref[2] == REF_POI and ref[3] != i}
    assert not named & hamlets
