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
