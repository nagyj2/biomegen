"""Tests for the explorer reading the world through the reader: unchanged at zero ticks, showing what changed."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.explorer.app import compose_frame, run
from biomegen.explorer.exports import export_world
from biomegen.explorer.panel import build_panel
from biomegen.explorer.prefetch import idle_work
from biomegen.explorer.state import (
    ViewState,
    initial_cursor,
    place_under_cursor,
    step_in,
    step_out,
    sync_floor,
)
from biomegen.render.cache import RenderCache
from biomegen.render.layers import Seen
from biomegen.render.views import view_names
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_MAP, SCALE_SITE, SCALE_ZOOM
from biomegen.sim.hydrate import hydrate
from biomegen.sites.plan import _cache
from biomegen.world.entities import POI, ChronicleEvent, Realm
from biomegen.world.overlay import Overlay
from biomegen.world.reader import WorldReader
from biomegen.world.sim_state import PlaceState, SimState
from biomegen.world.tile import Biome
from biomegen.world.world import World
from tests.explorer.replay import RecordingOut
from tests.explorer.test_app import ScriptedKeys
from tests.render.conftest import make_world

SIZE = (100, 40)
SEED = 42


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


@pytest.fixture(scope="module")
def reader(world: World, cfg: Config) -> WorldReader:
    return WorldReader(world, hydrate(world, cfg, SEED))


def _arrays(frame) -> tuple[np.ndarray, ...]:
    screen = frame.screen
    return screen.glyph, screen.fg, screen.bg, screen.bold


def _same(first, second) -> bool:
    return all(np.array_equal(a, b) for a, b in zip(_arrays(first), _arrays(second), strict=True))


def _state_at(world: World, cfg: Config, scale: str, view: str, reader: WorldReader | None) -> ViewState:
    """A state with the cursor on the first realm's seat at ``scale`` in ``view`` (a site is opened by stepping in)."""
    seat = world.pois[world.realms[0].seat_poi]
    state = ViewState(cx=seat.x, cy=seat.y, view_index=view_names(cfg).index(view), recenter=True)
    state.scale = SCALE_LOCAL if scale == SCALE_SITE else scale
    if scale == SCALE_SITE:
        step_in(world, cfg, state, reader)
    return state


# ---------------------------------------------------------------- zero ticks: the screen is today's
@pytest.mark.parametrize("view", ["terrain", "political"])
@pytest.mark.parametrize("scale", [SCALE_MAP, SCALE_ZOOM, SCALE_LOCAL, SCALE_SITE])
def test_a_frame_is_unchanged_at_zero_ticks(
    world: World, cfg: Config, reader: WorldReader, scale: str, view: str
) -> None:
    plain = compose_frame(world, cfg, _state_at(world, cfg, scale, view, None), Overlay(), SIZE)
    read = compose_frame(world, cfg, _state_at(world, cfg, scale, view, reader), Overlay(), SIZE, reader=reader)
    assert _same(plain, read)


def test_a_cached_frame_is_unchanged_at_zero_ticks(world: World, cfg: Config, reader: WorldReader) -> None:
    plain = compose_frame(world, cfg, _state_at(world, cfg, SCALE_ZOOM, "political", None), Overlay(), SIZE)
    cached = compose_frame(
        world,
        cfg,
        _state_at(world, cfg, SCALE_ZOOM, "political", reader),
        Overlay(),
        SIZE,
        cache=RenderCache(cfg),
        reader=reader,
    )
    assert _same(plain, cached)


def test_the_first_cursor_is_unchanged_at_zero_ticks(world: World, cfg: Config, reader: WorldReader) -> None:
    assert initial_cursor(world, cfg, reader) == initial_cursor(world, cfg)


