"""Tests for naming fallen realms and rendering the chronicle's event texts."""

from __future__ import annotations

import re

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.naming import chronicle, polity
from biomegen.util.units import grid_scale
from biomegen.world.entities import POI, ChronicleEvent, FallenRealm, GeoFeature, Predecessor, Realm, Relation, Ruler
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
    world.rulers = [  # realm 0 has two reigns, the second from year 200; realm 1 one
        Ruler(id=0, realm_id=0, from_year=50, to_year=200, style="martial", name="King Bran"),
        Ruler(id=1, realm_id=0, from_year=200, to_year=None, style="gentle", name="Queen Ede"),
        Ruler(id=2, realm_id=1, from_year=50, to_year=None, style="pious", name="Duke Cal"),
    ]
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


def _with_fallen(event: ChronicleEvent, world: World) -> ChronicleEvent:
    """Give ``event`` realm 0 and the fallen realm 0, as a war or battle with a ruin has."""
    event.realm_ids, event.fallen_ids = [0], [0]
    return event


def test_a_fallen_realms_founding_names_it(cfg: Config) -> None:
    world = _small_world()
    event = ChronicleEvent(0, 100, "founding", fallen_ids=[0], template="{fallen} rises in {year}.")
    assert _render(world, event, cfg) == f"{world.fallen_realms[0].name} rises in 100."


def test_a_war_with_a_fallen_realm_names_the_attacker_first(cfg: Config) -> None:
    world = _small_world()
    tags = ("attacker:fallen",)
    event = _with_fallen(ChronicleEvent(0, 100, "war", tags=tags, template="{attacker} attacks {defender}."), world)
    assert _render(world, event, cfg) == f"{world.fallen_realms[0].name} attacks Kingdom of Aldor."


def test_a_realm_can_be_the_attacker_of_a_fallen_realm(cfg: Config) -> None:
    world = _small_world()
    tags = ("attacker:realm",)
    event = _with_fallen(
        ChronicleEvent(0, 100, "war", tags=tags, template="{attacker_short} attacks {defender}."), world
    )
    assert _render(world, event, cfg) == f"Aldor attacks {world.fallen_realms[0].name}."


def test_a_ruins_battle_names_the_winner_by_its_tag(cfg: Config) -> None:
    world = _small_world()
    tags = ("ruins", "won_by_fallen")
    event = _with_fallen(ChronicleEvent(0, 100, "battle", tags=tags, template="{winner} beats {loser_short}."), world)
    assert _render(world, event, cfg) == f"{world.fallen_realms[0].name} beats Aldor."


def test_a_conquest_of_a_fallen_realm_names_the_victor(cfg: Config) -> None:
    world = _small_world()
    template = "{victor} ({victor_short}) ends {fallen}."
    event = _with_fallen(ChronicleEvent(0, 100, "fall", tags=("conquered",), template=template), world)
    assert _render(world, event, cfg) == f"Kingdom of Aldor (Aldor) ends {world.fallen_realms[0].name}."


def test_a_peace_names_winner_and_loser(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "peace", [1, 0], template="{winner_short} beats {loser_short}.")
    assert _render(_small_world(), event, cfg) == "Wend beats Aldor."


# --- the spans of names ---------------------------------------------------------------------------------


def _names(event: ChronicleEvent) -> list[tuple[str, str]]:
    return [(event.text[start:end], kind) for start, end, kind, _ in event.refs]


def test_a_founding_marks_the_realm_ruler_and_seat(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [0], [0], template="{realm} under {ruler} at {seat}.")
    _render(_small_world(), event, cfg)
    assert _names(event) == [("Kingdom of Aldor", "realm"), ("King Bran", "ruler"), ("Aldburg", "poi")]


def test_a_seatless_realms_seat_is_marked_as_the_realm(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [1], template="rises at {seat}")
    _render(_small_world(), event, cfg)
    assert _names(event) == [("Wend", "realm")]


def test_a_conquest_marks_the_lieges_ruler_as_a_ruler(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "conquest", [1, 0], template="{liege} under {ruler} takes {realm}.")
    _render(_small_world(), event, cfg)
    assert _names(event) == [("Kingdom of Aldor", "realm"), ("King Bran", "ruler"), ("Duchy of Wend", "realm")]


