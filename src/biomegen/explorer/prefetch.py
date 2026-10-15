"""Idle-time work: what the explorer prepares while it waits for a key.

The explorer is event driven and sits idle between keys. That time is spent drawing what the next frames are likely
to need, in small steps so a key press is never kept waiting for long: the terrain chunks round the screen (see
:meth:`~biomegen.render.cache.RenderCache.prefetch`), then the plans of the sites nearest the cursor, which take the
longest to build (a capital's plan is the slowest thing the explorer draws).
"""

from __future__ import annotations

from typing import Iterator, Optional

from ..config.model import Config
from ..render.cache import RenderCache
from ..render.views import resolve_view
from ..sampling.sampler import Sampler
from ..sites import site_plan, site_pois
from ..world.overlay import Overlay
from ..world.world import World
from .state import ViewState


def idle_work(
    world: World,
    config: Config,
    state: ViewState,
    cache: RenderCache,
    view_name: str,
    sampler: Optional[Sampler],
    overlay: Optional[Overlay] = None,
    color: bool = True,
    ascii_only: bool = False,
) -> Iterator[None]:
    """Yield after each small piece of preparation for the frames after the one on screen (drawn through ``sampler``).

    The caller stops advancing it as soon as a key is waiting; a fresh one starts after the next frame.
    """
    if sampler is not None:
        view = resolve_view(config, view_name)
        yield from cache.prefetch(world, config, view, sampler, overlay, ascii_only, color, state.floor)
    radius_km = float(config.get("render.cache.prefetch_site_km"))
    scale = world.scale

    def distance_km(x: int, y: int) -> float:
        return float((((x - state.cx) * scale.km_per_col) ** 2 + ((y - state.cy) * scale.km_per_row) ** 2) ** 0.5)

    nearby = [
        (distance_km(poi.x, poi.y), index, poi) for index, (poi, _geometry) in enumerate(site_pois(world, config))
    ]
    for distance, _index, poi in sorted(nearby, key=lambda found: (found[0], found[1])):
        if distance > radius_km:
            return
        site_plan(poi, 0, config, world)  # built once, then a cache hit
        yield
