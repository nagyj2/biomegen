"""Tests for the explorer's event reader."""

from __future__ import annotations

from biomegen.explorer.events import ChronicleReader
from biomegen.world.entities import ChronicleEvent, Realm
from biomegen.world.ledger import EventLog
from biomegen.world.world import World


def _world() -> World:
    world = World(4, 4, 9)
    world.realms = [Realm(id=0, kind="major")]
    world.chronicle = [ChronicleEvent(0, 100, "founding", [0], month=2)]
    return world


def test_the_reader_answers_from_the_generated_chronicle_by_default() -> None:
    assert [event.kind for event in ChronicleReader(_world()).of_realm(0)] == ["founding"]


def test_the_reader_also_answers_from_the_continuation_of_the_log_it_is_given() -> None:
    world = _world()
    log = EventLog(world, [ChronicleEvent(-1, 200, "treaty", [0], month=1)])
    assert [event.kind for event in ChronicleReader(world, log).of_realm(0)] == ["founding", "treaty"]
