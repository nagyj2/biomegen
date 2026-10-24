"""Tests for the coloured chronicle document: columns, kind colours and name colours (the map's own colours)."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.backends.plain import to_plain
from biomegen.render.chronicle import chronicle_document, layout_events
from biomegen.world.chronicle import KIND_WIDTH, WHEN_WIDTH, chronicle_text
from biomegen.world.entities import POI, ChronicleEvent, FallenRealm, Realm, Ruler
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=(42, 7))
def generated(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _tiny() -> World:
    world = World(4, 4, 9)
    world.island_name = "Testisle"
    world.year = 500
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A", color=(200, 20, 20))]
    event = ChronicleEvent(0, 100, "founding", [0], text="Kingdom of A is founded.", refs=[(0, 12, "realm", 0)])
    world.chronicle = [event]
    return world


def _name(world: World, cfg: Config, text: str, row: int = 2):
    return next(span for span in chronicle_document(world, cfg)[row] if span.text == text)


def test_the_plain_text_of_the_document_is_the_plain_output(generated: World, cfg: Config) -> None:
    # Colour only decorates: stripped of it, the document is the same text.
    assert to_plain(chronicle_document(generated, cfg)) == chronicle_text(generated).rstrip()


def test_the_when_column_is_year_right_aligned_to_five_and_month(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert row[0].text == "  100/01"


def test_the_kind_has_its_colour(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert (row[2].text.strip(), row[2].fg) == ("founding", tuple(cfg.get("history.colors.founding")))


def test_a_realm_name_is_exactly_the_realms_map_colour(cfg: Config) -> None:
    assert _name(_tiny(), cfg, "Kingdom of A").fg == (200, 20, 20)


def test_text_outside_a_name_is_uncoloured(cfg: Config) -> None:
    row = chronicle_document(_tiny(), cfg)[2]
    assert row[-1].text == " is founded." and row[-1].fg is None


def test_a_ruler_takes_the_colour_of_their_realm(cfg: Config) -> None:
    world = _tiny()
    world.rulers = [Ruler(id=0, realm_id=0, from_year=1, to_year=None, style="martial")]
    world.chronicle[0].refs = [(0, 12, "ruler", 0)]
    assert _name(world, cfg, "Kingdom of A").fg == (200, 20, 20)


def test_a_fallen_realm_has_its_own_colour(cfg: Config) -> None:
    world = _tiny()
    world.fallen_realms = [FallenRealm(id=0, location=(1, 1), founded=1, fell=2, color=(10, 200, 30))]
    world.chronicle[0].refs = [(0, 12, "fallen", 0)]
    assert _name(world, cfg, "Kingdom of A").fg == (10, 200, 30)


def _with_settlement(realm_id: int) -> World:
    world = _tiny()
    world.pois = [POI(kind="town", x=1, y=1, interior_seed=1, civilized=True, realm_id=realm_id, name="Wendham")]
    first = ChronicleEvent(0, 100, "settling", [0], text="Wendham is settled.", refs=[(0, 7, "poi", 0)])
    again = ChronicleEvent(1, 200, "war", [0], text="War over Wendham.", refs=[(9, 16, "poi", 0)])
    world.chronicle = [first, again]
    return world


def test_a_settlement_is_its_realms_colour_from_its_first_mention(cfg: Config) -> None:
    assert _name(_with_settlement(0), cfg, "Wendham").fg == (200, 20, 20)


def test_a_settlement_is_its_realms_colour_every_time(cfg: Config) -> None:
    assert _name(_with_settlement(0), cfg, "Wendham", row=3).fg == (200, 20, 20)


def test_a_wild_settlement_stays_neutral(cfg: Config) -> None:
    assert _name(_with_settlement(-1), cfg, "Wendham", row=3).fg == tuple(cfg.get("history.colors.settlement"))


def test_a_named_place_of_the_land_has_the_neutral_place_colour(cfg: Config) -> None:
    world = _tiny()
    world.chronicle[0].refs = [(0, 12, "feature", 0)]
    assert _name(world, cfg, "Kingdom of A").fg == tuple(cfg.get("history.colors.place"))


def test_the_two_neutral_colours_differ(cfg: Config) -> None:
    assert cfg.get("history.colors.settlement") != cfg.get("history.colors.place")


def test_every_realm_name_in_a_generated_chronicle_is_a_map_colour(generated: World, cfg: Config) -> None:
    # The chronicle never invents a colour for a realm: each realm span is the colour the political map tints it with.
    used = {
        span.fg
        for row in chronicle_document(generated, cfg)[2:]
        for span in row
        if span.fg in {realm.color for realm in generated.realms}
    }
    assert used and used <= {realm.color for realm in generated.realms}


def test_every_event_is_a_row_under_the_title(generated: World, cfg: Config) -> None:
    assert len(chronicle_document(generated, cfg)) == 2 + len(generated.chronicle)


def test_an_old_realm_that_split_has_its_own_colour(cfg: Config) -> None:
    from biomegen.world.entities import Predecessor

    world = _tiny()
    world.predecessors = [Predecessor(id=0, founded=1, split_year=50, color=(12, 120, 230))]
    world.chronicle[0].refs = [(0, 12, "predecessor", 0)]
    assert _name(world, cfg, "Kingdom of A").fg == (12, 120, 230)


def _long() -> World:
    world = _tiny()
    text = "Kingdom of A is founded " + "with a very long and winding account " * 3 + "ends."
    world.chronicle = [ChronicleEvent(0, 100, "founding", [0], text=text, refs=[(0, 12, "realm", 0)])]
    return world


def test_a_document_of_chosen_events_lists_only_them(cfg: Config) -> None:
    world = _tiny()
    world.chronicle.append(ChronicleEvent(1, 150, "war", [0], text="A fights."))
    assert to_plain(chronicle_document(world, cfg, [world.chronicle[1]])).splitlines()[2:] == [
        "  150/01  war         A fights."
    ]


def test_layout_wraps_lines_to_the_width(cfg: Config) -> None:
    lines, _, _ = layout_events(_long(), cfg, _long().chronicle, 50)
    assert max(sum(len(span.text) for span in line) for line in lines) <= 50


def test_layout_indents_continuation_lines_under_the_text(cfg: Config) -> None:
    lines, _, _ = layout_events(_long(), cfg, _long().chronicle, 50)
    indent = WHEN_WIDTH + 2 + KIND_WIDTH + 2  # year/month, gap, kind column, gap
    assert lines[1][0].text[:indent] == " " * indent


def test_layout_keeps_every_word(cfg: Config) -> None:
    world = _long()
    lines, _, _ = layout_events(world, cfg, world.chronicle, 50)
    words = " ".join("".join(span.text for span in line) for line in lines).split()
    assert words == f"  100/01  founding    {world.chronicle[0].text}".split()


def test_layout_marks_where_a_line_starts_per_event(cfg: Config) -> None:
    world = _long()
    world.chronicle.append(ChronicleEvent(1, 150, "war", [0], text="A fights."))
    lines, starts, _ = layout_events(world, cfg, world.chronicle, 50)
    assert (starts[0], starts[1], len(lines) > 2) == (0, len(lines) - 1, True)


def test_a_search_match_has_the_match_background(cfg: Config) -> None:
    world = _tiny()
    lines, _, _ = layout_events(world, cfg, world.chronicle, 60, "FOUNDED")
    marked = [span.text for span in lines[0] if span.bg == tuple(cfg.get("history.colors.match"))]
    assert marked == ["founded"]


def test_a_search_lists_the_matching_events(cfg: Config) -> None:
    world = _tiny()
    world.chronicle.append(ChronicleEvent(1, 150, "war", [0], text="A fights."))
    assert layout_events(world, cfg, world.chronicle, 60, "fights")[2] == [1]


def test_no_search_marks_nothing(cfg: Config) -> None:
    world = _tiny()
    lines, _, matches = layout_events(world, cfg, world.chronicle, 60)
    assert (matches, all(span.bg is None for span in lines[0])) == ([], True)


def test_every_term_of_an_expression_is_marked(cfg: Config) -> None:
    lines, _, _ = layout_events(_tiny(), cfg, _tiny().chronicle, 60, "kingdom|FOUNDED")
    marked = [span.text for span in lines[0] if span.bg == tuple(cfg.get("history.colors.match"))]
    assert marked == ["Kingdom", "founded"]


def test_an_and_expression_matches_only_events_with_every_term(cfg: Config) -> None:
    world = _tiny()
    world.chronicle.append(ChronicleEvent(1, 150, "war", [0], text="A fights."))
    assert layout_events(world, cfg, world.chronicle, 60, "a&fights")[2] == [1]


def test_an_and_expression_marks_nothing_in_an_event_that_lacks_a_term(cfg: Config) -> None:
    world = _tiny()
    lines, _, _ = layout_events(world, cfg, world.chronicle, 60, "founded&nothing")
    assert all(span.bg is None for span in lines[0])


def test_a_bandit_dungeon_is_never_coloured_as_the_realm_that_holds_it(config) -> None:
    # Named first and named again, it keeps the hideout colour (a settlement would turn to its realm's colour).
    from biomegen.render.chronicle import event_rows

    world = World(4, 4, 9)
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A", color=(10, 20, 200))]
    world.pois = [POI(kind="dungeon", x=1, y=1, interior_seed=1, name="Aakha Catacombs", realm_id=0)]
    world.chronicle = [
        ChronicleEvent(0, 10, "creation", poi_ids=[0], text="Aakha Catacombs is delved.", refs=[(0, 15, "poi", 0)]),
        ChronicleEvent(
            1, 24, "road", poi_ids=[0], text="A track is cut from Aakha Catacombs.", refs=[(20, 35, "poi", 0)]
        ),
    ]
    hideout = tuple(int(c) for c in config.get("history.colors.hideout"))
    named = [span.fg for row in event_rows(world, config) for span in row if span.text == "Aakha Catacombs"]
    assert named == [hideout, hideout]
