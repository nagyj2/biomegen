"""Tests for the stored POI hooks: an event's text, or a template from the kind's row, with its name spans."""

from __future__ import annotations

import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.naming.hooks import describe_hook, describe_hooks, render_hook
from biomegen.pipeline.story.places import nearest_settlement
from biomegen.world.entities import POI, ChronicleEvent, FallenRealm
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
    # A town some realm holds: a free one would take its tier's free text.
    world.pois[0].realm_id = 0
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


# --- free settlements ----------------------------------------------------------------------------------------------
def _free_cfg(cfg: Config) -> Config:
    cfg.data["tables"]["tiers"]["town"].update(
        hooks_free=["{name} owes nothing to anyone."], hooks_remnant=["{name} outlived {fallen}."]
    )
    return cfg


def test_a_free_settlement_takes_a_free_text(world: World, cfg: Config) -> None:
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook == "Aldburg owes nothing to anyone."


def test_a_free_text_marks_the_settlement_name(world: World, cfg: Config) -> None:
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook_refs == [(0, 7, "poi", 0)]


def test_a_held_settlement_takes_no_free_text(world: World, cfg: Config) -> None:
    world.pois[0].realm_id = 0
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook == ""


def test_a_remnant_names_the_fallen_realm_it_outlived(world: World, cfg: Config) -> None:
    world.fallen_realms = [FallenRealm(id=0, location=(5, 5), founded=10, fell=200, name="Kingdom of Naesiael")]
    world.chronicle = [ChronicleEvent(0, 50, "settling", fallen_ids=[0], tags=("town", "free", "remnant"))]
    world.pois[0].event_ids = [0]
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook == "Aldburg outlived Kingdom of Naesiael."


def test_the_fallen_realm_in_a_hook_is_a_fallen_ref(world: World, cfg: Config) -> None:
    world.fallen_realms = [FallenRealm(id=0, location=(5, 5), founded=10, fell=200, name="Kingdom of Naesiael")]
    world.chronicle = [ChronicleEvent(0, 50, "settling", fallen_ids=[0], tags=("town", "free", "remnant"))]
    world.pois[0].event_ids = [0]
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook_refs[-1] == (17, 36, "fallen", 0)


def test_a_fallen_name_with_the_is_lowered_mid_sentence(world: World, cfg: Config) -> None:
    world.fallen_realms = [FallenRealm(id=0, location=(5, 5), founded=10, fell=200, name="The Than Republic")]
    world.chronicle = [ChronicleEvent(0, 50, "settling", fallen_ids=[0], tags=("town", "free", "remnant"))]
    world.pois[0].event_ids = [0]
    describe_hook(world, _free_cfg(cfg), 5, 0, -1)
    assert world.pois[0].hook == "Aldburg outlived the Than Republic."


def test_a_tier_with_no_free_text_falls_back_to_its_event_text(world: World, cfg: Config) -> None:
    del cfg.data["tables"]["tiers"]["town"]["hooks_free"]
    world.chronicle = [ChronicleEvent(0, 50, "settling", text="Aldburg is raised.", tags=("town", "free"))]
    world.pois[0].event_ids = [0]
    describe_hook(world, cfg, 5, 0, -1)
    assert world.pois[0].hook == "Aldburg is raised."


def test_render_hook_returns_what_describe_hook_stores(world: World, cfg: Config) -> None:
    # The pure helper and the writer agree, for a POI with no event and a near settlement.
    hook = render_hook(world, cfg, 5, world.pois[1], 1, 0)
    describe_hook(world, cfg, 5, 1, 0)
    assert hook == (world.pois[1].hook, world.pois[1].hook_refs)


def test_render_hook_writes_nothing_to_the_poi(world: World, cfg: Config) -> None:
    render_hook(world, cfg, 5, world.pois[1], 1, -1)
    assert (world.pois[1].hook, world.pois[1].hook_refs) == ("", [])


def test_render_hook_serves_a_poi_that_is_not_in_the_world_yet(world: World, cfg: Config) -> None:
    # A simulation renders the hook of a POI it mints before storing it; the index is the id it will have.
    minted = POI(kind="tower", x=3, y=3, interior_seed=0, name="New Tower")
    assert render_hook(world, cfg, 5, minted, 2, -1) == ("New Tower stands alone.", [(0, 9, "poi", 2)])


def test_every_hook_of_a_generated_world_is_what_render_hook_returns() -> None:
    # The naming stage stores render_hook's result, so the pure helper reproduces every stored hook.
    config = load_config(None)
    generated = pipeline.generate(config, 42)
    again = [
        render_hook(
            generated,
            config,
            42,
            poi,
            index,
            nearest_settlement(generated, config, poi.x, poi.y, (index,)),
        )
        for index, poi in enumerate(generated.pois)
    ]
    assert again == [(poi.hook, poi.hook_refs) for poi in generated.pois]