def test_a_near_place_is_marked_as_a_place(cfg: Config) -> None:
    event = ChronicleEvent(0, 300, "fall", fallen_ids=[0], near_poi=1, template="Ruins near {near}.")
    _render(_small_world(), event, cfg)
    assert _names(event) == [("Wendham", "poi")]


def test_a_fallen_realm_is_marked_as_fallen(cfg: Config) -> None:
    world = _small_world()
    event = ChronicleEvent(0, 300, "fall", fallen_ids=[0], template="{fallen} falls.")
    _render(world, event, cfg)
    assert _names(event) == [(world.fallen_realms[0].name, "fallen")]


def test_a_span_ids_the_thing_it_names(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "settling", [0], [1], template="{short} settles {town}.")
    _render(_small_world(), event, cfg)
    assert [(kind, ref) for _, _, kind, ref in event.refs] == [("realm", 0), ("poi", 1)]


def test_text_that_names_nothing_has_no_spans(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [0], template="A year passes in {year}.")
    _render(_small_world(), event, cfg)
    assert event.refs == []


def test_the_capitalised_first_letter_does_not_move_a_span(cfg: Config) -> None:
    event = ChronicleEvent(0, 100, "founding", [0], template="the {short} rise.")
    _render(_small_world(), event, cfg)
    assert event.text[event.refs[0][0] : event.refs[0][1]] == "Aldor"


def test_every_span_in_a_generated_world_covers_a_name(world: World) -> None:
    names = {r.name for r in world.realms} | {r.short for r in world.realms} | {r.name for r in world.rulers}
    names |= {p.name for p in (*world.pois, *world.vanished)} | {f.name for f in world.fallen_realms}
    names |= {f.name.removeprefix("The ") for f in world.features}  # a river, range or sea named in a reason
    spans = [(e.text[a:b], kind) for e in world.chronicle for a, b, kind, _ in e.refs]
    lowered = {name.lower() for name in names}  # a ruler's title may be capitalised to open the sentence
    assert spans and all(text.lower() in lowered for text, _ in spans)


def test_a_place_named_in_a_reason_is_marked_in_the_event_text(cfg: Config) -> None:
    # The reason's own river span moves to where the reason lands in the event's text.
    world = _small_world()
    world.features = [GeoFeature(id=0, kind="river", anchor=(0, 0), name="The Wend")]
    world.relations[0].why, world.relations[0].places = "control of the {river}", {"river": 0}
    polity.describe_relations(world, cfg, 1)
    event = ChronicleEvent(0, 100, "battle", [0, 1], template="{winner_short} beats {loser_short} over {reason}.")
    _render(world, event, cfg)
    spans = [(event.text[a:b], kind) for a, b, kind, _ in event.refs]
    assert ("Wend", "feature") in spans


def test_a_town_in_a_reason_is_marked_in_the_event_text(cfg: Config) -> None:
    world = _small_world()
    world.relations[0].why = "the border town of {town}"
    polity.describe_relations(world, cfg, 1)
    event = ChronicleEvent(0, 100, "battle", [0, 1], template="{winner_short} beats {loser_short} over {reason}.")
    _render(world, event, cfg)
    assert ("Wendham", "poi") in [(event.text[a:b], kind) for a, b, kind, _ in event.refs]


def test_a_town_named_in_a_reason_is_marked_as_a_settlement(world: World) -> None:
    for relation in world.relations:
        for start, end, kind, ident in relation.why_refs:
            if kind == "poi":
                assert relation.why[start:end] == world.pois[ident].name


# --- rulers in the texts ---------------------------------------------------------------------------------------------


def test_a_founding_names_the_founder_of_that_year(cfg: Config) -> None:
    # Realm 0 has had two rulers; a founding in year 60 names the first, not the present one.
    event = ChronicleEvent(0, 60, "founding", [0], template="{realm} under {ruler}.")
    assert _render(_small_world(), event, cfg) == "Kingdom of Aldor under King Bran."


