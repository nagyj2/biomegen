"""Tests for the chronicle's text and JSON output."""

from __future__ import annotations

import json
import re

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.world.chronicle import (
    ChronicleFilter,
    chronicle_data,
    chronicle_json,
    chronicle_text,
    describe_filter,
    filter_events,
)
from biomegen.world.entities import ChronicleEvent, FallenRealm, Realm
from biomegen.world.world import World


@pytest.fixture(scope="module")
def generated() -> World:
    return pipeline.generate(load_config(None), 42)


def _tiny() -> World:
    world = World(4, 4, 9)
    world.island_name = "Testisle"
    world.year = 500
    world.realms = [Realm(id=0, kind="major", name="Kingdom of A", founded=100)]
    world.fallen_realms = [FallenRealm(id=0, location=(1, 2), founded=10, fell=90, culture="common", name="Old Realm")]
    world.chronicle = [
        ChronicleEvent(0, 100, "founding", [0], text="A is founded."),
        ChronicleEvent(1, 90, "fall", fallen_ids=[0], location=(1, 2), text="Old Realm falls."),
    ]
    return world


def test_text_has_a_title_with_the_present() -> None:
    assert chronicle_text(_tiny()).splitlines()[0] == "The Chronicle of Testisle (year 500)"


def test_text_lists_one_line_per_event() -> None:
    assert chronicle_text(_tiny()).splitlines()[2:] == [
        "  100  founding    A is founded.",
        "   90  fall        Old Realm falls.",
    ]


def test_text_has_year_kind_and_text_columns(generated: World) -> None:
    # Every event line is a right-aligned year, a padded event type, then the text.
    lines = chronicle_text(generated).splitlines()[2:]
    assert lines and all(re.fullmatch(r" *\d+  [a-z]+ {2,}\S.*", line) for line in lines)


def test_json_events_list_the_spans_of_their_names() -> None:
    world = _tiny()
    world.chronicle[0].refs = [(0, 1, "realm", 0)]
    assert chronicle_data(world)["events"][0]["refs"] == [{"start": 0, "end": 1, "type": "realm", "id": 0}]


def test_text_of_a_world_without_events_is_just_the_title() -> None:
    world = World(4, 4, 9)
    assert chronicle_text(world).strip() == "The Chronicle of the island (year 0)"


def test_an_event_without_a_cell_has_a_null_location() -> None:
    assert chronicle_data(_tiny())["events"][0]["location"] is None


def test_an_event_with_a_cell_lists_it() -> None:
    assert chronicle_data(_tiny())["events"][1]["location"] == [1, 2]


def test_an_independent_realm_has_a_null_liege() -> None:
    assert chronicle_data(_tiny())["realms"][0]["liege"] is None


def test_fallen_realms_are_listed_with_their_years() -> None:
    assert chronicle_data(_tiny())["fallen_realms"] == [
        {"id": 0, "name": "Old Realm", "culture": "common", "location": [1, 2], "founded": 10, "fell": 90}
    ]


def test_json_round_trips_to_the_data() -> None:
    world = _tiny()
    assert json.loads(chronicle_json(world)) == chronicle_data(world)


def test_json_keeps_non_ascii_names() -> None:
    world = _tiny()
    world.island_name = "Ærø"
    assert "Ærø" in chronicle_json(world)


def test_every_id_in_the_json_names_an_entity(generated: World) -> None:
    data = chronicle_data(generated)
    realms, fallen = {r["id"] for r in data["realms"]}, {f["id"] for f in data["fallen_realms"]}
    pois = {s["id"] for s in data["settlements"]}
    for event in data["events"]:
        assert set(event["realm_ids"]) <= realms and set(event["fallen_ids"]) <= fallen
        assert set(event["poi_ids"]) <= pois and event["near_poi"] in pois | {None}


def test_stats_count_the_events_by_kind(generated: World) -> None:
    stats = pipeline.stats(generated)
    assert stats["events"] == len(generated.chronicle) == sum(stats["event_kinds"].values())  # type: ignore[arg-type]


def test_stats_count_the_fallen_realms(generated: World) -> None:
    assert pipeline.stats(generated)["fallen_realms"] == len(generated.fallen_realms)


# --- rulers, predecessors and origins in the JSON -------------------------------------------------------------------


def _with_secession() -> World:
    from biomegen.world.entities import Predecessor, Ruler

    world = _tiny()
    world.realms[0].origin, world.realms[0].predecessor, world.realms[0].ruler = "split", 0, "King Bran"
    world.realms.append(Realm(id=1, kind="major", name="Kingdom of B", founded=100, origin="offshoot", parent=0))
    world.predecessors = [
        Predecessor(id=0, founded=20, split_year=100, children=[0], name="Old Kingdom", culture="common")
    ]
    world.rulers = [
        Ruler(
            id=0,
            realm_id=0,
            from_year=100,
            to_year=None,
            style="martial",
            traits={"trust": 0.5123456},
            name="King Bran",
        )
    ]
    world.chronicle[0].predecessor_ids = [0]
    return world


