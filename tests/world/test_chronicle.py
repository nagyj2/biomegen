"""Tests for the chronicle's text and JSON output."""

from __future__ import annotations

import json
import re

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.world.chronicle import chronicle_data, chronicle_json, chronicle_text
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
