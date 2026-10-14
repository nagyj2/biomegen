"""Stage 1: terrain - landmasses, mountain belts, sea level and heights in metres.

Ported from the reference generator's ``_elevation`` (``docs/reference/worldgen.py``), vectorised:

1. **Style.** A row of ``tables.styles`` (continents, pangaea, archipelago, islands) sets the land
   fraction, the base feature size and how the noise fields are blended.
2. **Raw height.** Domain-warped fBm (base + coarse continent field), an optional pull toward the map
   centre (pangaea) or toward random island blobs (islands), then **mountain belts**: ridged uplift along
   the winding zero-crossings of a coarse fBm, switched on and off by a mask field. Every noise field is
   sampled in km (:func:`~biomegen.util.noise.km_grid`), so features are round on anisotropic cells.
3. **Ocean frame.** Height drops near the map edges so the world is framed by sea.
4. **Rank-based sea level.** The sea level is the height quantile that leaves exactly the style's land
   fraction above water, so every seed has the land it asks for.
5. **Metres.** Land heights follow a hypsometric curve over height rank (most land is low, a few cells
   are high summits); sea depth grows with the normalised sea-floor height.

Writes ``elevation_m``, ``water_type`` (every sea cell is salt, inland seas included), ``biome`` (deep
sea, or a land placeholder the biomes stage replaces) and ``dist_to_ocean`` (km, aspect-aware, for
settlement and POI scoring).
"""

from __future__ import annotations

import random

import numpy as np

from ...config.model import Config
from ...util import geometry as geo
from ...util import noise, rng
from ...world.tile import Biome, WaterType
from ...world.world import World


def pick_style(config: Config, stream: random.Random) -> str:
    """Return the terrain style name: ``terrain.style``, or a weighted draw from ``tables.styles``."""
    style = str(config.get("terrain.style"))
    if style != "seed":
        return style
    styles = config.get("tables.styles")
    names = [name for name in sorted(styles) if float(styles[name]["weight"]) > 0]
    weights = [float(styles[name]["weight"]) for name in names]
    return stream.choices(names, weights=weights)[0]


def _sample(
    config: Config,
    seed: int,
    stream: random.Random,
    label: str,
    xs: np.ndarray,
    ys: np.ndarray,
    feature_km: float,
) -> tuple[noise.Sampler, np.ndarray, np.ndarray]:
    """Return a seeded sampler for ``label`` and the km coordinates rescaled to ``feature_km``, offset.

    The random offset moves each field off the noise lattice, so the fields' zero lines do not align.
    """
    sampler = noise.get_sampler(str(config.get("terrain.noise_backend")), rng.derive_int(seed, "terrain", label))
    ox, oy = stream.uniform(0.0, 256.0), stream.uniform(0.0, 256.0)
    return sampler, xs / feature_km + ox, ys / feature_km + oy


def _raw_height(world: World, config: Config, seed: int, stream: random.Random, style: dict) -> np.ndarray:
    """Return the unnormalised height field for ``style`` (sea level not yet applied)."""
    t = config.section("terrain")
    gain = float(t.get("fbm_gain"))
    lacunarity = float(t.get("fbm_lacunarity"))
    width_km = world.width * world.km_per_col
    height_km = world.height * world.km_per_row
    xs, ys = noise.km_grid((world.height, world.width), world.scale, 1.0)

    def fbm(sampler: noise.Sampler, cx: np.ndarray, cy: np.ndarray, octaves: int) -> np.ndarray:
        return noise.fbm(sampler, cx, cy, octaves=octaves, persistence=gain, lacunarity=lacunarity)

    # Domain warp (one field, two offsets) twists coastlines into peninsulas and gulfs.
    warp, wcx, wcy = _sample(config, seed, stream, "warp", xs, ys, float(t.get("warp_feature_km")))
    warp_octaves = int(t.get("warp_octaves"))
    warp_km = float(t.get("warp_km"))
    wx = xs + warp_km * fbm(warp, wcx, wcy, warp_octaves)
    wy = ys + warp_km * fbm(warp, wcx + 91.0, wcy + 37.0, warp_octaves)

    base, bcx, bcy = _sample(config, seed, stream, "base", wx, wy, float(style["base_feature_km"]))
    height = float(style["base_weight"]) * fbm(base, bcx, bcy, int(t.get("base_octaves")))
    cont, ccx, ccy = _sample(config, seed, stream, "continent", wx, wy, float(t.get("continent_feature_km")))
    height += float(style["continent_weight"]) * fbm(cont, ccx, ccy, int(t.get("continent_octaves")))

    # Pangaea: pull land toward the map centre (unwarped elliptical distance, 1 at the edge midpoints).
    centre = np.hypot((xs - width_km / 2) / (width_km / 2), (ys - height_km / 2) / (height_km / 2))
    height += float(style["centre_weight"]) * (float(t.get("centre_radius")) - centre)

    # Islands: land rises around random blobs (drawn for every style so the stream stays aligned).
    lo, hi = (int(v) for v in t.get("blob_count"))
    span_lo, span_hi = (float(v) for v in t.get("blob_span"))
    radius_lo, radius_hi = (float(v) for v in t.get("blob_radius_km"))
    blob = np.full(xs.shape, -np.inf)
    for _ in range(stream.randint(lo, hi)):
        bx = stream.uniform(span_lo, span_hi) * width_km
        by = stream.uniform(span_lo, span_hi) * height_km
        radius = stream.uniform(radius_lo, radius_hi)
        blob = np.maximum(blob, 1.0 - np.hypot(wx - bx, wy - by) / radius)
    height += float(style["blob_weight"]) * np.maximum(blob, float(t.get("blob_floor")))

    # Mountain belts: ridged uplift along winding bands, strong where the mask field is high.
    belt, ecx, ecy = _sample(config, seed, stream, "belt", wx, wy, float(t.get("belt_feature_km")))
    line = noise.belt_lines(belt, ecx, ecy, width=float(t.get("belt_width")), persistence=gain, lacunarity=lacunarity)
    mask, mcx, mcy = _sample(config, seed, stream, "belt_mask", wx, wy, float(t.get("belt_mask_feature_km")))
    strength = np.clip(float(t.get("belt_mask_bias")) + float(t.get("belt_mask_gain")) * fbm(mask, mcx, mcy, 2), 0, 1)
    ridge, rcx, rcy = _sample(config, seed, stream, "ridge", wx, wy, float(t.get("ridge_feature_km")))
    ridged = noise.ridged(ridge, rcx, rcy, octaves=int(t.get("ridge_octaves")))
    mix = float(t.get("belt_ridge_mix"))
    belts = line ** float(t.get("belt_sharpness")) * ((1.0 - mix) + mix * ridged) * strength
    height += float(t.get("belt_height")) * belts + float(t.get("ridge_height")) * ridged

    # Ocean frame: within edge_margin of an edge (as a fraction of the half-map), push the height down.
    h, w = world.height, world.width
    col = np.arange(w, dtype=np.float64)
    row = np.arange(h, dtype=np.float64)
    edge = np.minimum(
        (np.minimum(col, w - 1 - col) / (w * 0.5))[None, :],
        (np.minimum(row, h - 1 - row) / (h * 0.5))[:, None],
    )
    margin = float(t.get("edge_margin"))
    if margin > 0:
        inside = np.clip((margin - edge) / margin, 0.0, None)
        height -= inside**2 * float(t.get("edge_drop"))
    return height


