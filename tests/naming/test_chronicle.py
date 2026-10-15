"""Tests for naming fallen realms and rendering the chronicle's event texts."""

from __future__ import annotations

import re

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.naming import chronicle
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, ChronicleEvent, FallenRealm, Realm, Relation
from biomegen.world.tile import Biome
from biomegen.world.world import World

SEEDS = (42, 7)


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=SEEDS)
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _small_world() -> World:
    """Two named realms, a seat and a claimed town, one war with its reason and a fallen realm."""
    world = World(6, 3, 1, grid_scale(6, 3, (600.0, 300.0), 30.0, 0.0))
    world.biome[:] = int(Biome.GRASS)
    world.realms = [
        Realm(id=0, kind="major", seat_poi=0, name="Kingdom of Aldor", short="Aldor", ruler="King Bran"),
        Realm(id=1, kind="major", name="Duchy of Wend", short="Wend", ruler="Duke Cal"),
    ]
    world.pois = [
        POI(kind="capital", x=1, y=1, interior_seed=1, name="Aldburg", civilized=True),
        POI(kind="town", x=4, y=1, interior_seed=2, name="Wendham", civilized=True),
    ]
    world.relations = [Relation(a=0, b=1, kind="war", why="a broken pact", attacker=1, claim_poi=1)]
    world.fallen_realms = [FallenRealm(id=0, location=(3, 2), founded=100, fell=300)]
    return world


def _render(world: World, event: ChronicleEvent, config: Config) -> str:
    world.chronicle = [event]
    chronicle.describe_events(world, config, 1)
    return event.text


def test_founding_names_the_realm_its_ruler_and_seat(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [0], [0], template="{realm} under {ruler} at {seat} ({short}, {year}).")
    assert _render(_small_world(), event, cfg) == "Kingdom of Aldor under King Bran at Aldburg (Aldor, 100)."


def test_a_seatless_realm_uses_its_short_name_as_seat(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [1], template="{seat}")
    assert _render(_small_world(), event, cfg) == "Wend"


def test_conquest_names_vassal_liege_and_the_lieges_ruler(cfg: Config) -> None:
    event = ChronicleEvent(
        0, 100, "conquest", [1, 0], template="{liege} ({liege_short}) takes {realm} ({short}) under {ruler}."
    )
    assert _render(_small_world(), event, cfg) == "Kingdom of Aldor (Aldor) takes Duchy of Wend (Wend) under King Bran."


def test_settling_names_the_city(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "settling", [0], [1], template="{short} settles {town}.")
    assert _render(_small_world(), event, cfg) == "Aldor settles Wendham."


def test_war_names_attacker_defender_town_and_reason(cfg: Config) -> None:
    event = ChronicleEvent(
        0, 100, "war", [1, 0], [1], template="{attacker_short} fights {defender_short} for {town}: {reason}."
    )
    assert _render(_small_world(), event, cfg) == "Wend fights Aldor for Wendham: a broken pact."


def test_a_war_with_no_claimed_town_uses_the_fallback_words(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "war", [1, 0], template="{town}")
    assert _render(_small_world(), event, cfg) == cfg.get("tables.reason_tokens.town.fallback")


def test_battle_names_winner_and_loser(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "battle", [0, 1], template="{winner_short} beats {loser_short} ({reason}).")
    assert _render(_small_world(), event, cfg) == "Aldor beats Wend (a broken pact)."


def test_fall_names_the_fallen_realm_and_its_founding_year(cfg: Config) -> None:
    world = _small_world()
    event = ChronicleEvent(0, 300, "fall", fallen_ids=[0], template="{fallen} from {founded}.")
    assert _render(world, event, cfg) == f"{world.fallen_realms[0].name} from 100."


def test_near_names_the_nearby_settlement(cfg: Config) -> None:
    event = ChronicleEvent(0, 300, "fall", fallen_ids=[0], near_poi=1, template="Ruins near {near}.")
    assert _render(_small_world(), event, cfg) == "Ruins near Wendham."


def test_the_first_letter_is_capitalised(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [0], template="the {short} rise.")
    assert _render(_small_world(), event, cfg) == "The Aldor rise."


def test_a_fallen_realm_is_named_and_given_a_culture(cfg: Config) -> None:
    world = _small_world()
    chronicle.name_fallen_realms(world, cfg, 1)
    assert world.fallen_realms[0].name and world.fallen_realms[0].culture


def test_a_fallen_realm_keeps_its_name_across_runs(cfg: Config) -> None:
    first, second = _small_world(), _small_world()
    chronicle.name_fallen_realms(first, cfg, 1)
    chronicle.name_fallen_realms(second, cfg, 1)
    assert first.fallen_realms[0].name == second.fallen_realms[0].name


def test_fallen_realms_are_not_named_like_living_realms(world: World) -> None:
    living = {realm.name for realm in world.realms}
    assert world.fallen_realms and not living & {f.name for f in world.fallen_realms}


def test_every_fallen_realm_is_named(world: World) -> None:
    assert all(f.name and f.culture for f in world.fallen_realms)


def test_every_event_has_text(world: World) -> None:
    assert world.chronicle and all(e.text for e in world.chronicle)


def test_no_token_is_left_unresolved(world: World) -> None:
    assert not [e.text for e in world.chronicle if re.search(r"[{}]", e.text)]


def test_a_near_place_in_the_text_is_the_events_near_settlement(world: World) -> None:
    near = [e for e in world.chronicle if e.near_poi >= 0 and world.pois[e.near_poi].name in e.text]
    assert near


def test_event_text_is_the_same_on_a_second_run(cfg: Config) -> None:
    first, second = pipeline.generate(cfg, 42), pipeline.generate(cfg, 42)
    assert [e.text for e in first.chronicle] == [e.text for e in second.chronicle]
