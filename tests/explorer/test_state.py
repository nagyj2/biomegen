"""Tests for the explorer's view state, camera, cursor and floor rules."""

from __future__ import annotations

import pytest

from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.state import (
    MODE_FIT,
    MODE_ONE_TO_ONE,
    PAN_CENTRE,
    PAN_EDGE,
    ViewState,
    clamp,
    cycle_floor,
    edge_pan,
    initial_cursor,
    move_cursor,
    pan,
    poi_under_cursor,
    step_in,
    step_out,
    sync_floor,
    toggle_mode,
)
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_MAP, SCALE_SITE, SCALE_ZOOM
from biomegen.sites import site_geometry
from biomegen.world.entities import POI
from biomegen.world.tile import Biome, WaterType
from tests.render.conftest import make_world


@pytest.fixture(scope="module")
def site_config() -> Config:
    """Defaults with the extent jitter off, so a site covers its nominal tiles."""
    config = load_config(None)
    config.data["sites"]["size_jitter"] = 0.0
    config.data["sites"]["pop_scale"] = [1.0, 1.0]
    return config


def _tower_world():
    """A 20 x 20 world with a two-floor tower at (10, 10): half a tile, so it covers only its own tile."""
    world = make_world(20, 20, Biome.GRASS)
    world.pois.append(POI(kind="tower", x=10, y=10, interior_seed=3, floor_count=2))
    return world


def _dungeon_world():
    """A 20 x 20 world with a two-floor dungeon at (10, 10): 1.5 x 1.0 tiles, so it covers tiles 9-11 across."""
    world = make_world(20, 20, Biome.GRASS)
    world.pois.append(POI(kind="dungeon", x=10, y=10, interior_seed=3, floor_count=2, lowest_floor=-1))
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


def test_centre_panning_holds_still_inside_the_margin() -> None:
    assert pan(10, 15, 20, 100, 1, PAN_CENTRE) == 10


def test_centre_panning_jumps_half_a_screen_at_the_edge() -> None:
    # The cursor at the right margin (29) is re-centred: the camera moves 9 tiles, not 1.
    assert pan(10, 29, 20, 100, 1, PAN_CENTRE) == 19


def test_centre_panning_stays_inside_the_world() -> None:
    assert pan(78, 99, 20, 100, 1, PAN_CENTRE) == 80


def test_edge_panning_steps_like_edge_pan() -> None:
    assert pan(10, 29, 20, 100, 1, PAN_EDGE) == edge_pan(10, 29, 20, 100)


def test_message_log_keeps_only_the_latest() -> None:
    state = ViewState()
    for number in range(12):
        state.notify(str(number))
    assert (len(state.messages), state.last_message) == (8, "11")


def test_detail_flag_follows_the_scale() -> None:
    assert (ViewState().is_detail, ViewState(scale=SCALE_ZOOM).is_detail) == (False, True)


def test_zoom_key_steps_out_one_scale() -> None:
    # map -> zoom, zoom -> map, local -> zoom, site -> zoom.
    scales = []
    for start in (SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL, SCALE_SITE):
        state = ViewState(scale=start)
        step_out(state)
        scales.append(state.scale)
    assert scales == [SCALE_ZOOM, SCALE_MAP, SCALE_ZOOM, SCALE_ZOOM]


def test_local_key_steps_in_one_scale_away_from_a_poi(site_config: Config) -> None:
    # Off any POI: map -> zoom, zoom -> local, local stays.
    world = make_world(20, 20, Biome.GRASS)
    scales = []
    for start in (SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL):
        state = ViewState(scale=start, cx=3, cy=3)
        step_in(world, site_config, state)
        scales.append(state.scale)
    assert scales == [SCALE_ZOOM, SCALE_LOCAL, SCALE_LOCAL]


def test_zooming_in_on_a_poi_opens_its_site(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_ZOOM, cx=10, cy=10)
    step_in(world, site_config, state)
    assert state.scale == SCALE_SITE and state.poi is world.pois[0]


