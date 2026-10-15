"""Tests for the render cache: cached frames match fresh draws, reuse what is on screen, and forget what changed."""

from __future__ import annotations

import numpy as np
import pytest

from biomegen import pipeline
from biomegen.config import load_config
from biomegen.config.model import Config
from biomegen.render.cache import RenderCache, split_layers
from biomegen.render.fit import FitSampler
from biomegen.render.grid import CellGrid
from biomegen.render.layers import Seen, build_grid
from biomegen.render.views import resolve_view
from biomegen.sampling.detail import SCALE_LOCAL, SCALE_ZOOM, DetailSampler
from biomegen.sites import site_geometry, site_pois, window_sampler
from biomegen.world.overlay import Overlay
from biomegen.world.tile import Cell
from biomegen.world.world import World


@pytest.fixture(scope="module")
def config() -> Config:
    config = load_config(None)
    config.data["world"]["width"], config.data["world"]["height"] = 96, 48
    return config


@pytest.fixture(scope="module")
def world(config: Config) -> World:
    return pipeline.generate(config, 7)


def _same(a: CellGrid, b: CellGrid) -> bool:
    return all(np.array_equal(getattr(a, name), getattr(b, name)) for name in ("glyph", "fg", "bg", "bold"))


def _zoom(world: World, config: Config, cam: tuple[int, int], scale: str = SCALE_ZOOM) -> DetailSampler:
    return DetailSampler(world, config, 10, 5, cam[0], cam[1], 12, 7, scale)


def _settlement_site(world: World, config: Config):
    poi, geometry = max(site_pois(world, config), key=lambda found: found[1].cols * found[1].rows)
    return poi, geometry


def test_split_layers_keeps_the_cacheable_prefix() -> None:
    # Layers after the first one that depends on the screen run every frame, even a cacheable one.
    assert split_layers(("terrain", "relief", "markers", "roads")) == (("terrain", "relief"), ("markers", "roads"))


@pytest.mark.parametrize("scale", [SCALE_ZOOM, SCALE_LOCAL])
def test_a_cached_detail_frame_matches_a_fresh_draw(world: World, config: Config, scale: str) -> None:
    view = resolve_view(config, "terrain")
    sampler = _zoom(world, config, (30, 20), scale)
    cached = RenderCache(config).draw(world, config, view, sampler)
    assert _same(cached, build_grid(world, config, view, _zoom(world, config, (30, 20), scale)))


def test_a_frame_after_a_pan_matches_a_fresh_draw(world: World, config: Config) -> None:
    # The second frame reuses the first frame's chunks for the ground both show.
    view = resolve_view(config, "terrain")
    cache = RenderCache(config)
    cache.draw(world, config, view, _zoom(world, config, (30, 20)))
    panned = cache.draw(world, config, view, _zoom(world, config, (33, 21)))
    assert _same(panned, build_grid(world, config, view, _zoom(world, config, (33, 21))))


def test_a_pan_draws_only_the_new_ground(world: World, config: Config) -> None:
    # Panning four tiles (40 cells) brings one new column of chunks into view, far fewer cells than a whole frame.
    view = resolve_view(config, "terrain")
    cache = RenderCache(config)
    cache.draw(world, config, view, _zoom(world, config, (30, 20)))
    first = cache.cells
    cache.draw(world, config, view, _zoom(world, config, (34, 20)))
    assert 0 < cache.cells - first < first // 2


def test_the_seen_biomes_match_a_fresh_draw(world: World, config: Config) -> None:
    view = resolve_view(config, "terrain")
    cached_seen, fresh_seen = Seen(), Seen()
    RenderCache(config).draw(world, config, view, _zoom(world, config, (30, 20)), seen=cached_seen)
    build_grid(world, config, view, _zoom(world, config, (30, 20)), seen=fresh_seen)
    assert cached_seen.biomes == fresh_seen.biomes


def test_borders_see_their_neighbours_across_chunk_edges(world: World, config: Config) -> None:
    # A fresh draw one tile larger on every side has true neighbours for the cached frame's cells; inside it the two
    # agree cell for cell, so no chunk edge breaks a border line.
    view = resolve_view(config, "political")
    cached = RenderCache(config).draw(world, config, view, _zoom(world, config, (30, 20)))
    larger = build_grid(world, config, view, DetailSampler(world, config, 10, 5, 29, 19, 14, 9, SCALE_ZOOM))
    inner = (slice(5, 5 + cached.rows), slice(10, 10 + cached.cols))
    assert all(np.array_equal(getattr(cached, name), getattr(larger, name)[inner]) for name in ("bg", "glyph"))


