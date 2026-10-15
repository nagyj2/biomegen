"""Stage: pois - the wild and history-made points of interest, placed after the history stage.

The stage runs once realms, diplomacy and the chronicle exist, so a POI can follow the world's history and take its
realm by grid lookup. History placement comes first: every event of the finished ledger goes through the rule table
(:func:`.poi_rules.poi_for_event`) and each kind it makes is placed by its own function here:

- **ruin** (a ``fall``): the fallen realm's capital ruin sits exactly on ``FallenRealm.location``; its holdings are
  further ruins in the ``holding_km`` band round it, on eligible land spaced ``holding_spacing_km`` from every POI. Each
  ruin draws a fate from the table's open fates: a plain ruin, or one held by bandits (``bandit_strength`` of the row).
  It is dated with the realm's ``founded`` and ``fell`` and carries the fall event's id.
- **battlefield** (a ``decisive`` battle that passed its chance and age): the nearest free cell round the battle within
  ``offset_km``, at least ``min_spacing_km`` from every POI and ``kind_spacing_km`` from every other battlefield.

The location pass (:func:`biomegen.pipeline.pois.place_by_location`) then fills the rest by score. With
``history.start = "dawn"`` there are no realms and no events, so only the kinds whose ``source`` is "both" are placed,
by location: a few ruins, towers and dungeons already stand at year 0.
"""

from __future__ import annotations

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import rng
from ...world.entities import ChronicleEvent
from ...world.world import World
from .. import pois
from ..civilization.settlements import habitability
from .poi_rules import PoiPlan, poi_for_event


def _holdings(
    world: World, config: Config, seed: int, row: dict, event: ChronicleEvent, count: int, score: np.ndarray
) -> list[tuple[int, int]]:
    """Return up to ``count`` cells for a ruin's holdings: the ``holding_km`` band round the event, best score first."""
    x, y = event.location
    low, high = (float(v) for v in row["holding_km"])
    scale = world.scale
    km = np.hypot(
        ((np.arange(world.width) - x) * scale.km_per_col)[None, :],
        ((np.arange(world.height) - y) * scale.km_per_row)[:, None],
    )
    mask = pois.eligible_mask(
        world, row, pois.max_footprint(config, "ruin"), float(config.get("poi.min_footprint_land"))
    )
    mask &= (km >= low) & (km <= high) & (world.landmass_id == world.landmass_id[y, x])
    noise = rng.derive_numpy(seed, "poi", "holdings", event.id).random(mask.shape) * float(config.get("poi.jitter"))
    placed = [(p.x, p.y) for p in world.pois]
    return pois.pick_blue_noise(
        np.where(mask, score + noise, -np.inf), count, float(row["holding_spacing_km"]), placed, world
    )


def _place_ruins(
    world: World, config: Config, seed: int, event: ChronicleEvent, plan: PoiPlan, score: np.ndarray
) -> None:
    """Place a fall's ruins: the capital on the event's cell, then its holdings, each with its fate."""
    row = config.get("tables.pois.ruin")
    fallen = world.fallen_realms[event.fallen_ids[0]]
    cells = [event.location]
    if plan.count > 1:
        cells += _holdings(world, config, seed, row, event, plan.count - 1, score)
    stream = rng.derive(seed, "poi", "ruin", "floors", event.id)
    for (x, y), fate in zip(cells, plan.fates, strict=False):
        held = bool(config.get(f"tables.poi_fates.{fate}.bandits"))
        pois.commit(
            world,
            seed,
            "ruin",
            x,
            y,
            pois.draw_floors("ruin", row, stream),
            connect=bool(row.get("connect", True)),
            founded=fallen.founded,
            fell=fallen.fell,
            bandit_strength=int(row.get("bandit_strength", 0)) if held else 0,
            event_ids=[event.id],
        )


def _near_free_cell(world: World, config: Config, kind: str, event: ChronicleEvent) -> tuple[int, int] | None:
    """Return the free cell nearest the event's cell where a ``kind`` POI may stand, or None.

    A candidate is eligible land (the row's biomes, elevation and footprint), within the row's ``offset_km`` of the
    event, at least ``min_spacing_km`` from every POI and ``kind_spacing_km`` from every other POI of its kind.
    The nearest wins; ties go to the first in row-major order.
    """
    row = config.get(f"tables.pois.{kind}")
    x, y = event.location
    scale = world.scale
    km = np.hypot(
        ((np.arange(world.width) - x) * scale.km_per_col)[None, :],
        ((np.arange(world.height) - y) * scale.km_per_row)[:, None],
    )
    mask = pois.eligible_mask(world, row, pois.max_footprint(config, kind), float(config.get("poi.min_footprint_land")))
    mask &= km <= float(row["offset_km"])
    backend, sampling = config.get("compute.backend"), scale.sampling
    anywhere = np.zeros(mask.shape, dtype=bool)
    same = np.zeros(mask.shape, dtype=bool)
    for poi in world.pois:
        anywhere[poi.y, poi.x] = True
        same[poi.y, poi.x] |= poi.kind == kind
    if anywhere.any():
        mask &= geo.distance_to(anywhere, backend=backend, metric="euclidean", sampling=sampling) >= float(
            row["min_spacing_km"]
        )
    if same.any() and "kind_spacing_km" in row:
        mask &= geo.distance_to(same, backend=backend, metric="euclidean", sampling=sampling) >= float(
            row["kind_spacing_km"]
        )
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    best = np.lexsort((xs, ys, km[ys, xs]))[0]
    return int(xs[best]), int(ys[best])


def _place_battlefield(world: World, config: Config, seed: int, event: ChronicleEvent) -> None:
    """Place the battlefield of a decisive battle on the nearest free cell round it, if there is one."""
    cell = _near_free_cell(world, config, "battlefield", event)
    if cell is None:
        return
    row = config.get("tables.pois.battlefield")
    stream = rng.derive(seed, "poi", "battlefield", "floors", event.id)
    pois.commit(
        world,
        seed,
        "battlefield",
        *cell,
        pois.draw_floors("battlefield", row, stream),
        connect=bool(row.get("connect", True)),
        founded=event.year,
        event_ids=[event.id],
    )


def run(world: World, config: Config, seed: int) -> None:
    """Place the POIs of the world, mutating ``world`` in place."""
    dawn = config.get("history.start") == "dawn"
    if not dawn:
        score = habitability(world, config, seed) if world.fallen_realms else None
        for event in world.chronicle:
            for plan in poi_for_event(world, config, seed, event):
                if plan.kind == "ruin" and score is not None:
                    _place_ruins(world, config, seed, event, plan, score)
                elif plan.kind == "battlefield":
                    _place_battlefield(world, config, seed, event)
    pois.place_by_location(world, config, seed, ("both",) if dawn else ("location", "both"))