def test_the_site_cursor_starts_on_the_anchor_cell(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_ZOOM, cx=10, cy=10)
    step_in(world, site_config, state)
    geometry = site_geometry(world.pois[0], site_config)
    assert geometry is not None and (state.px, state.py) == geometry.cell_at(10, 10)


def test_the_local_key_on_a_poi_at_local_scale_opens_its_site(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_LOCAL, cx=11, cy=10)
    step_in(world, site_config, state)
    assert state.scale == SCALE_SITE


def test_the_local_key_inside_a_site_does_nothing(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_ZOOM, cx=10, cy=10)
    step_in(world, site_config, state)
    before = (state.px, state.py)
    step_in(world, site_config, state)
    assert state.scale == SCALE_SITE and (state.px, state.py) == before


def test_stepping_out_of_a_site_closes_it(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_ZOOM, cx=10, cy=10)
    step_in(world, site_config, state)
    step_out(state)
    assert state.scale == SCALE_ZOOM and state.poi is None and state.recenter


def test_zooming_in_beside_a_sub_tile_poi_goes_to_local(site_config: Config) -> None:
    # A tower covers only its own tile, so the tile beside it opens no site.
    world = _tower_world()
    state = ViewState(scale=SCALE_ZOOM, cx=11, cy=10)
    step_in(world, site_config, state)
    assert state.scale == SCALE_LOCAL


def _open(site_config: Config) -> tuple:
    world = _dungeon_world()
    state = ViewState(scale=SCALE_ZOOM, cx=10, cy=10)
    step_in(world, site_config, state)
    return world, state


def test_the_cursor_moves_one_plan_cell_inside_a_site(site_config: Config) -> None:
    world, state = _open(site_config)
    col, row = state.px, state.py
    move_cursor(world, site_config, state, 1, 0)
    assert (state.px, state.py, state.scale) == (col + 1, row, SCALE_SITE)


def test_the_tile_cursor_follows_the_plan_cell(site_config: Config) -> None:
    # Walking east across the window moves the tile cursor to the tile under the cell.
    world, state = _open(site_config)
    geometry = site_geometry(world.pois[0], site_config)
    assert geometry is not None
    move_cursor(world, site_config, state, geometry.cell_w, 0)
    assert (state.cx, state.cy) == (11, 10)


def test_walking_off_the_site_window_leaves_for_local(site_config: Config) -> None:
    world, state = _open(site_config)
    geometry = site_geometry(world.pois[0], site_config)
    assert geometry is not None
    state.px = geometry.cols - 1
    move_cursor(world, site_config, state, 1, 0)
    assert state.scale == SCALE_LOCAL and state.poi is None and "left" in state.last_message


def test_leaving_a_site_lands_on_the_tile_beyond_the_edge(site_config: Config) -> None:
    world, state = _open(site_config)
    geometry = site_geometry(world.pois[0], site_config)
    assert geometry is not None
    state.px = geometry.cols - 1
    move_cursor(world, site_config, state, 1, 0)
    assert state.cx == geometry.cam_x + geometry.tiles_w


def test_a_site_at_the_world_edge_is_left_before_the_world_ends(site_config: Config) -> None:
    world = make_world(20, 20, Biome.GRASS)
    world.pois.append(POI(kind="tower", x=0, y=10, interior_seed=3, floor_count=1))
    state = ViewState(scale=SCALE_ZOOM, cx=0, cy=10)
    step_in(world, site_config, state)
    geometry = site_geometry(world.pois[0], site_config)
    assert geometry is not None
    state.px = 0
    for _ in range(geometry.cell_w):  # walk west until off the world
        move_cursor(world, site_config, state, -1, 0)
        if state.scale != SCALE_SITE:
            break
    assert state.scale == SCALE_LOCAL and state.cx == 0


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


def test_cursor_stops_at_the_world_edge(config: Config) -> None:
    world = make_world(5, 4)
    state = ViewState(cx=4, cy=0)
    move_cursor(world, config, state, 3, -3)
    assert (state.cx, state.cy) == (4, 0)


