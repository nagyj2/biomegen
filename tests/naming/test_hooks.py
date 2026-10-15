"""Tests for the stored POI hooks: an event's text, or a template from the kind's row, with its name spans."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.naming.hooks import describe_hook, describe_hooks
from biomegen.world.entities import POI, ChronicleEvent
from biomegen.world.world import World


@pytest.fixture()
def cfg() -> Config:
    config = load_config(None)
    config.data["tables"]["pois"]["tower"].update(hooks=["{name} stands alone."], hooks_near=["{name} watches {near}."])
    return config


@pytest.fixture()
def world() -> World:
    made = World(10, 10, 1)
    made.pois = [
        POI(kind="town", x=1, y=1, interior_seed=0, civilized=True, name="Aldburg"),
        POI(kind="tower", x=7, y=7, interior_seed=0, name="Dest Tower"),
    ]
    return made


def test_a_poi_an_event_made_takes_the_event_text(world: World, cfg: Config) -> None:
    world.chronicle = [ChronicleEvent(0, 40, "battle", text="A battle was fought.", refs=[(2, 8, "realm", 1)])]
    world.pois[1].event_ids = [0]
    describe_hook(world, cfg, 5, 1, -1)
    assert (world.pois[1].hook, world.pois[1].hook_refs) == ("A battle was fought.", [(2, 8, "realm", 1)])


def test_the_hook_refs_are_a_copy_of_the_events(world: World, cfg: Config) -> None:
    world.chronicle = [ChronicleEvent(0, 40, "battle", text="A battle.", refs=[(2, 8, "realm", 1)])]
    world.pois[1].event_ids = [0]
    describe_hook(world, cfg, 5, 1, -1)
    world.pois[1].hook_refs.clear()
    assert world.chronicle[0].refs == [(2, 8, "realm", 1)]


def test_a_poi_with_no_event_takes_its_rows_template(world: World, cfg: Config) -> None:
    describe_hook(world, cfg, 5, 1, -1)
    assert world.pois[1].hook == "Dest Tower stands alone."


def test_the_name_in_a_hook_is_marked_as_the_poi(world: World, cfg: Config) -> None:
    describe_hook(world, cfg, 5, 1, -1)
    assert world.pois[1].hook_refs == [(0, 10, "poi", 1)]


def test_a_near_template_names_the_settlement_when_one_qualifies(world: World, cfg: Config) -> None:
    cfg.data["tables"]["pois"]["tower"]["hooks"] = []
    describe_hook(world, cfg, 5, 1, 0)
    assert world.pois[1].hook == "Dest Tower watches Aldburg."


def test_a_near_settlement_is_marked_in_the_hook(world: World, cfg: Config) -> None:
    cfg.data["tables"]["pois"]["tower"]["hooks"] = []
    describe_hook(world, cfg, 5, 1, 0)
    text, refs = world.pois[1].hook, world.pois[1].hook_refs
    assert [(text[a:b], kind, ident) for a, b, kind, ident in refs] == [("Dest Tower", "poi", 1), ("Aldburg", "poi", 0)]


def test_a_near_template_is_never_used_without_a_settlement(world: World, cfg: Config) -> None:
    cfg.data["tables"]["pois"]["tower"]["hooks"] = []
    describe_hook(world, cfg, 5, 1, -1)
    assert world.pois[1].hook == ""


def test_a_kind_with_no_row_has_an_empty_hook(world: World, cfg: Config) -> None:
    describe_hook(world, cfg, 5, 0, -1)
    assert world.pois[0].hook == ""


def test_describing_a_hook_twice_gives_the_same_hook(world: World, cfg: Config) -> None:
    describe_hook(world, cfg, 5, 1, 0)
    first = (world.pois[1].hook, list(world.pois[1].hook_refs))
    describe_hook(world, cfg, 5, 1, 0)
    assert (world.pois[1].hook, world.pois[1].hook_refs) == first


def test_describe_hooks_asks_for_each_pois_near_settlement(world: World, cfg: Config) -> None:
    cfg.data["tables"]["pois"]["tower"]["hooks"] = []
    describe_hooks(world, cfg, 5, lambda index: 0 if index == 1 else -1)
    assert world.pois[1].hook == "Dest Tower watches Aldburg."
