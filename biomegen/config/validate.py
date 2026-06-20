"""Validation / coercion of a merged configuration tree.

A single sweep that (a) coerces ergonomic input forms into canonical ones (e.g. ``"#rrggbb"`` ->
``[r, g, b]``) and (b) clamps a few values into legal ranges, **accumulating every problem** before
raising. Collecting all errors (rather than dying on the first) means a user fixing their TOML sees
every issue at once. Validation is intentionally light-touch: it guards the things that would crash a
generation stage, not every conceivable value.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


class ConfigError(ValueError):
    """Raised when the merged config has one or more problems. Message lists them all."""


def _coerce_color(value: Any) -> Tuple[int, int, int]:
    """Coerce a colour given as ``[r, g, b]`` or ``"#rrggbb"`` into a clamped int triple."""
    if isinstance(value, str):
        s = value.strip().lstrip("#")
        if len(s) != 6:
            raise ValueError(f"invalid hex colour {value!r}")
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    else:
        seq = list(value)
        if len(seq) != 3:
            raise ValueError(f"colour must have 3 components, got {value!r}")
        r, g, b = (int(c) for c in seq)
    clamp = lambda c: max(0, min(255, c))  # noqa: E731 - tiny local helper
    return (clamp(r), clamp(g), clamp(b))


def _clamp(node: Dict[str, Any], key: str, lo: float, hi: float, errors: List[str], where: str) -> None:
    """Clamp ``node[key]`` into [lo, hi] if present and numeric; record a note if it was out of range."""
    if key not in node:
        return
    try:
        val = float(node[key])
    except (TypeError, ValueError):
        errors.append(f"{where}.{key} must be a number, got {node[key]!r}")
        return
    clamped = max(lo, min(hi, val))
    if clamped != val:
        # Not fatal - clamp and keep the original numeric type sense (int stays int).
        node[key] = int(clamped) if isinstance(node[key], int) else clamped


def _validate_biome_names(cfg: Dict[str, Any], errors: List[str]) -> None:
    """Check that every biome name used in config matches a :class:`~biomegen.world.tile.Biome` member.

    Biomes are an ``IntEnum`` internally; config refers to them by lower-case name. Validating those
    names here (rather than failing deep inside a generation stage) catches typos and makes it
    obvious which biomes exist when adding new ones.
    """
    from ..world.tile import BIOME_BY_NAME  # local import: avoids any import-order coupling

    valid = set(BIOME_BY_NAME)

    def check(name: object, where: str) -> None:
        if not isinstance(name, str) or name.lower() not in valid:
            errors.append(f"{where}: unknown biome {name!r} (valid: {', '.join(sorted(valid))})")

    biomes = cfg.get("biomes", {})
    for ri, row in enumerate(biomes.get("matrix", []) or []):
        for name in row:
            check(name, f"biomes.matrix[{ri}]")

    render = cfg.get("render", {})
    for name in render.get("palette", {}) or {}:
        check(name, "render.palette")
    for name in render.get("glyphs", {}) or {}:
        check(name, "render.glyphs")

    for gi, group in enumerate(cfg.get("regions", {}).get("similarity_groups", []) or []):
        for name in group:
            check(name, f"regions.similarity_groups[{gi}]")

    for kind, rule in (cfg.get("poi", {}).get("types", {}) or {}).items():
        for name in rule.get("biomes", []) or []:
            check(name, f"poi.types.{kind}.biomes")


def validate(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and coerce ``cfg`` in place, returning it. Raise :class:`ConfigError` on any problem."""
    errors: List[str] = []

    # --- world dimensions must be positive integers ---
    world = cfg.get("world", {})
    for dim in ("width", "height"):
        try:
            if int(world.get(dim, 1)) <= 0:
                errors.append(f"world.{dim} must be a positive integer")
        except (TypeError, ValueError):
            errors.append(f"world.{dim} must be an integer, got {world.get(dim)!r}")
    _clamp(world, "sea_level", 0.0, 1.0, errors, "world")
    _clamp(world, "min_land_fraction", 0.0, 1.0, errors, "world")
    if world.get("size_mode") not in (None, "fixed", "auto"):
        errors.append("world.size_mode must be 'fixed' or 'auto'")

    # --- probabilities in [0, 1] ---
    roads = cfg.get("roads", {})
    for key in ("civilized_connect_prob", "uncivilized_connect_prob", "extra_edge_prob", "road_discount"):
        _clamp(roads, key, 0.0, 1.0, errors, "roads")

    biomes = cfg.get("biomes", {})
    for key in ("beach_max", "mountain_min", "snow_min", "snow_temp"):
        _clamp(biomes, key, 0.0, 1.0, errors, "biomes")

    climate = cfg.get("climate", {})
    for key in ("equator_temp", "pole_temp", "coastal_bias"):
        _clamp(climate, key, 0.0, 1.0, errors, "climate")
    if climate.get("orientation") not in (None, "equator-center", "north-pole-top"):
        errors.append("climate.orientation must be 'equator-center' or 'north-pole-top'")

    # --- colour coercion for the render palette ---
    render = cfg.get("render", {})
    palette = render.get("palette", {})
    for name, value in list(palette.items()):
        try:
            palette[name] = list(_coerce_color(value))
        except ValueError as exc:
            errors.append(f"render.palette.{name}: {exc}")

    # --- every biome name referenced anywhere in config must be a real Biome enum member ---
    _validate_biome_names(cfg, errors)

    # --- the Whittaker matrix must be rectangular and band-aligned ---
    matrix = biomes.get("matrix")
    temp_bands = biomes.get("temp_bands", [])
    moisture_bands = biomes.get("moisture_bands", [])
    if matrix is not None:
        expected_rows = len(temp_bands) + 1
        expected_cols = len(moisture_bands) + 1
        if len(matrix) != expected_rows:
            errors.append(f"biomes.matrix has {len(matrix)} rows but temp_bands implies {expected_rows}")
        for ri, row in enumerate(matrix):
            if len(row) != expected_cols:
                errors.append(f"biomes.matrix row {ri} has {len(row)} cols but moisture_bands implies {expected_cols}")

    if errors:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
    return cfg