# ---------------------------------------------------------------- what the simulation changed
def _small() -> World:
    """A 40x20 world: realm 0 (Aria) on the left, realm 1 (Bex) on the right, and Dunmere, a village, at (20, 10)."""
    world = make_world(40, 20, Biome.GRASS)
    world.island_name = "Testland"
    world.realm_id[:, :20] = 0
    world.realm_id[:, 20:] = 1
    world.realms = [
        Realm(id=0, kind="major", name="Aria", short="Aria", ruler="King A", color=(200, 40, 40), pop=5000),
        Realm(id=1, kind="major", name="Bex", short="Bex", ruler="Mayor B", color=(40, 40, 200), pop=900),
    ]
    world.pois = [
        POI(
            kind="village",
            x=20,
            y=10,
            interior_seed=3,
            pop=800,
            name="Dunmere",
            civilized=True,
            realm_id=1,
            tags=("river",),
        )
    ]
    world.poi_index[10, 20] = 0
    return world


def _panel(world: World, cfg: Config, state: ViewState, reader: WorldReader, view: str = "terrain") -> list[str]:
    grid = build_panel(world, cfg, state, view, Seen(), 100, 15, reader=reader)
    return ["".join(row) for row in grid.glyph.tolist()]


def test_the_poi_line_shows_the_people_the_simulation_counts(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.places[0].pop = 1234
    assert "pop 1,234" in _panel(world, cfg, ViewState(cx=20, cy=10), WorldReader(world, state))[5]


def test_the_poi_name_is_in_the_colour_of_its_new_owner(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.places[0].owner = 0
    grid = build_panel(
        world, cfg, ViewState(cx=20, cy=10), "terrain", Seen(), 100, 15, reader=WorldReader(world, state)
    )
    assert tuple(grid.fg[5, 6].tolist()) == (200, 40, 40)


def test_the_realm_line_shows_the_people_the_simulation_counts(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.factions[1].pop = 777_777
    assert "pop. ~777,777" in _panel(world, cfg, ViewState(cx=20, cy=10), WorldReader(world, state))[4]


def test_the_realm_at_the_cursor_is_the_one_the_simulations_owner_grid_gives(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.owners[10, 20] = 0
    assert "Aria" in _panel(world, cfg, ViewState(cx=20, cy=10), WorldReader(world, state))[3]


def test_the_buildings_line_follows_the_manifest_the_simulation_keeps(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    site = ViewState(cx=20, cy=10)
    step_in(world, cfg, site)  # map -> zoom
    step_in(world, cfg, site)  # zoom -> the village's site
    plain = [line for line in _panel(world, cfg, site, WorldReader(world, state)) if "buildings:" in line]
    state.manifests[0] = replace(state.manifests[0], houses=0, specialized=0)
    bare = [line for line in _panel(world, cfg, site, WorldReader(world, state)) if "buildings:" in line]
    assert plain and bare and plain != bare


def test_a_simulation_event_at_the_cursor_is_listed_in_the_political_panel(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    reader = WorldReader(world, state)
    reader.events.append(
        ChronicleEvent(-1, 1201, "treaty", realm_ids=[1], location=(20, 10), text="A treaty was sworn.", month=2)
    )
    text = "\n".join(_panel(world, cfg, ViewState(cx=20, cy=10), reader, "political"))
    assert "A treaty was sworn." in text


# ---------------------------------------------------------------- finding a site by index
def _tower_world() -> World:
    world = make_world(40, 20, Biome.GRASS)
    world.pois = [POI(kind="tower", x=20, y=10, interior_seed=3, floor_count=2)]
    world.poi_index[10, 20] = 0
    return world


def test_the_place_under_the_cursor_is_the_readers_current_poi(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.places[0].owner = 0
    index, poi = place_under_cursor(world, cfg, ViewState(cx=20, cy=10), WorldReader(world, state))  # type: ignore[misc]
    assert (index, poi.realm_id, poi is world.pois[0]) == (0, 0, False)


def test_a_floor_choice_survives_the_simulation_replacing_the_poi(cfg: Config) -> None:
    # The structure is tracked by its index: a new object for the same tower is not "leaving" it.
    world = _tower_world()
    state = hydrate(world, cfg, 1)
    reader = WorldReader(world, state)
    view = ViewState(cx=20, cy=10)
    tracking = sync_floor(world, cfg, view, None, reader)
    view.floor = 1
    state.places[0] = PlaceState(owner=0, pop=1)
    state.revision += 1
    sync_floor(world, cfg, view, tracking, reader)
    assert view.floor == 1


def test_stepping_into_a_site_records_its_index(cfg: Config) -> None:
    world = _small()
    reader = WorldReader(world, hydrate(world, cfg, 1))
    view = ViewState(cx=20, cy=10, scale=SCALE_LOCAL)
    step_in(world, cfg, view, reader)
    assert (view.scale, view.poi_index) == (SCALE_SITE, 0)


def test_stepping_out_of_a_site_forgets_its_index(cfg: Config) -> None:
    world = _small()
    reader = WorldReader(world, hydrate(world, cfg, 1))
    view = ViewState(cx=20, cy=10, scale=SCALE_LOCAL)
    step_in(world, cfg, view, reader)
    step_out(view)
    assert (view.poi, view.poi_index) == (None, -1)


def test_a_site_the_simulation_minted_can_be_entered(cfg: Config) -> None:
    world = _tower_world()
    state = hydrate(world, cfg, 1)
    state.pois = [POI(kind="tower", x=30, y=5, interior_seed=9, floor_count=2)]
    view = ViewState(cx=30, cy=5, scale=SCALE_LOCAL)
    step_in(world, cfg, view, WorldReader(world, state))
    assert (view.scale, view.poi_index) == (SCALE_SITE, 1)


# ---------------------------------------------------------------- prefetch, export and the loop
def test_idle_time_builds_the_plan_of_a_poi_the_simulation_minted(cfg: Config) -> None:
    world = make_world(40, 20, Biome.GRASS)
    state = hydrate(world, cfg, 1)
    state.pois = [POI(kind="tower", x=20, y=10, interior_seed=9)]
    list(
        idle_work(
            world, cfg, ViewState(cx=20, cy=10), RenderCache(cfg), "terrain", None, reader=WorldReader(world, state)
        )
    )
    assert len(_cache(world, cfg)) == 1


def _svg(tmp_path: Path, world: World, reader: WorldReader | None) -> str:
    config = load_config(None)
    config.data["export"].update({"dir": str(tmp_path / "out"), "png": False})
    (path,) = export_world(world, config, "political", reader=reader)
    return Path(path).read_text(encoding="utf-8")


def test_a_world_export_is_unchanged_at_zero_ticks(tmp_path: Path, cfg: Config) -> None:
    world = _small()
    assert _svg(tmp_path, world, None) == _svg(tmp_path, world, WorldReader(world, hydrate(world, cfg, 1)))


def test_a_world_export_shows_what_the_simulation_changed(tmp_path: Path, cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.owners[:, 10:20] = 1
    assert _svg(tmp_path, world, None) != _svg(tmp_path, world, WorldReader(world, state))


class _Source:
    """An inactive tick source that holds a simulation's state (what ``run`` reads the world through)."""

    active = False

    def __init__(self, state: SimState) -> None:
        self.state = state

    def due(self, now: float, speed: float) -> int:
        return 0

    def tick(self, count: int) -> bool:
        return False

    def reset(self, world: World) -> None:
        return None


def _run(world: World, cfg: Config, source: object | None = None) -> RecordingOut:
    out = RecordingOut(SIZE[1], SIZE[0])
    run(world, cfg, "none", reader=ScriptedKeys(), out=out, get_size=lambda: SIZE, ticks=source)  # type: ignore[arg-type]
    return out


def test_the_loop_reads_the_world_through_its_sources_state(cfg: Config) -> None:
    world = _small()
    state = hydrate(world, cfg, 1)
    state.owners[10, 20] = 0
    assert "Aria" in "\n".join(_run(world, cfg, _Source(state)).frames[-1])


def test_the_loop_without_a_source_shows_the_generated_world(cfg: Config) -> None:
    assert "Aria" not in "\n".join(_run(_small(), cfg).frames[-1])
