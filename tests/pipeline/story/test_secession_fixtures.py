"""Tests that the fixture seeds 11 and 15 keep the secessions they were added for, at the default chance."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.world.world import World


@pytest.fixture(scope="module")
def seed_11() -> World:
    return pipeline.generate(load_config(None), 11)


@pytest.fixture(scope="module")
def seed_15() -> World:
    return pipeline.generate(load_config(None), 15)


def test_seed_11_holds_a_defection(seed_11: World) -> None:
    assert [e for e in seed_11.chronicle if e.kind == "secession" and "defection" in e.tags]


def test_seed_15_holds_an_offshoot(seed_15: World) -> None:
    assert [r for r in seed_15.realms if r.origin == "offshoot"]


def test_the_two_fixtures_hold_two_different_kinds_of_secession(seed_11: World, seed_15: World) -> None:
    kinds = {
        "defection" if "defection" in e.tags else "offshoot"
        for world in (seed_11, seed_15)
        for e in world.chronicle
        if e.kind == "secession"
    }
    assert kinds == {"defection", "offshoot"}
