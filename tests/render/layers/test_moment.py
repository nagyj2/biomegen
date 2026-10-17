"""Tests for drawing the political map at a past moment (``build_grid(..., moment=...)``)."""

from __future__ import annotations

import numpy as np

from biomegen.render.layers import build_grid, owner_palette_index
from biomegen.render.views import View
from biomegen.sampling.sampler import Sampler
from biomegen.world.entities import ChronicleEvent, FallenRealm, Predecessor, Realm
from biomegen.world.territory import WILD, TerritoryChange, fallen_owner, predecessor_owner
from biomegen.world.tile import Biome
from biomegen.world.world import World
from tests.render.conftest import make_world

POLITICAL = View("p", ("terrain", "tint", "borders"), "realm")
TINT_ONLY = View("p", ("terrain", "tint"), "realm")
RED, BLUE, GOLD = (200, 40, 40), (40, 40, 200), (200, 180, 40)


def _cells(*columns: int, rows: int = 2, width: int = 6) -> np.ndarray:
    return np.array(sorted(y * width + x for y in range(rows) for x in columns), dtype=np.int32)


def _world() -> World:
    """Realm 0 holds columns 0-2 today and realm 1 columns 3-5. Realm 1 was founded in year 100 on wild land; before
    that a fallen realm (founded 20, fell 100) held columns 3-4."""
    world = make_world(6, 2, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major", color=RED), Realm(id=1, kind="major", color=BLUE, liege=-1)]
    world.fallen_realms = [FallenRealm(id=0, location=(3, 0), founded=20, fell=100, color=GOLD)]
    world.realm_id[:, :3], world.realm_id[:, 3:] = 0, 1
    world.territory = [
        TerritoryChange(20, 1, "founding", _cells(3, 4), WILD, fallen_owner(0)),
        TerritoryChange(100, 1, "fall", _cells(3, 4), fallen_owner(0), WILD),
        TerritoryChange(100, 2, "founding", _cells(3, 4, 5), WILD, 1),
    ]
    return world


def _draw(world: World, config, moment=None, view: View = POLITICAL):
    return build_grid(world, config, view, Sampler.viewport(world, world.height, world.width), moment=moment)


def test_the_present_moment_draws_the_same_as_no_moment(config) -> None:
    world = _world()
    assert (_draw(world, config, (100, 2)).bg == _draw(world, config).bg).all()


def test_before_a_realm_exists_its_land_is_not_its_colour(config) -> None:
    world = _world()
    assert _draw(world, config, (150, 1)).bg[0, 5].tolist() != _draw(world, config, (50, 1)).bg[0, 5].tolist()


def test_a_fallen_realm_is_tinted_in_its_own_colour(config) -> None:
    # In year 50 columns 3-4 are the fallen realm's (gold); a realm's colour would be red or blue.
    world = _world()
    grid = _draw(world, config, (50, 1), TINT_ONLY)
    gold, red = grid.bg[0, 3].astype(int), grid.bg[0, 0].astype(int)
    assert gold[1] > gold[2] and gold[0] > red[2] and gold.tolist() != red.tolist()


def test_a_border_is_drawn_between_a_fallen_realm_and_its_neighbour(config) -> None:
    world = _world()
    changed = (_draw(world, config, (50, 1)).bg != _draw(world, config, (50, 1), TINT_ONLY).bg).any(axis=(0, 2))
    assert np.flatnonzero(changed).tolist() == [3, 4]  # the fallen realm borders realm 0 and the wild land beside it


def test_wild_land_in_the_past_is_flattened_like_wild_land_today(config) -> None:
    # Between the fall and the founding (year 100, month 1) the land is wild: grey, not any realm's colour.
    world = _world()
    wild = _draw(world, config, (100, 1), TINT_ONLY).bg[0, 3].astype(int)
    assert abs(int(wild[0]) - int(wild[1])) < 40 and abs(int(wild[1]) - int(wild[2])) < 40


def test_a_predecessor_has_its_own_palette_index() -> None:
    world = _world()
    world.predecessors = [Predecessor(id=0, founded=1, split_year=2)]
    codes = np.array([WILD, 0, 1, fallen_owner(0), predecessor_owner(0)])
    assert owner_palette_index(world, codes).tolist() == [-1, 0, 1, 2, 3]


def test_a_vassal_tie_counts_from_its_conquest() -> None:
    world = _world()
    world.realms[1].liege = 0
    world.chronicle = [ChronicleEvent(0, 150, "conquest", [1, 0], tags=("vassalage",), month=4)]
    assert (world.top_realm_at(1, 150, 3), world.top_realm_at(1, 150, 4), world.top_realm_at(1, 300)) == (1, 0, 0)


def test_a_vassal_with_no_conquest_event_is_independent_in_the_past() -> None:
    world = _world()
    world.realms[1].liege = 0
    assert world.top_realm_at(1, 300) == 1


# --- war fronts at a moment ---------------------------------------------------------------------------------------


def _war_world(config) -> World:
    """Realm 0 (columns 0-2) and realm 1 (columns 3-5) at war from year 100 to a peace in year 120."""
    world = make_world(6, 2, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major", color=RED), Realm(id=1, kind="major", color=BLUE)]
    world.realm_id[:, :3], world.realm_id[:, 3:] = 0, 1
    world.chronicle = [
        ChronicleEvent(0, 100, "war", [0, 1], tags=("ended",), month=1),
        ChronicleEvent(1, 120, "peace", [1, 0], month=1),
    ]
    world.territory = [TerritoryChange(50, 1, "founding", _cells(0, 1, 2, 3, 4, 5), WILD, 0)]
    return world


def _line(world: World, config, moment) -> list[int]:
    """The fill of the border cell (row 0, column 3) at ``moment``."""
    return _draw(world, config, moment).bg[0, 3].astype(int).tolist()


def test_a_border_at_war_is_reddened_at_that_moment(config) -> None:
    world = _war_world(config)
    during, before = _line(world, config, (110, 1)), _line(world, config, (90, 1))
    assert during[0] > before[0] and during[2] < before[2]


def test_a_border_after_the_peace_is_a_plain_border_again(config) -> None:
    world = _war_world(config)
    assert _line(world, config, (130, 1)) == _line(world, config, (90, 1))


# --- points of interest at a moment -------------------------------------------------------------------------------


def _poi_world() -> World:
    """Realm 0 holds the whole 6x2 world from year 50; a town founded in 100 and a ruin left by a fall in 200."""
    from biomegen.world.entities import POI

    world = make_world(6, 2, Biome.GRASS)
    world.realms = [Realm(id=0, kind="major", color=RED)]
    world.realm_id[:] = 0
    world.chronicle = [
        ChronicleEvent(0, 100, "settling", [0], [0], month=1),
        ChronicleEvent(1, 200, "fall", fallen_ids=[0], month=1),
    ]
    world.pois = [
        POI(kind="town", x=1, y=0, interior_seed=1, civilized=True, event_ids=[0], founded=100, realm_id=0),
        POI(kind="ruin", x=4, y=1, interior_seed=1, event_ids=[1], founded=20, fell=200),
    ]
    world.poi_index[0, 1], world.poi_index[1, 4] = 0, 1
    world.territory = [TerritoryChange(50, 1, "founding", _cells(0, 1, 2, 3, 4, 5), WILD, 0)]
    return world


def _glyphs(world: World, config, moment) -> list[str]:
    grid = build_grid(
        world,
        config,
        View("p", ("terrain", "markers"), ""),
        Sampler.viewport(world, world.height, world.width),
        moment=moment,
    )
    return [str(g) for g in grid.glyph[grid.bold]]  # markers are drawn bold


def test_a_town_is_not_drawn_before_it_is_founded(config) -> None:
    assert len(_glyphs(_poi_world(), config, (90, 1))) < len(_glyphs(_poi_world(), config, (110, 1)))


def test_a_ruin_is_drawn_only_after_the_fall(config) -> None:
    world = _poi_world()
    assert len(_glyphs(world, config, (150, 1))) == 1 and len(_glyphs(world, config, (200, 1))) == 2


def test_the_present_draws_every_poi(config) -> None:
    world = _poi_world()
    assert len(_glyphs(world, config, None)) == 2


def test_a_settlement_on_wild_land_then_is_drawn_as_a_free_one(config) -> None:
    from biomegen.render.layers import LayerContext

    world = _poi_world()
    sampler = Sampler.viewport(world, world.height, world.width)
    early = LayerContext(world, config, TINT_ONLY, sampler, moment=(40, 1))  # before realm 0 held anything
    late = LayerContext(world, config, TINT_ONLY, sampler, moment=(150, 1))
    assert (bool(early.held_pois[0]), bool(late.held_pois[0])) == (False, True)


# --- roads at a moment --------------------------------------------------------------------------------------------


def _road_world() -> World:
    """Two towns (founded 100 and 120) joined by a road along row 0, columns 1 to 4, laid in year 150."""
    from biomegen.world.entities import POI, RoadLink

    world = make_world(6, 2, Biome.GRASS)
    world.chronicle = [
        ChronicleEvent(0, 100, "settling", [], [0], month=1),
        ChronicleEvent(1, 120, "settling", [], [1], month=1),
        ChronicleEvent(2, 150, "road", poi_ids=[0, 1], month=1),
    ]
    world.pois = [
        POI(kind="town", x=1, y=0, interior_seed=1, civilized=True, event_ids=[0], founded=100),
        POI(kind="town", x=4, y=0, interior_seed=1, civilized=True, event_ids=[1], founded=120),
    ]
    world.road[0, 1:5] = 1
    world.road_links = [RoadLink(0, 1, 1, np.array([1, 2, 3, 4], dtype=np.int32), event_id=2)]
    return world


def _road_cells(world: World, config, moment) -> int:
    grid = build_grid(
        world,
        config,
        View("p", ("terrain", "roads"), ""),
        Sampler.viewport(world, world.height, world.width),
        moment=moment,
    )
    plain = build_grid(
        world, config, View("p", ("terrain",), ""), Sampler.viewport(world, world.height, world.width), moment=moment
    )
    return int((grid.glyph != plain.glyph).sum())


def test_a_road_is_not_drawn_before_it_is_laid(config) -> None:
    assert _road_cells(_road_world(), config, (140, 1)) == 0


def test_a_road_is_drawn_once_it_is_laid(config) -> None:
    assert _road_cells(_road_world(), config, (160, 1)) == 4


def test_the_present_draws_all_the_road(config) -> None:
    assert _road_cells(_road_world(), config, None) == 4


def test_a_road_waits_for_both_of_its_ends(config) -> None:
    world = _road_world()
    world.chronicle[2].year = 110  # laid before the second town was founded
    assert _road_cells(world, config, (115, 1)) == 0


# --- watchtowers over time ----------------------------------------------------------------------------------------


def _tower_world() -> World:
    """A watchtower raised in 100, abandoned at the peace of 120 and taken by bandits in 150 (a tower from then);
    another raised in 100 and dismantled in 120 (history only)."""
    from biomegen.world.entities import POI

    world = make_world(8, 2, Biome.GRASS)
    world.chronicle = [
        ChronicleEvent(0, 100, "war", [0, 1], month=1),
        ChronicleEvent(1, 120, "peace", [0, 1], month=1),
        ChronicleEvent(2, 150, "occupation", poi_ids=[0], month=1),
        ChronicleEvent(3, 100, "creation", poi_ids=[0], month=1),
    ]
    taken = POI(kind="tower", x=2, y=0, interior_seed=1, event_ids=[0, 1, 2, 3], founded=100)
    taken.extra.update({"fate": "occupied", "taken": 150})
    gone = POI(kind="watchtower", x=5, y=1, interior_seed=1, event_ids=[0, 1], founded=100, fell=120)
    gone.extra.update({"fate": "dismantled", "taken": 0})
    world.pois, world.vanished = [taken], [gone]
    world.poi_index[0, 2] = 0
    return world


def _marker_glyphs(world: World, config, moment) -> list[str]:
    grid = build_grid(
        world,
        config,
        View("p", ("terrain", "markers"), ""),
        Sampler.viewport(world, world.height, world.width),
        moment=moment,
    )
    return [str(g) for g in grid.glyph[grid.bold]]


def test_a_tower_bandits_took_is_a_watchtower_until_they_did(config) -> None:
    from biomegen.render.poi_style import poi_marker

    world = _tower_world()
    watch, tower = poi_marker(config, "watchtower")[0], poi_marker(config, "tower")[0]
    assert (_marker_glyphs(world, config, (110, 1))[0], _marker_glyphs(world, config, (160, 1))[0]) == (watch, tower)


def test_a_dismantled_watchtower_stands_only_until_the_peace(config) -> None:
    world = _tower_world()
    counts = [len(_marker_glyphs(world, config, moment)) for moment in ((90, 1), (110, 1), (125, 1))]
    assert counts == [0, 2, 1]


def test_the_present_does_not_draw_what_has_vanished(config) -> None:
    assert len(_marker_glyphs(_tower_world(), config, None)) == 1
