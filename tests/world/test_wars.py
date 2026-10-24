"""Tests for which wars were being fought at a moment (``world/wars.py``)."""

from __future__ import annotations

from biomegen.world.entities import ChronicleEvent, Realm
from biomegen.world.wars import war_intervals, wars_at
from biomegen.world.world import World


def _world(*events: ChronicleEvent) -> World:
    world = World(4, 4, 1)
    world.realms = [Realm(id=i, kind="major") for i in range(4)]
    world.chronicle = list(events)
    return world


def _event(year: int, kind: str, realms: list[int], *tags: str, month: int = 1, fallen: list[int] | None = None):
    return ChronicleEvent(0, year, kind, realms, fallen_ids=fallen or [], tags=tags, month=month)


def test_an_ongoing_war_never_ends() -> None:
    world = _world(_event(100, "war", [0, 1], "ongoing"))
    assert war_intervals(world) == [(0, 1, (100, 1), None)]


def test_an_older_war_ends_at_its_peace() -> None:
    world = _world(_event(100, "war", [0, 1], "ended"), _event(120, "peace", [1, 0], month=6))
    assert war_intervals(world) == [(0, 1, (100, 1), (120, 6))]


def test_a_conquest_war_ends_at_the_conquest() -> None:
    world = _world(_event(100, "war", [0, 1], "conquest"), _event(110, "conquest", [1, 0], "vassalage", month=3))
    assert war_intervals(world) == [(0, 1, (100, 1), (110, 3))]


def test_a_peace_of_another_pair_does_not_end_the_war() -> None:
    world = _world(_event(100, "war", [0, 1], "ended"), _event(110, "peace", [2, 3]))
    assert war_intervals(world)[0][3] is None


def test_wars_at_a_moment_are_those_begun_and_not_yet_ended() -> None:
    world = _world(_event(100, "war", [0, 1], "ended"), _event(120, "peace", [1, 0], month=6))
    assert (wars_at(world, (99, 12)), wars_at(world, (100, 1)), wars_at(world, (120, 5)), wars_at(world, (120, 6))) == (
        [],
        [(0, 1)],
        [(0, 1)],
        [],
    )


def test_a_war_with_a_fallen_realm_is_not_listed() -> None:
    world = _world(_event(100, "war", [0], "ended", fallen=[0]))
    assert war_intervals(world) == []


def test_each_war_of_a_pair_ends_at_its_own_peace() -> None:
    # Two wars of one pair: the first ends at the first peace, the second at the second.
    world = _world(
        _event(100, "war", [0, 1], "ended"),
        _event(120, "peace", [1, 0]),
        _event(150, "war", [1, 0], "ended"),
        _event(170, "peace", [0, 1]),
        _event(200, "war", [0, 1], "ongoing"),
    )
    assert [end for *_, end in war_intervals(world)] == [(120, 1), (170, 1), None]