def _metres(height: np.ndarray, land: np.ndarray, config: Config, stream: random.Random) -> np.ndarray:
    """Convert sea-level-relative ``height`` to metres: hypsometric land, depth-scaled sea floor."""
    t = config.section("terrain")
    max_elev = stream.uniform(*(float(v) for v in t.get("max_elevation_m")))
    max_depth = stream.uniform(*(float(v) for v in t.get("max_depth_m")))
    curve = [(float(r), float(m)) for r, m in t.get("hypsometry")] + [(1.0, max_elev)]
    metres = np.zeros(height.shape, dtype=np.float64)

    land_height = height[land]
    if land_height.size:
        # Rank land cells by height (stable sort: ties keep row-major order) and read the curve.
        order = np.argsort(land_height, kind="stable")
        rank = np.empty(land_height.size, dtype=np.float64)
        rank[order] = np.arange(land_height.size) / max(1, land_height.size - 1)
        metres[land] = np.interp(rank, [r for r, _ in curve], [m for _, m in curve])

    sea_height = height[~land]
    if sea_height.size:
        deepest = float(sea_height.min())
        depth = sea_height / deepest if deepest < 0 else np.zeros_like(sea_height)
        min_depth = float(t.get("min_depth_m"))
        metres[~land] = -(min_depth + (max_depth - min_depth) * depth ** float(t.get("depth_exponent")))
    return metres


def run(world: World, config: Config, seed: int) -> None:
    """Fill ``elevation_m``, the ocean and ``dist_to_ocean`` in place."""
    stream = rng.derive(seed, "terrain")
    style_name = pick_style(config, stream)
    style = config.get(f"tables.styles.{style_name}")
    jitter = float(config.get("terrain.land_fraction_jitter"))
    land_fraction_target = float(np.clip(float(style["land_fraction"]) + stream.uniform(-jitter, jitter), 0.0, 1.0))

    raw = _raw_height(world, config, seed, stream, style)
    # Sea level at the quantile that leaves the target share of cells above it.
    cells = raw.size
    cut = min(cells - 1, int(cells * (1.0 - land_fraction_target)))
    height = raw - float(np.sort(raw, axis=None)[cut])
    land = height > 0

    world.terrain_style = style_name
    world.elevation_m = _metres(height, land, config, stream)
    world.biome[:] = np.where(land, int(Biome.GRASS), int(Biome.DEEP)).astype(np.uint8)
    world.water_type[:] = np.where(land, int(WaterType.NONE), int(WaterType.SALT)).astype(np.uint8)
    world.dist_to_ocean = geo.distance_to(
        ~land, backend=config.get("compute.backend"), metric="euclidean", sampling=world.scale.sampling
    )


def land_fraction(world: World) -> float:
    """Return the fraction of cells that are land (used by the pipeline's land-exists sanity gate)."""
    return float(np.mean(world.water_type == int(WaterType.NONE)))
