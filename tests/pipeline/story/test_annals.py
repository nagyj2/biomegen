"""Tests for the annals: the minor events of towers, dungeons and the founding of villages and hamlets."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.pipeline.story.ledger import merge_events
from biomegen.world.chronicle import ChronicleFilter, filter_events
from biomegen.world.entities import POI, ChronicleEvent
from biomegen.world.territory import WILD, TerritoryChange
from biomegen.world.world import World


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module", params=(42, 7))
def world(request: pytest.FixtureRequest, cfg: Config) -> World:
    return pipeline.generate(cfg, request.param)


def _towers_and_dungeons(world: World):
    return [(i, p) for i, p in enumerate(world.pois) if p.kind in ("tower", "dungeon")]


def _creation(world: World, index: int):
    return [e for e in world.chronicle if e.kind == "creation" and e.poi_ids == [index]]


def test_every_tower_and_dungeon_has_one_minor_creation_event(world: World) -> None:
    for index, _poi in _towers_and_dungeons(world):
        (event,) = _creation(world, index)
        assert event.salience == "minor"


def test_a_tower_is_linked_to_its_creation(world: World) -> None:
    for index, poi in _towers_and_dungeons(world):
        (event,) = _creation(world, index)
        assert event.id in poi.event_ids


def test_a_tower_made_by_a_fall_is_created_no_sooner_than_the_fall(world: World) -> None:
    for index, poi in _towers_and_dungeons(world):
        falls = [world.chronicle[i] for i in poi.event_ids if world.chronicle[i].kind == "fall"]
        if falls:
            (event,) = _creation(world, index)
            assert (event.year, event.month) >= (falls[0].year, falls[0].month) and event.year == falls[0].year


def test_a_tower_placed_by_location_is_ancient_or_made_inside_the_history(world: World) -> None:
    for index, poi in _towers_and_dungeons(world):
        if not any(world.chronicle[i].kind == "fall" for i in poi.event_ids):
            (event,) = _creation(world, index)
            assert 0 <= event.year <= world.year and poi.founded == event.year


def test_some_towers_are_ancient_and_some_are_made_in_the_history(cfg: Config) -> None:
    years = [e.year for seed in (42, 7, 1337) for e in pipeline.generate(cfg, seed).chronicle if e.kind == "creation"]
    assert 0 in years and any(year > 0 for year in years)


def test_every_village_and_hamlet_has_a_founding_or_settling_event_in_its_founding_year(world: World) -> None:
    for index, poi in enumerate(world.pois):
        if poi.kind in ("village", "hamlet"):
            events = [e for e in world.chronicle if e.kind in ("founding", "settling") and index in e.poi_ids]
            assert events and events[0].year == poi.founded


def test_the_chronicle_stays_sorted_and_numbered_after_the_annals(world: World) -> None:
    moments = [(e.year, e.month) for e in world.chronicle]
    assert moments == sorted(moments) and [e.id for e in world.chronicle] == list(range(len(world.chronicle)))


def test_a_poi_event_link_names_the_poi_or_its_fallen_realm(world: World) -> None:
    for index, poi in enumerate(world.pois):
        for event_id in poi.event_ids:
            event = world.chronicle[event_id]
            assert index in event.poi_ids or event.fallen_ids or event.realm_ids or event.location == (poi.x, poi.y)


def test_every_territory_change_still_names_its_event(world: World) -> None:
    for change in world.territory:
        event = world.chronicle[change.event_id]
        assert (event.year, event.month) == change.moment


def test_minor_events_leave_no_token_in_their_text(world: World) -> None:
    assert all("{" not in e.text for e in world.chronicle)


def test_the_default_listing_leaves_the_minor_events_out(world: World) -> None:
    shown = filter_events(world, ChronicleFilter())
    assert len(shown) < len(world.chronicle) and all(e.salience == "major" for e in shown)


# --- merging events into a finished chronicle ----------------------------------------------------------------------


def _merge_world() -> World:
    world = World(4, 2, 1)
    world.chronicle = [
        ChronicleEvent(0, 10, "founding", month=2),
        ChronicleEvent(1, 10, "war", month=9),
        ChronicleEvent(2, 20, "fall", month=1),
    ]
    world.pois = [POI(kind="ruin", x=0, y=0, interior_seed=1, event_ids=[2])]
    world.territory = [TerritoryChange(10, 9, "battle", np.array([1], dtype=np.int32), WILD, 0, event_id=1)]
    return world


def test_new_events_slot_in_by_moment_and_everything_is_renumbered() -> None:
    world = _merge_world()
    new = [ChronicleEvent(-1, 10, "creation", month=5), ChronicleEvent(-1, 5, "creation", month=12)]
    merge_events(world, new, 12)
    assert [(e.year, e.month) for e in world.chronicle] == [(5, 12), (10, 2), (10, 5), (10, 9), (20, 1)]
    assert [e.id for e in world.chronicle] == [0, 1, 2, 3, 4]


def test_a_new_event_of_the_same_month_goes_after_the_old_one() -> None:
    world = _merge_world()
    merge_events(world, [ChronicleEvent(-1, 10, "creation", month=9)], 12)
    assert [e.kind for e in world.chronicle][1:3] == ["war", "creation"]


def test_the_ids_the_world_keeps_follow_the_renumbering() -> None:
    world = _merge_world()
    merge_events(world, [ChronicleEvent(-1, 5, "creation", month=1), ChronicleEvent(-1, 10, "creation", month=5)], 12)
    assert world.chronicle[world.pois[0].event_ids[0]].kind == "fall"
    assert world.chronicle[world.territory[0].event_id].kind == "war"


# --- roads ----------------------------------------------------------------------------------------------------------


def test_the_road_links_cover_exactly_the_road_tiles(world: World) -> None:
    covered = np.zeros(world.road.shape, dtype=bool)
    for link in world.road_links:
        covered.reshape(-1)[link.cells] = True
    assert np.array_equal(covered, world.road > 0)


def test_every_road_link_has_one_minor_road_event(world: World) -> None:
    for link in world.road_links:
        event = world.chronicle[link.event_id]
        assert event.kind == "road" and event.salience == "minor"
    assert len({link.event_id for link in world.road_links}) == len(world.road_links)


def test_a_road_is_laid_after_both_its_ends_stand(world: World, cfg: Config) -> None:
    from biomegen.world.lifespans import poi_appears

    for link in world.road_links:
        event = world.chronicle[link.event_id]
        for end in (link.a, link.b):
            if end >= 0:
                appears = poi_appears(world, cfg, end)
                assert appears is None or appears <= (event.year, event.month)


def test_a_trunk_road_joins_two_places_and_a_spur_one(world: World) -> None:
    for link in world.road_links:
        assert len(world.chronicle[link.event_id].poi_ids) == (2 if link.b >= 0 else 1)


def test_road_events_name_their_places(world: World) -> None:
    for link in world.road_links:
        text = world.chronicle[link.event_id].text
        assert world.pois[link.a].name in text and "{" not in text


def test_the_road_links_keep_their_events_through_the_merges(world: World) -> None:
    for link in world.road_links:
        assert world.chronicle[link.event_id].id == link.event_id


# --- the land comes first ---------------------------------------------------------------------------------------


def test_a_settlement_is_founded_no_sooner_than_its_land_was_taken_from_the_wild(world: World) -> None:
    from biomegen.world.territory import wild_since

    since = wild_since(world.territory, world.height, world.width)
    seats = {r.seat_poi for r in world.realms}
    defected = {i for e in world.chronicle if "defection" in e.tags for i in e.poi_ids}  # settled for another realm
    for index, poi in enumerate(world.pois):
        if poi.civilized and poi.realm_id >= 0 and index not in seats | defected:
            assert poi.founded >= since[poi.y, poi.x], (poi.kind, index)


def test_a_settling_event_is_dated_by_the_founding_of_its_settlement(world: World) -> None:
    for event in world.chronicle:
        if event.kind == "settling" and event.realm_ids and len(event.poi_ids) == 1:
            poi = world.pois[event.poi_ids[0]]
            assert event.year == poi.founded or poi.realm_id != event.realm_ids[0]


def test_a_hamlet_or_homestead_is_founded_no_sooner_than_its_land(world: World) -> None:
    from biomegen.world.territory import wild_since

    since = wild_since(world.territory, world.height, world.width)
    for poi in world.pois:
        if poi.realm_id >= 0 and poi.kind in ("hamlet", "homestead") and poi.founded > 0:
            assert poi.founded >= since[poi.y, poi.x]


# --- the life of a watchtower ---------------------------------------------------------------------------------------


def _watchtowers(world: World):
    return [(i, p) for i, p in enumerate((*world.pois, *world.vanished)) if p.extra.get("fate")]


def _events_about(world: World, index: int, kind: str):
    return [e for e in world.chronicle if e.kind == kind and e.poi_ids == [index]]


def test_every_watchtower_is_raised_with_its_war(world: World) -> None:
    for index, poi in _watchtowers(world):
        (created,) = _events_about(world, index, "creation")
        war = world.chronicle[poi.event_ids[0]]
        assert (
            war.kind == "war" and (created.year, created.month) == (war.year, war.month) and created.salience == "minor"
        )


def test_a_watchtower_not_standing_has_its_end_told_at_the_peace(world: World) -> None:
    for index, poi in _watchtowers(world):
        ended = _events_about(world, index, "abandon")
        if poi.extra["fate"] == "standing":
            assert not ended
        else:
            (event,) = ended
            peace = world.chronicle[poi.event_ids[1]]
            assert (event.year, event.month) == (peace.year, peace.month)


def test_bandits_take_an_abandoned_watchtower_after_the_peace(world: World) -> None:
    for index, poi in _watchtowers(world):
        taken = _events_about(world, index, "occupation")
        if poi.extra["fate"] == "occupied":
            (event,) = taken
            assert event.year == poi.extra["taken"] and event.year > world.chronicle[poi.event_ids[1]].year
        else:
            assert not taken


def test_a_dismantled_watchtowers_events_name_it(world: World) -> None:
    for index, poi in enumerate(world.vanished, start=len(world.pois)):
        assert all(poi.name in e.text for e in world.chronicle if e.poi_ids == [index])


# --- camps and boats ------------------------------------------------------------------------------------------------


def _camps(world: World):
    return [(i, p) for i, p in enumerate(world.pois) if p.kind == "camp"]


def test_every_camp_has_one_minor_creation_event(world: World) -> None:
    assert _camps(world)
    for index, _poi in _camps(world):
        (event,) = _creation(world, index)
        assert event.salience == "minor"


def test_a_camp_is_made_by_the_realm_that_held_the_land_then(world: World) -> None:
    from biomegen.world.territory import WILD

    for index, poi in _camps(world):
        (event,) = _creation(world, index)
        owner = int(world.owners_at(event.year, event.month)[poi.y, poi.x])
        assert event.realm_ids == ([owner] if owner >= 0 else []) and (owner >= 0 or owner == WILD or owner < 0)


def test_a_camps_text_names_its_place_and_its_realm(world: World) -> None:
    for index, poi in _camps(world):
        (event,) = _creation(world, index)
        assert poi.name in event.text and "{" not in event.text
        if event.realm_ids:
            assert world.realms[event.realm_ids[0]].short in event.text


def test_no_boat_is_placed(world: World) -> None:
    assert not [p for p in world.pois if p.kind == "boat"]


def test_the_boat_row_is_kept_but_switched_off(cfg: Config) -> None:
    assert cfg.get("tables.pois.boat.generated") is False and cfg.get("tables.pois.boat.km2_per_poi") > 0


def test_a_spur_is_never_laid_before_the_road_it_runs_into(world: World) -> None:
    spurs = [link for link in world.road_links if link.joins >= 0]
    assert spurs
    for link in spurs:
        joined, event, parent = world.road_links[link.joins], world.chronicle[link.event_id], None
        parent = world.chronicle[joined.event_id]
        assert (parent.year, parent.month, parent.id) <= (event.year, event.month, event.id)


def test_a_spur_runs_into_a_road_that_has_the_cell_it_ends_on(world: World) -> None:
    width = world.width
    for link in (item for item in world.road_links if item.joins >= 0):
        joined = set(world.road_links[link.joins].cells.tolist())
        assert joined & set(link.cells.tolist()) and all(c < world.width * world.height for c in joined)
        assert width > 0


def test_a_merged_event_gets_the_tick_of_its_moment() -> None:
    world = _merge_world()
    merge_events(world, [ChronicleEvent(-1, 10, "creation", month=5)], 12)
    assert [e.tick for e in world.chronicle if e.kind == "creation"] == [10 * 12 + 5 - 1]
