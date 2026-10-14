"""Defaults for the ``terrain`` section (terrain / heightmap)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Noise backend selector (see biomegen.util.noise). "perlin" is our deterministic numpy
    # gradient noise and is the reproducibility-guaranteed default.
    "noise_backend": "perlin",
    "octaves": 7,  # number of fBm octaves summed (more = finer detail)
    "persistence": 0.54,  # amplitude falloff per octave (higher = rougher terrain)
    "lacunarity": 2.0,  # frequency growth per octave
    "scale": 58.0,  # base feature size in tiles (larger = broader landforms)
    "warp_strength": 0.55,  # domain-warp magnitude (higher = more meandering coasts/ridges)
    "warp_scale": 80.0,  # feature size of the warp field
    "warp_octaves": 3,
    "falloff_power": 2.2,  # radial island falloff steepness (lower = broader/larger main island)
    "falloff_strength": 1.0,  # how strongly the falloff pulls edges to ocean (0..1)
    "redistribution": 1.0,  # exponent applied after normalisation (>1 lowers mid heights)
    # Gentle interior lift: elevation = mask * (land_floor + (1-land_floor)*base). A small value
    # nudges the main island slightly larger/solider while keeping terrain variation (so the
    # interior still has hills, valleys and lakes). High values flatten and bloat - keep it low.
    "land_floor": 0.18,
    # --- coastline detail & archipelago shaping (see heightmap.py) ---
    # Coastline irregularity. Applied only NEAR the shore (interior stays solid), so it makes the
    # outline organic/non-round with peninsulas and bays WITHOUT fragmenting the island.
    "coast_detail": 0.42,
    "coast_scale": 20.0,  # feature size of the coastline-detail noise (smaller = finer wiggle)
    # Low-frequency, positive-only land lobes in the OUTER ring -> small satellite islands around
    # the main one (archipelago). 0 gives a single island.
    "archipelago": 0.42,
    "archipelago_scale": 68.0,
}
