"""Defaults for the ``terrain`` section (``pipeline/physical/terrain.py``)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Noise backend selector (see biomegen.util.noise). "perlin" is our deterministic numpy
    # gradient noise and is the reproducibility-guaranteed default.
    "noise_backend": "perlin",
    # Feature sizes are wavelengths in km; values follow the reference generator at its 6000 km width.
    "style": "seed",  # a tables.styles row name, or "seed" to draw one per seed (weighted)
    "land_fraction_jitter": 0.04,  # +- uniform jitter on the style's land fraction, per seed
    "fbm_gain": 0.5,  # amplitude falloff per fBm octave
    "fbm_lacunarity": 2.03,  # frequency growth per fBm octave
    "base_octaves": 6,
    "warp_feature_km": 2400.0,  # wavelength of the coastline-twisting domain warp
    "warp_km": 1200.0,  # warp displacement amplitude
    "warp_octaves": 3,
    "continent_feature_km": 3750.0,  # wavelength of the coarse continent field
    "continent_octaves": 3,
    "centre_radius": 0.6,  # pangaea: normalised centre distance at which the centre term is zero
    "blob_count": [4, 8],  # islands: [min, max] number of island blobs
    "blob_radius_km": [420.0, 1200.0],  # islands: [min, max] blob radius
    "blob_span": [0.15, 0.85],  # islands: blob centres fall in this fraction of the map on each axis
    "blob_floor": -0.3,  # islands: lower clamp of the blob term (keeps seas between blobs shallow)
    # Mountain belts: long winding bands on the zero-crossings of a coarse fBm, ridged and masked.
    "belt_feature_km": 3530.0,
    "belt_width": 0.09,  # band half-width in fBm units (larger = broader belts)
    "belt_height": 0.45,  # belt uplift at full strength
    "belt_sharpness": 1.5,  # exponent on belt strength (higher = narrower crests)
    "belt_ridge_mix": 0.6,  # share of belt uplift modulated by ridged noise (0..1)
    "belt_mask_feature_km": 4615.0,  # wavelength of the field that switches belts on and off
    "belt_mask_bias": 0.5,
    "belt_mask_gain": 2.2,
    "ridge_feature_km": 857.0,  # wavelength of the ridged noise
    "ridge_octaves": 4,
    "ridge_height": 0.07,  # ridged noise added everywhere (rough uplands)
    # Ocean frame: within edge_margin (fraction of the half-map) of an edge, height drops by up to edge_drop.
    "edge_margin": 0.12,
    "edge_drop": 1.2,
    # Hypsometric curve: land height in metres by height rank (0 = lowest land cell, 1 = highest).
    # The top point is added per seed at a height drawn from max_elevation_m.
    "hypsometry": [[0.0, 2.0], [0.4, 180.0], [0.65, 420.0], [0.78, 800.0], [0.91, 1700.0], [0.975, 3200.0]],
    "max_elevation_m": [4300.0, 7400.0],  # [min, max] height of the highest summit
    "max_depth_m": [4500.0, 7500.0],  # [min, max] depth of the deepest sea
    "min_depth_m": 15.0,  # depth of sea cells right at the coastline
    "depth_exponent": 0.85,  # shape of depth with normalised sea-floor height (<1 deepens shelves)
}
