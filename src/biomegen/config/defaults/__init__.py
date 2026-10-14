"""The authoritative in-code default configuration.

:data:`DEFAULTS` mirrors the structure of ``config.toml`` exactly. Every controllable value in the
program has an entry here, so the application runs correctly with zero config present and a user's
TOML only needs to specify the handful of keys they want to override. Keep this in sync with
``config.example.toml`` (the example is generated to match these values).

Conventions:
    * Physical fields carry units: heights in m, temperatures in °C, rain in mm, distances in km.
    * Probabilities are in [0, 1]; clamped during validation.
    * Colours are ``[r, g, b]`` 0-255 triples (TOML may also give ``"#rrggbb"``; validation coerces).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from . import (
    biomes,
    climate,
    compute,
    controls,
    export,
    general,
    geography,
    hydrology,
    keys,
    naming,
    poi,
    regions,
    render,
    roads,
    settlements,
    sites,
    tables,
    terrain,
    world,
)

# NOTE: this dict is never mutated in place by the rest of the program - callers always work on a
# deep copy (see :func:`get_defaults`). The merge in the loader copies before merging.
DEFAULTS: Dict[str, Any] = {
    "general": general.VALUES,
    "world": world.VALUES,
    "compute": compute.VALUES,
    "terrain": terrain.VALUES,
    "climate": climate.VALUES,
    "hydrology": hydrology.VALUES,
    "biomes": biomes.VALUES,
    "geography": geography.VALUES,
    "regions": regions.VALUES,
    "settlements": settlements.VALUES,
    "sites": sites.VALUES,
    "poi": poi.VALUES,
    "roads": roads.VALUES,
    "naming": naming.VALUES,
    "render": render.VALUES,
    "export": export.VALUES,
    "keys": keys.VALUES,
    "controls": controls.VALUES,
    "tables": tables.VALUES,
}


def get_defaults() -> Dict[str, Any]:
    """Return a deep copy of :data:`DEFAULTS` so callers can merge/mutate without side effects."""
    return deepcopy(DEFAULTS)
