"""Tests for ruling styles and succession: the style timeline, the succession events and their effect on battles."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story import conflicts, rulers
from biomegen.pipeline.story.conflicts import REALM
from biomegen.pipeline.story.ledger import Ledger
from biomegen.pipeline.story.rulers import style_at
from biomegen.util.units import grid_scale
from biomegen.world.entities import Realm
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _successions(world: World) -> list:
    return [e for e in world.chronicle if e.kind == "succession"]


def _tiny(realms: int = 3) -> World:
    world = World(8, 4, 1, grid_scale(8, 4, (800.0, 400.0), 30.0, 0.0))
    world.realms = [Realm(id=i, kind="major", founded=10 * i, area_km2=1000.0) for i in range(realms)]
    return world


def _derive(world: World, **overrides: object) -> tuple[dict, list]:
    config = load_config(None)
    config.data["history"].update(overrides)
    ledger = Ledger(config)
    timelines = rulers.derive(world, config, 1, 1200, ledger)
    return timelines, ledger.finish()


# --- the timeline ---------------------------------------------------------------------------------


def test_every_realm_has_a_ruling_style_from_the_table(world: World, cfg: Config) -> None:
    assert world.realms and all(r.ruling_style in cfg.get("tables.ruling_styles") for r in world.realms)


def test_a_timeline_starts_at_the_realms_founding() -> None:
    world = _tiny()
    timelines, _ = _derive(world)
    assert all(timelines[r.id][0][0] == r.founded for r in world.realms)


def test_the_present_style_is_the_last_of_the_timeline() -> None:
    world = _tiny()
    timelines, _ = _derive(world)
    assert all(r.ruling_style == timelines[r.id][-1][1] for r in world.realms)


def test_style_at_reads_the_style_in_force() -> None:
    timeline = [(10, "a"), (100, "b"), (300, "c")]
    assert [style_at(timeline, y) for y in (5, 10, 99, 100, 299, 300, 900)] == ["a", "a", "a", "b", "b", "c", "c"]


def test_the_timelines_are_deterministic() -> None:
    assert _derive(_tiny())[0] == _derive(_tiny())[0]


def test_no_succession_ever_changes_nothing_at_chance_zero() -> None:
    world = _tiny()
    timelines, events = _derive(world, succession_change_chance=0.0)
    assert events == [] and all(len(t) == 1 for t in timelines.values())


def test_every_succession_changes_the_style_at_chance_one() -> None:
    world = _tiny()
    timelines, events = _derive(world, succession_change_chance=1.0)
    assert events and all(a != b for t in timelines.values() for (_, a), (_, b) in zip(t, t[1:], strict=False))


def test_a_changed_style_is_one_event() -> None:
    world = _tiny()
    timelines, events = _derive(world)
    assert len(events) == sum(len(t) - 1 for t in timelines.values())


def test_successions_are_a_gap_apart() -> None:
    world = _tiny()
    timelines, _ = _derive(world, succession_change_chance=1.0, succession_years=[300, 400])
    gaps = [b[0] - a[0] for t in timelines.values() for a, b in zip(t, t[1:], strict=False)]
    assert gaps and all(300 <= g <= 400 for g in gaps)


# --- the events -----------------------------------------------------------------------------------


def test_a_succession_names_the_realm_and_both_styles(world: World, cfg: Config) -> None:
    styles = cfg.get("tables.ruling_styles")
    events = _successions(world)
    assert events and all(len(e.realm_ids) == 1 and {t.split(":")[0] for t in e.tags} == {"from", "to"} for e in events)
    assert all(t.split(":")[1] in styles for e in events for t in e.tags)


def test_a_succession_changes_the_style(world: World) -> None:
    assert all(
        dict(t.split(":") for t in e.tags)["from"] != dict(t.split(":") for t in e.tags)["to"]
        for e in _successions(world)
    )


def test_a_succession_comes_after_the_realms_founding(world: World) -> None:
    assert all(e.year > world.realms[e.realm_ids[0]].founded for e in _successions(world))


def test_a_succession_text_names_both_styles(world: World, cfg: Config) -> None:
    for event in _successions(world):
        tags = dict(t.split(":") for t in event.tags)
        assert cfg.get(f"tables.ruling_styles.{tags['to']}.label") in event.text
        assert cfg.get(f"tables.ruling_styles.{tags['from']}.label") in event.text


def test_a_succession_text_leaves_no_token(world: World) -> None:
    assert not [e.text for e in _successions(world) if "{" in e.text or "}" in e.text]


def test_a_switched_off_succession_kind_makes_no_events() -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = ["founding"]
    assert not [e for e in pipeline.generate(config, 42).chronicle if e.kind == "succession"]


def test_a_switched_off_succession_kind_still_gives_every_realm_a_style() -> None:
    config = load_config(None)
    config.data["history"]["kinds"] = ["founding"]
    assert all(r.ruling_style for r in pipeline.generate(config, 42).realms)


# --- the effect on battles ------------------------------------------------------------------------


def _conflicts(timelines: dict) -> conflicts._Timeline:
    config = load_config(None)
    world = _tiny(2)
    return conflicts._Timeline(world, config, 1, 1200, Ledger(config), timelines)


def test_a_warlike_style_raises_a_realms_odds() -> None:
    timeline = _conflicts({0: [(0, "martial")], 1: [(0, "mercantile")]})
    assert timeline._odds((REALM, 0), 100) == pytest.approx(1.25 * timeline._odds((REALM, 1), 100) / 1.0)


def test_a_style_only_counts_while_it_holds() -> None:
    timeline = _conflicts({0: [(0, "mercantile"), (500, "martial")], 1: [(0, "mercantile")]})
    assert (timeline._odds((REALM, 0), 499), timeline._odds((REALM, 0), 500)) == pytest.approx((1.0, 1.25))


def test_a_realm_with_no_style_has_its_plain_strength() -> None:
    timeline = _conflicts({})
    assert timeline._odds((REALM, 0), 100) == timeline.strength[(REALM, 0)]


# --- the ruler records ---------------------------------------------------------------------------------


def _rulers_of(world: World, realm_id: int) -> list:
    return [r for r in world.rulers if r.realm_id == realm_id]


def test_every_realm_has_a_founder_from_its_founding(world: World) -> None:
    assert all(_rulers_of(world, r.id)[0].from_year == r.founded for r in world.realms)


def test_ruler_ids_are_their_index_in_the_world(world: World) -> None:
    assert [r.id for r in world.rulers] == list(range(len(world.rulers)))


def test_a_realms_reigns_follow_one_another(world: World) -> None:
    # Each reign ends the year the next begins and the present ruler's has no end.
    for realm in world.realms:
        reigns = _rulers_of(world, realm.id)
        assert all(a.to_year == b.from_year for a, b in zip(reigns, reigns[1:], strict=False))
        assert reigns[-1].to_year is None


def test_no_reign_begins_after_the_present(world: World) -> None:
    assert all(r.from_year <= world.year for r in world.rulers)


def test_silent_successions_are_rulers_too(world: World) -> None:
    # The style changes are the only events, yet there are more reigns than style changes.
    changes = len([e for e in _successions(world)])
    assert len(world.rulers) - len(world.realms) >= changes


def test_the_present_style_is_the_present_rulers(world: World) -> None:
    assert all(realm.ruling_style == _rulers_of(world, realm.id)[-1].style for realm in world.realms)


def test_a_style_change_event_begins_a_reign_of_the_new_style(world: World) -> None:
    for event in _successions(world):
        new = dict(t.split(":") for t in event.tags)["to"]
        assert any(r.from_year == event.year and r.style == new for r in _rulers_of(world, event.realm_ids[0]))


def test_a_ruler_has_each_trait_in_range(world: World) -> None:
    from biomegen.world.entities import TRAITS

    assert all(set(r.traits) == set(TRAITS) and all(0.0 <= v <= 1.0 for v in r.traits.values()) for r in world.rulers)


def test_a_rulers_traits_stay_within_the_spread_of_its_styles(world: World, cfg: Config) -> None:
    spread = float(cfg.get("history.ruler_trait_spread"))
    for ruler in world.rulers:
        base = cfg.get(f"tables.ruling_styles.{ruler.style}.traits")
        assert all(abs(v - base[name]) <= spread + 1e-9 for name, v in ruler.traits.items())


def test_martial_rulers_are_more_aggressive_than_gentle_ones() -> None:
    world = _tiny(40)
    _derive(world, succession_change_chance=1.0)
    by_style = {s: [r.traits["aggression"] for r in world.rulers if r.style == s] for s in ("martial", "gentle")}
    assert by_style["martial"] and by_style["gentle"]
    assert sum(by_style["martial"]) / len(by_style["martial"]) > sum(by_style["gentle"]) / len(by_style["gentle"])


def test_the_rulers_are_deterministic() -> None:
    first, second = _tiny(), _tiny()
    _derive(first)
    _derive(second)
    assert first.rulers == second.rulers


def test_a_realms_rulers_do_not_depend_on_the_other_realms() -> None:
    # Every draw is keyed on the realm and the reign: a world of two realms gives realm 0 what a world of three gave it.
    small, large = _tiny(2), _tiny(3)
    _derive(small)
    _derive(large)
    assert _rulers_of(small, 0) == _rulers_of(large, 0)


def test_the_trait_draws_never_move_the_style_events() -> None:
    # The personality draws use their own stream, so the spread changes the traits but not one succession event.
    narrow, wide = _derive(_tiny(), ruler_trait_spread=0.0)[1], _derive(_tiny(), ruler_trait_spread=0.5)[1]
    assert [(e.year, e.tags) for e in narrow] == [(e.year, e.tags) for e in wide]


def test_every_ruler_is_named_after_generation(world: World) -> None:
    assert world.rulers and all(r.name for r in world.rulers)


def test_a_realms_ruler_is_its_present_rulers_name(world: World) -> None:
    assert all(realm.ruler == _rulers_of(world, realm.id)[-1].name for realm in world.realms)


def test_rulers_of_a_dawn_world_are_none() -> None:
    config = load_config(None)
    config.data["history"]["start"] = "dawn"
    assert pipeline.generate(config, 42).rulers == []


def test_a_founding_text_that_names_a_ruler_names_the_founder(world: World) -> None:
    # The year-10 founding is not ruled by the ruler of year 1200: a ruler named in it is the realm's first.
    founded = [e for e in world.chronicle if e.kind == "founding" and e.realm_ids and "{ruler}" in e.template]
    assert founded
    for event in founded:
        founder = _rulers_of(world, event.realm_ids[0])[0]
        assert founder.name.lower() in event.text.lower()


def test_a_succession_text_that_names_a_ruler_names_that_reign(world: World) -> None:
    # A title may open the sentence capitalised ("The Synod of ..."), so names are compared in lower case.
    for event in _successions(world):
        reigns = _rulers_of(world, event.realm_ids[0])
        new = next(r for r in reigns if r.from_year == event.year)
        old = next(r for r in reigns if r.to_year == event.year)
        text = event.text.lower()
        assert ("{ruler}" not in event.template or new.name.lower() in text) and (
            "{old_ruler}" not in event.template or old.name.lower() in text
        )