def test_the_json_lists_the_rulers_of_a_realm() -> None:
    (ruler,) = chronicle_data(_with_secession())["rulers"]
    assert (ruler["realm_id"], ruler["name"], ruler["from_year"], ruler["to_year"]) == (0, "King Bran", 100, None)


def test_the_json_rounds_a_rulers_traits() -> None:
    assert chronicle_data(_with_secession())["rulers"][0]["traits"] == {"trust": 0.512}


def test_the_json_lists_the_predecessors_and_their_children() -> None:
    (predecessor,) = chronicle_data(_with_secession())["predecessors"]
    assert (predecessor["name"], predecessor["split_year"], predecessor["children"]) == ("Old Kingdom", 100, [0])


def test_the_json_gives_each_realm_its_origin() -> None:
    realms = chronicle_data(_with_secession())["realms"]
    assert [(r["origin"], r["parent"], r["predecessor"]) for r in realms] == [("split", None, 0), ("offshoot", 0, None)]


def test_a_realm_founded_outright_has_no_origin_in_the_json(generated: World) -> None:
    assert all(
        r["origin"] is None
        for r in chronicle_data(generated)["realms"]
        if r["parent"] is None and r["predecessor"] is None
    )


def test_an_event_names_its_predecessors_in_the_json() -> None:
    assert chronicle_data(_with_secession())["events"][0]["predecessor_ids"] == [0]


def test_the_json_with_secession_is_still_json() -> None:
    assert json.loads(chronicle_json(_with_secession()))["predecessors"][0]["id"] == 0


def test_every_ruler_of_a_generated_world_is_in_the_json(generated: World) -> None:
    rulers = chronicle_data(generated)["rulers"]
    assert len(rulers) == len(generated.rulers) and all(r["name"] for r in rulers)


def test_stats_count_rulers_predecessors_origins_and_free_settlements(generated: World) -> None:
    stats = pipeline.stats(generated)
    assert stats["rulers"] == len(generated.rulers) and stats["predecessors"] == len(generated.predecessors)
    assert stats["free_settlements"] == sum(1 for p in generated.pois if p.free)
    assert sum(stats["realm_origins"].values()) == len([r for r in generated.realms if r.origin])  # type: ignore[attr-defined]


def _ids(world: World, **fields) -> list[int]:
    return [event.id for event in filter_events(world, ChronicleFilter(**fields))]


def test_an_empty_filter_keeps_every_event() -> None:
    assert _ids(_tiny()) == [0, 1]


def test_the_kind_filter_keeps_the_listed_kinds() -> None:
    assert _ids(_tiny(), kinds=("fall",)) == [1]


def test_the_year_range_includes_both_ends() -> None:
    assert _ids(_tiny(), year_from=90, year_to=100) == [0, 1]


def test_the_year_range_drops_events_outside_it() -> None:
    assert _ids(_tiny(), year_from=91) == [0]


def test_the_realm_filter_matches_a_fallen_realm_by_name() -> None:
    # "old" is in Old Realm, a fallen realm named by event 1 only
    assert _ids(_tiny(), realm="OLD") == [1]


def test_the_realm_filter_matches_a_live_realm_by_name() -> None:
    assert _ids(_tiny(), realm="kingdom") == [0]


def test_the_text_filter_matches_any_case() -> None:
    assert _ids(_tiny(), text="FALLS") == [1]


def test_the_text_filter_matches_the_kind_word() -> None:
    assert _ids(_tiny(), text="founding") == [0]


def test_filters_combine_with_and() -> None:
    assert _ids(_tiny(), kinds=("fall",), year_from=95) == []


def test_text_of_filtered_events_lists_only_them() -> None:
    world = _tiny()
    events = filter_events(world, ChronicleFilter(kinds=("fall",)))
    assert chronicle_text(world, events).splitlines()[2:] == ["   90  fall        Old Realm falls."]


def test_text_of_no_events_says_so() -> None:
    assert chronicle_text(_tiny(), []).splitlines()[2:] == ["(no matching events)"]


def test_json_of_filtered_events_keeps_every_entity() -> None:
    world = _tiny()
    data = chronicle_data(world, filter_events(world, ChronicleFilter(kinds=("fall",))))
    assert [len(data["events"]), len(data["realms"]), len(data["fallen_realms"])] == [1, 1, 1]


def test_describe_filter_is_empty_without_a_filter() -> None:
    assert describe_filter(ChronicleFilter()) == ""


def test_describe_filter_names_each_part() -> None:
    text = describe_filter(ChronicleFilter(kinds=("war",), year_from=100, realm="a", text="b"))
    assert text == "kind war  years 100-  name 'a'  text 'b'"