def test_a_site_view_region_matches_a_fresh_draw(world: World, config: Config) -> None:
    poi, geometry = _settlement_site(world, config)
    view = resolve_view(config, "terrain")
    region = ((3, 2), (30, 50))
    cached = RenderCache(config).draw(world, config, view, window_sampler(world, config, geometry, *region))
    assert _same(cached, build_grid(world, config, view, window_sampler(world, config, geometry, *region)))


def test_an_overlay_edit_is_drawn_on_the_next_frame(world: World, config: Config) -> None:
    # The interior edit changes a cached site cell; the cache drops what it drew and the next frame shows it.
    poi, geometry = _settlement_site(world, config)
    view = resolve_view(config, "terrain")
    overlay = Overlay()
    cache = RenderCache(config)
    cache.draw(world, config, view, window_sampler(world, config, geometry), overlay)
    col, row = geometry.cell_at(poi.x, poi.y)
    overlay.set_interior(poi.interior_seed, 0, col, row, int(Cell.CHEST))
    cached = cache.draw(world, config, view, window_sampler(world, config, geometry), overlay)
    assert _same(cached, build_grid(world, config, view, window_sampler(world, config, geometry), overlay))


def test_invalidating_a_box_drops_only_the_chunks_near_it(world: World, config: Config) -> None:
    view = resolve_view(config, "terrain")
    cache = RenderCache(config)
    cache.draw(world, config, view, _zoom(world, config, (30, 20)))
    full = cache.cells
    cache.invalidate((80, 0, 90, 5))  # far from the frame
    kept = cache.cells
    cache.invalidate((35, 24, 36, 25))  # inside it
    assert (kept, cache.cells < full) == (full, True)


def test_the_cache_keeps_at_most_max_cells(world: World) -> None:
    small = load_config(None)
    small.data["render"]["cache"]["max_cells"] = 5000
    view = resolve_view(small, "terrain")
    cache = RenderCache(small)
    for cam in ((10, 10), (40, 20), (70, 30)):
        cache.draw(world, small, view, _zoom(world, small, cam))
    assert cache.cells <= 5000


def test_a_map_frame_is_reused_and_handed_out_as_a_copy(world: World, config: Config) -> None:
    # The fit map does not move with the cursor: the second draw is the first one's frame, which the caller may mark.
    view = resolve_view(config, "terrain")
    cache = RenderCache(config)
    first = cache.draw(world, config, view, FitSampler(world, config, 60, 30))
    first.glyph[...] = "!"
    second = cache.draw(world, config, view, FitSampler(world, config, 60, 30))
    assert _same(second, build_grid(world, config, view, FitSampler(world, config, 60, 30)))


def test_a_site_geometry_is_found_for_the_fixture_world(world: World, config: Config) -> None:
    # Guards the site tests above: the fixture world has a settlement with a plan window.
    poi, geometry = _settlement_site(world, config)
    assert site_geometry(poi, config) is not None and geometry.cols > 30


def test_prefetch_draws_the_ground_a_re_centre_brings_into_view(world: World, config: Config) -> None:
    # After the prefetch has run, moving the view half a screen needs no new chunk.
    view = resolve_view(config, "terrain")
    cache = RenderCache(config)
    cache.draw(world, config, view, _zoom(world, config, (30, 20)))
    for _ in cache.prefetch(world, config, view, _zoom(world, config, (30, 20))):
        pass
    prepared = cache.cells
    cache.draw(world, config, view, _zoom(world, config, (36, 23)))
    assert cache.cells == prepared


def test_prefetch_never_pushes_out_drawn_chunks(world: World) -> None:
    # A cache nearly full after one frame prefetches nothing, so the frame's chunks stay.
    small = load_config(None)
    small.data["render"]["cache"]["max_cells"] = 9000
    view = resolve_view(small, "terrain")
    cache = RenderCache(small)
    cache.draw(world, small, view, _zoom(world, small, (30, 20)))
    drawn = cache.cells
    for _ in cache.prefetch(world, small, view, _zoom(world, small, (30, 20))):
        pass
    assert drawn <= cache.cells <= 9000
