"""Tests for the explorer's view state, camera, cursor and floor rules."""

from __future__ import annotations

import pytest

from biomegen.config.model import Config
from biomegen.explorer.state import (
    MODE_FIT,
    MODE_ONE_TO_ONE,
    ViewState,
    clamp,
    cycle_floor,
    edge_pan,
    initial_cursor,
    move_cursor,
    poi_under_cursor,
    step_in,
    step_out,
    sync_floor,
    toggle_mode,
)
from biomegen.render.detail import SCALE_LOCAL, SCALE_MAP, SCALE_ZOOM
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from tests.render.conftest import make_world


def _tower_world():
    """A 20 x 20 world with a two-floor tower whose 3 x 3 footprint covers tiles 9-11."""
    world = make_world(20, 20, Biome.GRASS)
    world.pois.append(POI(kind="tower", x=10, y=10, interior_seed=3, footprint=(3, 3), floor_count=2))
    return world


def test_clamp_keeps_a_value_in_range() -> None:
    assert (clamp(-3, 0, 5), clamp(9, 0, 5), clamp(2, 0, 5)) == (0, 5, 2)


def test_clamp_with_an_empty_range_gives_the_low_bound() -> None:
    assert clamp(4, 3, 1) == 3


def test_camera_holds_still_while_the_cursor_is_inside() -> None:
    assert edge_pan(10, 15, 20, 100) == 10


def test_camera_scrolls_when_the_cursor_reaches_the_right_edge() -> None:
    assert edge_pan(10, 29, 20, 100) == 11


def test_camera_scrolls_when_the_cursor_reaches_the_left_edge() -> None:
    assert edge_pan(10, 10, 20, 100) == 9


def test_camera_stays_inside_the_world() -> None:
    assert edge_pan(78, 99, 20, 100) == 80


def test_a_world_smaller_than_the_viewport_is_centred() -> None:
    assert edge_pan(0, 3, 20, 10) == -5


def test_message_log_keeps_only_the_latest() -> None:
    state = ViewState()
    for number in range(12):
        state.notify(str(number))
    assert (len(state.messages), state.last_message) == (8, "11")


def test_detail_flag_follows_the_scale() -> None:
    assert (ViewState().is_detail, ViewState(scale=SCALE_ZOOM).is_detail) == (False, True)


def test_zoom_key_steps_out_one_scale() -> None:
    # map -> zoom, zoom -> map, local -> zoom.
    scales = []
    for start in (SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL):
        state = ViewState(scale=start)
        step_out(state)
        scales.append(state.scale)
    assert scales == [SCALE_ZOOM, SCALE_MAP, SCALE_ZOOM]


def test_local_key_steps_in_one_scale() -> None:
    # map -> zoom, zoom -> local, local stays.
    scales = []
    for start in (SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL):
        state = ViewState(scale=start)
        step_in(state)
        scales.append(state.scale)
    assert scales == [SCALE_ZOOM, SCALE_LOCAL, SCALE_LOCAL]


def test_changing_scale_asks_for_a_recentre() -> None:
    state = ViewState()
    step_in(state)
    assert state.recenter


def test_fit_and_one_to_one_toggle() -> None:
    state = ViewState()
    toggle_mode(state)
    assert (state.mode, state.recenter) == (MODE_ONE_TO_ONE, True)


def test_toggle_back_to_fit() -> None:
    state = ViewState(mode=MODE_ONE_TO_ONE)
    toggle_mode(state)
    assert state.mode == MODE_FIT


def test_toggle_is_refused_at_detail_scale() -> None:
    state = ViewState(scale=SCALE_ZOOM)
    toggle_mode(state)
    assert (state.mode, "map only" in state.last_message) == (MODE_FIT, True)


def test_cursor_stops_at_the_world_edge() -> None:
    world = make_world(5, 4)
    state = ViewState(cx=4, cy=0)
    move_cursor(world, state, 3, -3)
    assert (state.cx, state.cy) == (4, 0)


def test_cursor_moves_by_the_step() -> None:
    world = make_world(10, 10)
    state = ViewState(cx=2, cy=2)
    move_cursor(world, state, 3, 1)
    assert (state.cx, state.cy) == (5, 3)


def test_initial_cursor_prefers_a_poi_on_land(config: Config) -> None:
    world = make_world(30, 20, Biome.GRASS)
    world.poi_index[4, 25] = 0
    assert initial_cursor(world, config) == (25, 4)


def test_initial_cursor_avoids_open_water(config: Config) -> None:
    world = make_world(10, 10, Biome.DEEP, -2000.0)
    world.water_type[:] = int(WaterType.SALT)
    world.biome[2:5, 2:5] = int(Biome.GRASS)
    world.water_type[2:5, 2:5] = int(WaterType.NONE)
    x, y = initial_cursor(world, config)
    assert 2 <= x < 5 and 2 <= y < 5


def test_initial_cursor_on_a_world_without_land_is_the_centre(config: Config) -> None:
    world = make_world(10, 6, Biome.DEEP, -2000.0)
    world.water_type[:] = int(WaterType.SALT)
    assert initial_cursor(world, config) == (5, 3)


def test_structure_under_the_cursor_covers_its_whole_footprint() -> None:
    world = _tower_world()
    assert poi_under_cursor(world, ViewState(cx=11, cy=9)) is world.pois[0]


def test_no_structure_outside_the_footprint() -> None:
    assert poi_under_cursor(_tower_world(), ViewState(cx=12, cy=10)) is None


def test_entering_a_structure_starts_on_the_ground_floor() -> None:
    world = _tower_world()
    state = ViewState(cx=10, cy=10, floor=1)
    sync_floor(world, state, None)
    assert state.floor == 0


def test_moving_within_a_structure_keeps_the_floor() -> None:
    world = _tower_world()
    state = ViewState(cx=10, cy=10)
    tracking = sync_floor(world, state, None)
    state.floor = 1
    state.cx = 11
    sync_floor(world, state, tracking)
    assert state.floor == 1


def test_leaving_every_structure_resets_the_floor() -> None:
    world = _tower_world()
    state = ViewState(cx=10, cy=10)
    tracking = sync_floor(world, state, None)
    state.floor, state.cx = 1, 2
    sync_floor(world, state, tracking)
    assert state.floor == 0


def test_floor_cycles_up_and_stops_at_the_top() -> None:
    world = _tower_world()
    state = ViewState(cx=10, cy=10)
    cycle_floor(world, state, 1)
    cycle_floor(world, state, 1)
    assert (state.floor, "no further floor" in state.last_message) == (1, True)


def test_cycling_off_a_structure_explains_itself() -> None:
    state = ViewState(cx=0, cy=0)
    cycle_floor(_tower_world(), state, 1)
    assert "no interior here" in state.last_message


@pytest.mark.parametrize("delta", [1, -1])
def test_single_floor_structure_cannot_change_floor(delta: int) -> None:
    world = make_world(10, 10)
    world.pois.append(POI(kind="camp", x=5, y=5, interior_seed=1, footprint=(2, 2), floor_count=1))
    state = ViewState(cx=5, cy=5)
    cycle_floor(world, state, delta)
    assert (state.floor, "single floor" in state.last_message) == (0, True)