def test_a_conquest_names_the_lieges_ruler_in_the_year_of_the_conquest(cfg: Config) -> None:
    later = ChronicleEvent(0, 250, "conquest", [1, 0], template="{liege} under {ruler} takes {realm}.")
    earlier = ChronicleEvent(0, 150, "conquest", [1, 0], template="{liege} under {ruler} takes {realm}.")
    assert _render(_small_world(), later, cfg).split(" under ")[1].startswith("Queen Ede")
    assert _render(_small_world(), earlier, cfg).split(" under ")[1].startswith("King Bran")


def _succession(year: int = 200) -> ChronicleEvent:
    return ChronicleEvent(
        0,
        year,
        "succession",
        [0],
        template="{old_ruler} gives way to {ruler}: {old_style} to {style}.",
        tags=("from:martial", "to:gentle"),
    )


def test_a_succession_names_the_new_ruler_and_the_one_before(cfg: Config) -> None:
    assert _render(_small_world(), _succession(), cfg) == "King Bran gives way to Queen Ede: warlike to gentle."


def test_a_succession_marks_both_rulers_as_rulers(cfg: Config) -> None:
    event = _succession()
    _render(_small_world(), event, cfg)
    assert _names(event) == [("King Bran", "ruler"), ("Queen Ede", "ruler")]


def test_a_ruler_ref_is_the_rulers_id(cfg: Config) -> None:
    event = _succession()
    _render(_small_world(), event, cfg)
    assert [ident for *_, kind, ident in event.refs if kind == "ruler"] == [0, 1]


def test_a_realm_with_no_ruler_records_falls_back_to_its_ruler_string(cfg: Config) -> None:
    world = _small_world()
    world.rulers = []
    event = ChronicleEvent(0, 100, "founding", [0], [0], template="{realm} under {ruler}.")
    assert _render(world, event, cfg) == "Kingdom of Aldor under King Bran."


# --- predecessors ----------------------------------------------------------------------------------------------------


def _with_predecessor() -> World:
    world = _small_world()
    world.predecessors = [Predecessor(id=0, founded=40, split_year=100, children=[0, 1])]
    world.realms[0].culture = "common"
    return world


def test_a_predecessor_is_named(cfg: Config) -> None:
    world = _with_predecessor()
    chronicle.name_predecessors(world, cfg, 3)
    assert world.predecessors[0].name


def test_a_predecessor_takes_its_first_childs_culture(cfg: Config) -> None:
    world = _with_predecessor()
    world.realms[0].culture = "norse"
    chronicle.name_predecessors(world, cfg, 3)
    assert world.predecessors[0].culture == "norse"


def test_a_predecessor_is_named_the_same_every_time(cfg: Config) -> None:
    first, second = _with_predecessor(), _with_predecessor()
    chronicle.name_predecessors(first, cfg, 3)
    chronicle.name_predecessors(second, cfg, 3)
    assert first.predecessors[0].name == second.predecessors[0].name


def test_a_predecessor_name_differs_from_its_childrens(cfg: Config) -> None:
    world = _with_predecessor()
    chronicle.name_predecessors(world, cfg, 3)
    assert world.predecessors[0].name not in {r.name for r in world.realms}


def test_an_expansion_names_the_realm_its_ruler_and_seat(cfg: Config) -> None:
    event = ChronicleEvent(0, 120, "expansion", [0], template="{short} under {ruler} spreads from {seat}.")
    assert _render(_small_world(), event, cfg) == "Aldor under King Bran spreads from Aldburg."


def test_a_fallen_realms_expansion_names_the_fallen_realm(cfg: Config) -> None:
    world = _small_world()
    event = ChronicleEvent(0, 150, "expansion", fallen_ids=[0], template="{fallen} spreads over the wild.")
    world.chronicle = [event]
    chronicle.describe_events(world, cfg, 1)
    assert "{" not in event.text and world.fallen_realms[0].name in event.text


def test_every_expansion_row_resolves_all_its_tokens(cfg: Config) -> None:
    # Each wording of the two expansion rows (near ones too) leaves no {token} behind.
    for row, kwargs in (("expansion", {"realm_ids": [0]}), ("expansion_fallen", {"fallen_ids": [0]})):
        pool = cfg.get(f"tables.chronicle.{row}")
        for template in list(pool["templates"]) + list(pool.get("templates_near", [])):
            world = _small_world()
            event = ChronicleEvent(0, 150, "expansion", template=template, near_poi=1, **kwargs)
            assert "{" not in _render(world, event, cfg), template
