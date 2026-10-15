"""Tests for values derived once from a world's arrays."""

from __future__ import annotations

from biomegen.world.derived import derived
from biomegen.world.world import World


def test_a_derived_value_is_built_once_while_its_source_is_unchanged() -> None:
    world = World(4, 3, 1)
    calls: list[int] = []

    def build() -> int:
        calls.append(1)
        return len(calls)

    assert (derived(world, "count", build, world.road), derived(world, "count", build, world.road)) == (1, 1)


def test_a_derived_value_is_rebuilt_when_its_source_changes() -> None:
    # A hand-made world edited in place gets a fresh value, never a stale one.
    world = World(4, 3, 1)
    first = derived(world, "roads", lambda: int(world.road.sum()), world.road)
    world.road[1, 1] = 1
    assert (first, derived(world, "roads", lambda: int(world.road.sum()), world.road)) == (0, 1)
