"""The pure scorer of the placement styles: where a homestead (or a hamlet) of a style would stand.

A style is a row of ``tables.poi_styles``. :func:`style_score` turns it into a score grid: ``-inf`` where the style
may not stand (wrong biome, height, no fresh water or coast in reach, too little dry land for the largest plan it may
grow into, a taken tile, and for a homestead land no realm holds), and elsewhere the weighted sum of the row's terms,
each a ``[0, 1]`` weight with every falloff in km: fresh water, the coast, remoteness from settlements, fertility (the
settlement habitability), roughness of the land, forest cover, closeness to a settlement and to a road. A little seeded
noise breaks ties. :func:`suited_mask` (the cells scoring at least the row's ``min_score``) and :func:`style_count`
(suited land over the kind's ``km2_per_poi``) turn that into a count.

Generation (:func:`place_styles`) and a later simulation's building projects call the same functions. Nothing here
reads or writes beyond the arguments: a simulation passes its own ``realm_id`` and ``road`` grids instead of the
generated ones, and every shared grid is built once in :func:`style_fields`.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from scipy import ndimage

from ...config.model import Config
from ...util import geometry as geo
from ...util import rng
from ...world.tile import RELIEF_NAME, WaterType, biome_from_name
from ...world.world import World
from .. import pois
from ..civilization.settlements import habitability

KINDS = ("homestead", "hamlet")


class StyleFields(NamedTuple):
    """The grids every style scores from, built once per world: km distances and ``[0, 1]`` terms."""

    fresh_km: np.ndarray
    settlement_km: np.ndarray
    road_km: np.ndarray
    fertility: np.ndarray
    roughness: np.ndarray
    forest: np.ndarray
    realm_id: np.ndarray


def _km_to(world: World, config: Config, mask: np.ndarray) -> np.ndarray:
    """Km distance from every cell to the nearest True cell of ``mask`` (``inf`` everywhere when there is none)."""
    return geo.distance_to(
        mask, backend=config.get("compute.backend"), metric="euclidean", sampling=world.scale.sampling
    ).astype(np.float64)


def _forest_share(world: World, config: Config) -> np.ndarray:
    """Share of the land within ``poi.forest_radius_km`` of each cell that wears forest cover (a box average)."""
    names = config.get("poi.forest_biomes")
    wooded = np.isin(world.biome, [int(biome_from_name(name)) for name in names]).astype(np.float64)
    radius = float(config.get("poi.forest_radius_km"))
    scale = world.scale
    size = (max(1, round(2.0 * radius / scale.km_per_row)), max(1, round(2.0 * radius / scale.km_per_col)))
    return np.asarray(ndimage.uniform_filter(wooded, size=size, mode="nearest"), dtype=np.float64)


def style_fields(
    world: World,
    config: Config,
    seed: int,
    *,
    realm_id: np.ndarray | None = None,
    road: np.ndarray | None = None,
) -> StyleFields:
    """Build the shared grids: ``realm_id`` and ``road`` default to the world's own (a simulation passes live ones).

    A settlement for the distance terms is a civilized POI whose tier is a ``near_target`` (a hamlet is not), so
    styles do not cluster round their own hamlets.
    """
    settled = np.zeros((world.height, world.width), dtype=bool)
    for poi in world.pois:
        if poi.civilized and config.get(f"tables.tiers.{poi.kind}.near_target", True):
            settled[poi.y, poi.x] = True
    road_mask = (world.road > 0) if road is None else road.astype(bool)
    fresh = world.water_type == int(WaterType.FRESH)
    return StyleFields(
        fresh_km=_km_to(world, config, fresh),
        settlement_km=_km_to(world, config, settled),
        road_km=_km_to(world, config, road_mask),
        fertility=np.clip(habitability(world, config, seed), 0.0, 1.0).astype(np.float64),
        roughness=1.0 - config.table_array("relief", "habitability_mul", RELIEF_NAME)[world.relief].astype(np.float64),
        forest=_forest_share(world, config),
        realm_id=world.realm_id if realm_id is None else realm_id,
    )


def style_footprint(config: Config, style: str) -> tuple[int, int] | None:
    """Return the largest plan ``(w, h)`` in tiles a ``style`` POI may need.

    That is its homestead site or, for a style that grows, the tier it grows into, whichever is larger each way (so
    growth never lacks room).
    """
    row = config.get(f"tables.poi_styles.{style}")
    sizes = [pois.max_footprint(config, "homestead", style)]
    if "grows_into" in row:
        sizes.append(pois.max_footprint(config, str(row["grows_into"])))
    known = [size for size in sizes if size is not None]
    return (max(w for w, _ in known), max(h for _, h in known)) if known else None


def _closeness(distance_km: np.ndarray, scale_km: float) -> np.ndarray:
    """Map a km distance to a ``[0, 1]`` closeness weight (near is 1); an infinite distance gives 0."""
    with np.errstate(over="ignore"):
        return np.exp(-distance_km / max(scale_km, 1e-6))


def style_score(
    world: World,
    config: Config,
    seed: int,
    style: str,
    kind: str = "homestead",
    *,
    realm_id: np.ndarray | None = None,
    road: np.ndarray | None = None,
    fields: StyleFields | None = None,
) -> np.ndarray:
    """Return the score of a ``kind`` (homestead or hamlet) of ``style`` on every cell, ``-inf`` where it may not stand.

    ``realm_id`` and ``road`` replace the world's grids (a simulation's live ones); ``fields`` are the shared grids when
    the caller scores several styles (they then ignore ``realm_id`` and ``road``). A homestead needs land a realm holds
    (``realm_id >= 0``); a hamlet may stand on free land.
    """
    row = config.get(f"tables.poi_styles.{style}")
    grids = fields or style_fields(world, config, seed, realm_id=realm_id, road=road)
    mask = pois.eligible_mask(world, row, style_footprint(config, style), float(config.get("poi.min_footprint_land")))
    if "needs_freshwater_km" in row:
        mask &= grids.fresh_km <= float(row["needs_freshwater_km"])
    if "needs_coast_km" in row:
        mask &= world.dist_to_ocean <= float(row["needs_coast_km"])
    if kind == "homestead":
        mask &= grids.realm_id >= 0
    fresh_scale = float(config.get("poi.freshwater_scale_km"))
    score = np.zeros(mask.shape, dtype=np.float64)
    score += float(row.get("near_freshwater", 0.0)) * _closeness(grids.fresh_km, fresh_scale)
    score += float(row.get("coastal", 0.0)) * _closeness(world.dist_to_ocean, float(config.get("poi.coastal_scale_km")))
    far = 1.0 - _closeness(grids.settlement_km, float(config.get("poi.remoteness_scale_km")))
    score += float(row.get("remoteness", 0.0)) * far
    score += float(row.get("fertility", 0.0)) * grids.fertility
    score += float(row.get("relief", 0.0)) * grids.roughness
    score += float(row.get("forest", 0.0)) * grids.forest
    if "near_settlement" in row:
        score += float(row["near_settlement"]) * _closeness(grids.settlement_km, float(row["near_settlement_km"]))
    if "near_road" in row:
        score += float(row["near_road"]) * _closeness(grids.road_km, float(row["near_road_km"]))
    noise = rng.derive_numpy(seed, "poi", "style", style, "score").random(mask.shape) * float(config.get("poi.jitter"))
    return np.where(mask, score + noise, -np.inf)


def suited_mask(config: Config, style: str, score: np.ndarray) -> np.ndarray:
    """Bool grid: the cells that suit ``style`` (eligible and scoring at least its ``min_score``)."""
    return np.isfinite(score) & (score >= float(config.get(f"tables.poi_styles.{style}.min_score")))


def style_count(world: World, config: Config, style: str, kind: str, score: np.ndarray) -> int:
    """Return how many ``kind`` POIs of ``style`` the world gets: suited land (km²) over the kind's ``km2_per_poi``.

    Zero when the row has no ``<kind>_km2_per_poi`` (the style makes none of that kind at generation). The result is
    multiplied by ``poi.density`` and rounded.
    """
    per = config.get(f"tables.poi_styles.{style}.{kind}_km2_per_poi", None)
    if per is None:
        return 0
    suited_km2 = float(suited_mask(config, style, score).sum()) * world.scale.cell_area_km2
    return round(suited_km2 / float(per) * float(config.get("poi.density")))
