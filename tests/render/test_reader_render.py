"""Tests for rendering through the world reader: unchanged at zero ticks, and showing what the simulation changed."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.cache import RenderCache
from biomegen.render.chronicle import name_color
from biomegen.render.fit import FitSampler, tile_priority
from biomegen.render.furniture.legend import build_legend
from biomegen.render.layers import build_grid, owner_palette_index
from biomegen.render.static import StaticRender, render_detail, render_static
from biomegen.render.views import resolve_view
from biomegen.sampling.sampler import Sampler
from biomegen.sim.hydrate import hydrate
from biomegen.world.entities import POI, REF_POI, REF_REALM, FallenRealm, Realm
from biomegen.world.reader import WorldReader
from biomegen.world.sim_state import SimState
from biomegen.world.tile import Biome
from biomegen.world.world import World
from tests.render.conftest import make_world

SEED = 42


@pytest.fixture(scope="module")
def cfg() -> Config:
    return load_config(None)


@pytest.fixture(scope="module")
def world(cfg: Config) -> World:
    return pipeline.generate(cfg, SEED)


@pytest.fixture(scope="module")
def reader(world: World, cfg: Config) -> WorldReader:
    """The generated world read through its hydrated state at tick 0."""
    return WorldReader(world, hydrate(world, cfg, SEED))


def _same(first: StaticRender, second: StaticRender) -> bool:
    return all(
        np.array_equal(getattr(first.grid, name), getattr(second.grid, name)) for name in ("glyph", "fg", "bg", "bold")
    ) and (first.document == second.document)


# ---------------------------------------------------------------- zero ticks: the frames are today's
@pytest.mark.parametrize("view", ["terrain", "political", "elevation"])
def test_a_static_map_is_unchanged_at_zero_ticks(world: World, cfg: Config, reader: WorldReader, view: str) -> None:
    assert _same(render_static(world, cfg, view), render_static(world, cfg, view, reader=reader))


@pytest.mark.parametrize("scale", ["zoom", "local", "site"])
def test_a_magnified_view_of_the_capital_is_unchanged_at_zero_ticks(
    world: World, cfg: Config, reader: WorldReader, scale: str
) -> None:
    seat = world.pois[world.realms[0].seat_poi]
    at = (seat.x, seat.y)
    assert _same(
        render_detail(world, cfg, scale, "political", at=at),
        render_detail(world, cfg, scale, "political", at=at, reader=reader),
    )


def test_a_hamlet_or_village_view_is_unchanged_at_zero_ticks(world: World, cfg: Config, reader: WorldReader) -> None:
    village = next(poi for poi in world.pois if poi.kind == "village")
    at = (village.x, village.y)
    assert _same(render_detail(world, cfg, "local", at=at), render_detail(world, cfg, "local", at=at, reader=reader))


def test_the_sites_layer_draws_the_manifest_the_simulation_keeps(world: World, cfg: Config) -> None:
    # A manifest with no house built gives a different plan from the one the settlement's population does.
    index = next(i for i, poi in enumerate(world.pois) if poi.kind == "village")
    village = world.pois[index]
    state = hydrate(world, cfg, SEED)
    state.manifests[index] = replace(state.manifests[index], houses=0, specialized=0)
    at = (village.x, village.y)
    plain = render_detail(world, cfg, "local", at=at)
    changed = render_detail(world, cfg, "local", at=at, reader=WorldReader(world, state))
    assert not _same(plain, changed)


# ---------------------------------------------------------------- what the simulation changed
def _two_realms() -> World:
    """An 8x4 grass world: realm 0 on the left half, realm 1 on the right."""
    world = make_world(8, 4, Biome.GRASS)
    world.realm_id[:, :4] = 0
    world.realm_id[:, 4:] = 1
    world.realms = [
        Realm(id=0, kind="major", name="Aria", short="Aria", color=(200, 40, 40)),
        Realm(id=1, kind="major", name="Bex", short="Bex", color=(40, 40, 200)),
    ]
    return world


def _frame(world: World, cfg: Config, reader: WorldReader | None = None) -> np.ndarray:
    view = resolve_view(cfg, "political")
    sampler = Sampler.viewport(world, world.height, world.width)
    return build_grid(world, cfg, view, sampler, labels="none", reader=reader).bg


def test_a_cell_that_changed_owner_is_drawn_in_its_new_realms_colour(cfg: Config) -> None:
    # The oracle: the frame equals that of a world whose own realm grid holds the change.
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    state.owners[1:3, 2:4] = 1
    moved = _two_realms()
    moved.realm_id[1:3, 2:4] = 1
    assert np.array_equal(_frame(world, cfg, WorldReader(world, state)), _frame(moved, cfg))


def test_the_unchanged_world_is_not_drawn_as_the_change(cfg: Config) -> None:
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    state.owners[1:3, 2:4] = 1
    assert not np.array_equal(_frame(world, cfg, WorldReader(world, state)), _frame(world, cfg))


def test_a_poi_the_simulation_minted_is_drawn_as_its_marker(cfg: Config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    state = hydrate(world, cfg, 1)
    state.pois = [POI(kind="tower", x=1, y=1, interior_seed=5)]
    view = resolve_view(cfg, "terrain")
    grid = build_grid(world, cfg, view, Sampler.viewport(world, 3, 3), reader=WorldReader(world, state))
    assert grid.glyph[1, 1] == cfg.get("render.markers.tower")


def test_the_same_poi_is_not_drawn_without_the_reader(cfg: Config) -> None:
    world = make_world(3, 3, Biome.GRASS)
    view = resolve_view(cfg, "terrain")
    grid = build_grid(world, cfg, view, Sampler.viewport(world, 3, 3))
    assert grid.glyph[1, 1] != cfg.get("render.markers.tower")


def test_a_realm_the_simulation_made_has_a_colour_in_the_political_map(cfg: Config) -> None:
    # Owner 2 is a realm only the simulation knows: its palette index and colour come from the reader's realms.
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    state.realms = [Realm(id=2, kind="tribal", name="Cade", short="Cade", color=(10, 220, 10))]
    state.owners[:, 6:] = 2
    grid = _frame(world, cfg, WorldReader(world, state))
    assert grid.shape[:2] == (4, 8) and tuple(grid[1, 7].tolist())[1] > tuple(grid[1, 7].tolist())[0]


def test_the_palette_index_counts_the_realms_the_simulation_made() -> None:
    world = _two_realms()
    codes = np.array([[-1, 0, 1, -2]])
    world.fallen_realms = [FallenRealm(0, (0, 0), 1, 2), FallenRealm(1, (1, 1), 1, 2)]
    # Three realms (one made by the simulation): fallen realm 0 (owner -2) follows them at index 3.
    assert owner_palette_index(world, codes, realms=3).tolist() == [[-1, 0, 1, 3]]


def test_the_legend_shows_the_population_the_simulation_counts(world: World, cfg: Config) -> None:
    state = hydrate(world, cfg, SEED)
    state.factions[world.realms[0].id].pop = 7_654_321
    view = resolve_view(cfg, "political")
    text = "\n".join(
        "".join(span.text for span in line)
        for line in build_legend(world, cfg, view, 100, reader=WorldReader(world, state))
    )
    assert "pop. ~7.7 million" in text


def test_the_legend_without_a_reader_shows_the_generated_population(world: World, cfg: Config) -> None:
    view = resolve_view(cfg, "political")
    text = "\n".join("".join(span.text for span in line) for line in build_legend(world, cfg, view, 100))
    assert "pop. ~7.7 million" not in text


# ---------------------------------------------------------------- colours of names and the fit map
def test_a_realm_the_simulation_made_is_coloured_by_the_reader(cfg: Config) -> None:
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    state.realms = [Realm(id=2, kind="tribal", color=(1, 2, 3))]
    assert name_color(world, cfg, REF_REALM, 2, reader=WorldReader(world, state)) == (1, 2, 3)


def test_a_realm_the_simulation_made_has_no_colour_without_the_reader(cfg: Config) -> None:
    with pytest.raises(IndexError):
        name_color(_two_realms(), cfg, REF_REALM, 2)


def test_a_place_that_changed_hands_takes_its_new_realms_colour(cfg: Config) -> None:
    world = _two_realms()
    world.pois = [POI(kind="town", x=1, y=1, interior_seed=1, civilized=True, realm_id=0, pop=100)]
    state = hydrate(world, cfg, 1)
    state.places[0].owner = 1
    assert name_color(world, cfg, REF_POI, 0, reader=WorldReader(world, state)) == (40, 40, 200)


def test_a_minted_poi_is_salient_on_the_fit_map_with_the_reader(cfg: Config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    state = hydrate(world, cfg, 1)
    state.pois = [POI(kind="tower", x=2, y=2, interior_seed=5)]
    reader = WorldReader(world, state)
    assert tile_priority(world, cfg, reader)[2, 2] > tile_priority(world, cfg)[2, 2]


def test_the_fit_sampler_picks_a_minted_poi_for_its_block(cfg: Config) -> None:
    world = make_world(4, 4, Biome.GRASS)
    state = hydrate(world, cfg, 1)
    state.pois = [POI(kind="tower", x=3, y=3, interior_seed=5)]
    sampler = FitSampler(world, cfg, 2, 2, WorldReader(world, state))
    assert (float(sampler.tile_x[1, 1]), float(sampler.tile_y[1, 1])) == (3.0, 3.0)


# ---------------------------------------------------------------- the render cache and the revision
def _cached(cache: RenderCache, world: World, cfg: Config, reader: WorldReader) -> np.ndarray:
    view = resolve_view(cfg, "political")
    sampler = FitSampler(world, cfg, 8, 4)
    return cache.draw(world, cfg, view, sampler, labels="none", reader=reader).bg


def test_the_cache_keeps_a_frame_while_the_revision_is_the_same(cfg: Config) -> None:
    # The simulation bumps the revision when it changes something: until it does, the cached frame stands.
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    reader, cache = WorldReader(world, state), RenderCache(cfg)
    first = _cached(cache, world, cfg, reader)
    state.owners[1:3, 2:4] = 1
    assert np.array_equal(_cached(cache, world, cfg, reader), first)


def test_the_cache_drops_what_it_drew_when_the_revision_changes(cfg: Config) -> None:
    world = _two_realms()
    state = hydrate(world, cfg, 1)
    reader, cache = WorldReader(world, state), RenderCache(cfg)
    _cached(cache, world, cfg, reader)
    state.owners[1:3, 2:4] = 1
    state.revision += 1
    assert np.array_equal(_cached(cache, world, cfg, reader), _frame(world, cfg, reader))


def test_the_cache_drops_what_it_drew_for_a_new_state(cfg: Config) -> None:
    world = _two_realms()
    first = hydrate(world, cfg, 1)
    cache = RenderCache(cfg)
    _cached(cache, world, cfg, WorldReader(world, first))
    second = SimState(owners=first.owners.copy(), ticks_per_month=30)
    second.owners[1:3, 2:4] = 1
    assert np.array_equal(
        _cached(cache, world, cfg, WorldReader(world, second)), _frame(world, cfg, WorldReader(world, second))
    )
