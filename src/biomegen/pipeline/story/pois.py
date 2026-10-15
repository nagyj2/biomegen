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

- **tower**, **dungeon** (a ``fall``, a dungeon only a conquered one, each at its ``chance``): placed like a field,
  and bandit-held from the start (the row's ``bandit_strength``): what a fallen realm's land comes to.
- **watchtower** (an ongoing ``war``): up to ``max_per_event`` towers on the war's front, one per ``per_km_of_front``
  of it, on high ground and ``kind_spacing_km`` apart, each held by the realm owning its cell.

- **shrine** (a ``succession`` into a devout style): the best cell, by freshwater and remoteness weights, in the
  ``poi_sites`` band round the realm's seat; the previous ruler's temper picks the site (an aggressive one a quiet
  spot in the realm near the seat, a passive one a cell far off, ``connect = false``).

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
from ..civilization.diplomacy import front_cells
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


def _clear_of_pois(world: World, config: Config, row: dict) -> np.ndarray:
    """Bool grid: where a POI of ``row`` placed from an event keeps its spacing (``event_spacing_km``, else
    ``min_spacing_km``) from every POI placed so far."""
    anywhere = np.zeros((world.height, world.width), dtype=bool)
    for poi in world.pois:
        anywhere[poi.y, poi.x] = True
    if not anywhere.any():
        return np.ones_like(anywhere)
    distance = geo.distance_to(
        anywhere, backend=config.get("compute.backend"), metric="euclidean", sampling=world.scale.sampling
    )
    return distance >= float(row.get("event_spacing_km", row["min_spacing_km"]))


def _near_free_cell(world: World, config: Config, kind: str, event: ChronicleEvent) -> tuple[int, int] | None:
    """Return the free cell nearest the event's cell where a ``kind`` POI may stand, or None.

    A candidate is eligible land (the row's biomes, elevation and footprint), within the row's ``offset_km`` of the
    event, at least ``event_spacing_km`` (else ``min_spacing_km``) from every POI and ``kind_spacing_km`` from every
    other POI of its kind.
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
    mask &= _clear_of_pois(world, config, row)
    same = np.zeros(mask.shape, dtype=bool)
    for poi in world.pois:
        same[poi.y, poi.x] |= poi.kind == kind
    if same.any() and "kind_spacing_km" in row:
        mask &= geo.distance_to(
            same, backend=config.get("compute.backend"), metric="euclidean", sampling=scale.sampling
        ) >= float(row["kind_spacing_km"])
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    best = np.lexsort((xs, ys, km[ys, xs]))[0]
    return int(xs[best]), int(ys[best])


def _place_near_event(world: World, config: Config, seed: int, event: ChronicleEvent, kind: str) -> None:
    """Place a ``kind`` POI (a battlefield, or a bandit tower or dungeon) on the nearest free cell round the event.

    It is dated by the event and holds the row's bandits (a wild kind with a ``bandit_strength``; none for a
    battlefield).
    """
    cell = _near_free_cell(world, config, kind, event)
    if cell is None:
        return
    row = config.get(f"tables.pois.{kind}")
    stream = rng.derive(seed, "poi", kind, "floors", event.id)
    pois.commit(
        world,
        seed,
        kind,
        *cell,
        pois.draw_floors(kind, row, stream),
        connect=bool(row.get("connect", True)),
        founded=event.year,
        bandit_strength=int(row.get("bandit_strength", 0)),
        event_ids=[event.id],
    )


def _place_watchtowers(world: World, config: Config, seed: int, event: ChronicleEvent, plan: PoiPlan) -> None:
    """Place a war's watchtowers on its front, on high ground, spread ``kind_spacing_km`` apart.

    A tower belongs to the realm that owns its cell. It is built within the last ``lifespan`` years (and not before the
    war began), since a later simulation dismantles towers that outlive it.
    """
    row = config.get("tables.pois.watchtower")
    front = np.zeros((world.height, world.width), dtype=bool)
    cells = front_cells(world, *event.realm_ids)
    front[cells // world.width, cells % world.width] = True
    mask = front & pois.eligible_mask(
        world, row, pois.max_footprint(config, "watchtower"), float(config.get("poi.min_footprint_land"))
    )
    mask &= _clear_of_pois(world, config, row)
    rise = world.elevation_m / max(1.0, float(world.elevation_m.max()))
    noise = rng.derive_numpy(seed, "poi", "watchtower", event.id).random(mask.shape) * float(config.get("poi.jitter"))
    placed = [(p.x, p.y) for p in world.pois if p.kind == "watchtower"]
    picks = pois.pick_blue_noise(
        np.where(mask, 1.0 + rise + noise, -np.inf), plan.count, float(row["kind_spacing_km"]), placed, world
    )
    stream = rng.derive(seed, "poi", "watchtower", "built", event.id)
    for x, y in picks:
        age = stream.randint(0, min(int(row["lifespan"]), world.year - event.year))
        pois.commit(
            world,
            seed,
            "watchtower",
            x,
            y,
            pois.draw_floors("watchtower", row, stream),
            connect=bool(row.get("connect", True)),
            founded=world.year - age,
            event_ids=[event.id],
        )


def _place_shrine(
    world: World, config: Config, seed: int, event: ChronicleEvent, plan: PoiPlan, fields: pois.ScoreFields
) -> None:
    """Place the shrine of a succession on the best-scoring cell of its site's band round the realm's seat.

    The site row (``poi_sites``, picked by the previous ruler's temper) gives the distance band from the seat, whether
    the cell must lie in the realm, and the score weights. A realm with no seat, or no free cell in the band, gets none.
    """
    seat = world.realms[plan.realm_id].seat_poi
    if seat < 0:
        return
    row, site = config.get("tables.pois.shrine"), config.get(f"tables.poi_sites.{plan.site}")
    sx, sy = world.pois[seat].x, world.pois[seat].y
    scale = world.scale
    km = np.hypot(
        ((np.arange(world.width) - sx) * scale.km_per_col)[None, :],
        ((np.arange(world.height) - sy) * scale.km_per_row)[:, None],
    )
    mask = pois.eligible_mask(
        world, row, pois.max_footprint(config, "shrine"), float(config.get("poi.min_footprint_land"))
    )
    mask &= (km >= float(site["min_km"])) & (km <= float(site["max_km"])) & _clear_of_pois(world, config, row)
    if site["land"] == "realm":
        mask &= world.realm_id == plan.realm_id
    noise = rng.derive_numpy(seed, "poi", "shrine", event.id).random(mask.shape) * float(config.get("poi.jitter"))
    score = 1.0 + float(site["near_freshwater"]) * fields.fresh + float(site["remoteness"]) * fields.remote
    picks = pois.pick_blue_noise(np.where(mask, score + noise, -np.inf), 1, 0.0, [], world)
    if picks:
        stream = rng.derive(seed, "poi", "shrine", "floors", event.id)
        pois.commit(
            world,
            seed,
            "shrine",
            *picks[0],
            pois.draw_floors("shrine", row, stream),
            connect=bool(site["connect"]),
            founded=event.year,
            event_ids=[event.id],
        )


def run(world: World, config: Config, seed: int) -> None:
    """Place the POIs of the world, mutating ``world`` in place."""
    dawn = config.get("history.start") == "dawn"
    if not dawn:
        score = habitability(world, config, seed) if world.fallen_realms else None
        fields: list[pois.ScoreFields] = []

        def _fields() -> pois.ScoreFields:
            """The score weight grids, computed the first time a shrine needs them."""
            if not fields:
                fields.append(pois.score_fields(world, config))
            return fields[0]

        for event in world.chronicle:
            for plan in poi_for_event(world, config, seed, event):
                if plan.kind == "ruin" and score is not None:
                    _place_ruins(world, config, seed, event, plan, score)
                elif plan.kind in ("battlefield", "tower", "dungeon"):
                    _place_near_event(world, config, seed, event, plan.kind)
                elif plan.kind == "watchtower":
                    _place_watchtowers(world, config, seed, event, plan)
                elif plan.kind == "shrine":
                    _place_shrine(world, config, seed, event, plan, _fields())
    pois.place_by_location(world, config, seed, ("both",) if dawn else ("location", "both"))
