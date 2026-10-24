"""Tests for the composite event reader: the generated chronicle and its continuation as one list."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.world.entities import POI, ChronicleEvent, Realm
from biomegen.world.ledger import EventLog
from biomegen.world.world import World


def _world() -> World:
    world = World(4, 4, 9)
    world.realms = [Realm(id=0, kind="major"), Realm(id=1, kind="major")]
    world.chronicle = [
        ChronicleEvent(0, 100, "founding", [0], month=2),
        ChronicleEvent(1, 150, "war", [0, 1], location=(1, 1), month=6),
    ]
    return world


def _later(year: int = 200, month: int = 1, **fields: object) -> ChronicleEvent:
    return ChronicleEvent(-1, year, "treaty", month=month, **fields)  # type: ignore[arg-type]


def test_an_appended_event_takes_the_next_id() -> None:
    log = EventLog(_world())
    assert log.append(_later()).id == 2


def test_the_log_counts_the_chronicle_and_the_continuation() -> None:
    log = EventLog(_world(), [_later(), _later(210)])
    assert len(log) == 4


def test_every_event_id_is_its_index() -> None:
    log = EventLog(_world(), [_later(), _later(210)])
    assert [event.id for event in log] == [0, 1, 2, 3]


def test_a_list_given_as_the_continuation_is_the_logs_own_store() -> None:
    # A simulation keeps its events in one list and the log reads and appends to that same list.
    held = [_later()]
    log = EventLog(_world(), held)
    log.append(_later(210))
    assert len(held) == 2


def test_a_list_given_as_the_continuation_is_numbered_in_place() -> None:
    held = [_later(), _later(210)]
    EventLog(_world(), held)
    assert [event.id for event in held] == [2, 3]


def test_a_continuation_that_goes_back_in_time_is_refused() -> None:
    with pytest.raises(ValueError):
        EventLog(_world(), [_later(210), _later(200)])


def test_an_index_reaches_across_the_chronicle_into_the_continuation() -> None:
    log = EventLog(_world(), [_later()])
    assert (log[1].kind, log[2].kind, log[-1].kind) == ("war", "treaty", "treaty")


def test_an_index_past_the_end_is_an_error() -> None:
    with pytest.raises(IndexError):
        EventLog(_world())[2]


def test_an_event_before_the_last_one_is_refused() -> None:
    log = EventLog(_world())
    with pytest.raises(ValueError):
        log.append(_later(150, 5))


def test_an_event_in_the_same_month_as_the_last_is_accepted() -> None:
    log = EventLog(_world())
    assert log.append(_later(150, 6)).id == 2


def test_the_first_event_of_an_empty_chronicle_is_accepted() -> None:
    log = EventLog(World(4, 4, 9))
    assert log.append(_later(5)).id == 0


def test_of_realm_adds_the_continuation_after_the_chronicle() -> None:
    log = EventLog(_world(), [_later(realm_ids=[0])])
    assert [event.kind for event in log.of_realm(0)] == ["founding", "war", "treaty"]


def test_until_keeps_the_continuation_dated_in_range() -> None:
    log = EventLog(_world(), [_later(200), _later(300)])
    assert [event.year for event in log.until(250)] == [100, 150, 200]


def test_at_finds_a_continuation_event_by_its_cell() -> None:
    log = EventLog(_world(), [_later(location=(1, 1))])
    assert [event.kind for event in log.at(1, 1)] == ["war", "treaty"]


def test_at_finds_a_continuation_event_that_names_the_poi_there() -> None:
    world = _world()
    world.pois = [POI(kind="town", x=2, y=3, interior_seed=1)]
    world.poi_index[3, 2] = 0
    log = EventLog(world, [_later(poi_ids=[0])])
    assert [event.kind for event in log.at(2, 3)] == ["treaty"]


@pytest.fixture(scope="module")
def generated() -> World:
    return pipeline.generate(load_config(None), 42)


def test_with_no_continuation_the_queries_are_the_worlds(generated: World) -> None:
    # An empty continuation changes nothing: every query answers as World does.
    log = EventLog(generated)
    poi = generated.pois[0]
    assert (log.at(poi.x, poi.y), log.of_realm(0), log.until(500)) == (
        generated.events_at(poi.x, poi.y),
        generated.events_of(0),
        generated.events_until(500),
    )