def test_cursor_moves_by_the_step(config: Config) -> None:
    world = make_world(10, 10)
    state = ViewState(cx=2, cy=2)
    move_cursor(world, config, state, 3, 1)
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


def test_structure_under_the_cursor_covers_its_whole_extent(site_config: Config) -> None:
    world = _dungeon_world()
    assert poi_under_cursor(world, site_config, ViewState(cx=11, cy=10)) is world.pois[0]


def test_no_structure_outside_the_extent(site_config: Config) -> None:
    assert poi_under_cursor(_dungeon_world(), site_config, ViewState(cx=12, cy=10)) is None


def test_the_open_site_is_the_structure_under_the_cursor(site_config: Config) -> None:
    world, state = _open(site_config)
    state.cx = 2  # even with the tile cursor elsewhere, the open site wins
    assert poi_under_cursor(world, site_config, state) is world.pois[0]


def test_entering_a_structure_starts_on_the_ground_floor(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(cx=10, cy=10, floor=-1)
    sync_floor(world, site_config, state, None)
    assert state.floor == 0


def test_moving_within_a_structure_keeps_the_floor(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(cx=10, cy=10)
    tracking = sync_floor(world, site_config, state, None)
    state.floor = -1
    state.cx = 11
    sync_floor(world, site_config, state, tracking)
    assert state.floor == -1


def test_leaving_every_structure_resets_the_floor(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(cx=10, cy=10)
    tracking = sync_floor(world, site_config, state, None)
    state.floor, state.cx = -1, 2
    sync_floor(world, site_config, state, tracking)
    assert state.floor == 0


def test_floor_cycles_down_and_stops_at_the_bottom(site_config: Config) -> None:
    world = _dungeon_world()
    state = ViewState(cx=10, cy=10)
    cycle_floor(world, site_config, state, -1)
    cycle_floor(world, site_config, state, -1)
    assert (state.floor, "no further floor" in state.last_message) == (-1, True)


def test_floors_cycle_inside_an_open_site(site_config: Config) -> None:
    world, state = _open(site_config)
    cycle_floor(world, site_config, state, -1)
    assert state.floor == -1


def test_cycling_off_a_structure_explains_itself(site_config: Config) -> None:
    state = ViewState(cx=0, cy=0)
    cycle_floor(_dungeon_world(), site_config, state, 1)
    assert "no interior here" in state.last_message


@pytest.mark.parametrize("delta", [1, -1])
def test_single_floor_structure_cannot_change_floor(site_config: Config, delta: int) -> None:
    world = make_world(10, 10)
    world.pois.append(POI(kind="camp", x=5, y=5, interior_seed=1, floor_count=1))
    state = ViewState(cx=5, cy=5)
    cycle_floor(world, site_config, state, delta)
    assert (state.floor, "single floor" in state.last_message) == (0, True)


def _village_world():
    from biomegen.world.entities import POI

    world = make_world(16, 12)
    world.pois.append(POI(kind="village", x=8, y=6, interior_seed=3, pop=500, civilized=True))
    return world


def test_a_village_can_cycle_up_to_its_roofs(site_config: Config) -> None:
    # A one-storey settlement still has a roof level above its ground: floor 1 shows every building's roof.
    state = ViewState(cx=8, cy=6)
    cycle_floor(_village_world(), site_config, state, 1)
    assert (state.floor, "roofs" in state.last_message) == (1, True)


def test_the_roof_level_is_the_last_floor_of_a_settlement(site_config: Config) -> None:
    world = _village_world()
    state = ViewState(cx=8, cy=6)
    cycle_floor(world, site_config, state, 1)
    cycle_floor(world, site_config, state, 1)
    assert (state.floor, "no further floor" in state.last_message) == (1, True)


def test_a_dungeon_has_no_roof_level(site_config: Config) -> None:
    from biomegen.explorer.state import floor_label

    world = _dungeon_world()
    assert floor_label(world.pois[0], site_config, -1) == "-1"
