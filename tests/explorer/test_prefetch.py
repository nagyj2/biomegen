"""Tests for the explorer's idle-time work."""

from __future__ import annotations

from biomegen.config import load_config
from biomegen.explorer.prefetch import idle_work
from biomegen.explorer.state import ViewState
from biomegen.render.cache import RenderCache
from biomegen.world.entities import POI
from biomegen.world.tile import Biome
from tests.render.conftest import make_world


def _two_villages():
    """A 60 x 10 world with a village by the cursor at (5, 5) and another 50 tiles east."""
    world = make_world(60, 10, Biome.GRASS)
    for index, x in enumerate((5, 55)):
        world.pois.append(POI(kind="village", x=x, y=5, interior_seed=index + 1, pop=300))
        world.poi_index[5, x] = index
    return world


def test_idle_work_builds_only_the_plans_within_reach() -> None:
    # On the map (no detail sampler) the only work is plans: the near village is within prefetch_site_km, the far
    # one (50 tiles of 1 km) is not.
    config = load_config(None)
    config.data["render"]["cache"]["prefetch_site_km"] = 10.0
    world = _two_villages()
    state = ViewState(cx=5, cy=5)
    steps = sum(1 for _ in idle_work(world, config, state, RenderCache(config), "terrain", None))
    assert steps == 1
