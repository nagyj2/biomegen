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
