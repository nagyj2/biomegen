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
    except TypeError, ValueError:
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
    from ..world.tile import BIOME_BY_NAME  # local import: avoids import-order coupling

    valid = set(BIOME_BY_NAME)

    def check(name: object, where: str, allowed: set = valid) -> None:
        if not isinstance(name, str) or name.lower() not in allowed:
            errors.append(f"{where}: unknown biome {name!r} (valid: {', '.join(sorted(allowed))})")

    biomes = cfg.get("biomes", {})
    for bi, band in enumerate(biomes.get("bands", []) or []):
        check(band.get("biome"), f"biomes.bands[{bi}].biome")
        for rule in band.get("rain", []) or []:
            check(rule[0] if isinstance(rule, list) and rule else rule, f"biomes.bands[{bi}].rain")
    if "peak_biome" in biomes:
        check(biomes["peak_biome"], "biomes.peak_biome")

    pois = cfg.get("tables", {}).get("pois", {}) or {}
    for kind in sorted(pois):
        rule = pois[kind]
        for name in (rule.get("biomes", []) or []) if isinstance(rule, dict) else []:
            check(name, f"tables.pois.{kind}.biomes")

    for habitat, names in (cfg.get("politics", {}).get("habitats", {}) or {}).items():
        for name in names or []:
            check(name, f"politics.habitats.{habitat}")


def _validate_world(world: Dict[str, Any], errors: List[str]) -> None:
    """Check the ``world`` section: dimensions, extent, latitude settings."""
    # --- world dimensions must be positive integers ---
    for dim in ("width", "height"):
        try:
            if int(world.get(dim, 1)) <= 0:
                errors.append(f"world.{dim} must be a positive integer")
        except TypeError, ValueError:
            errors.append(f"world.{dim} must be an integer, got {world.get(dim)!r}")
    _clamp(world, "min_land_fraction", 0.0, 1.0, errors, "world")
    if world.get("size_mode") not in (None, "fixed", "auto"):
        errors.append("world.size_mode must be 'fixed' or 'auto'")
    size_km = world.get("size_km")
    if size_km is not None and not (
        isinstance(size_km, list)
        and len(size_km) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in size_km)
    ):
        errors.append(f"world.size_km must be two positive numbers [east-west, north-south], got {size_km!r}")
    if world.get("center_lat") != "seed":
        _clamp(world, "center_lat", -90.0, 90.0, errors, "world")
    lat_range = world.get("center_lat_range_deg")
    if lat_range is not None and not (
        isinstance(lat_range, list)
        and len(lat_range) == 2
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in lat_range)
        and 0 <= lat_range[0] <= lat_range[1] <= 89
    ):
        errors.append(f"world.center_lat_range_deg must be [min, max] with 0 <= min <= max <= 89, got {lat_range!r}")


def _validate_history(history: Dict[str, Any], errors: List[str]) -> None:
    """Check the ``history`` section: the start mode and the event kinds that would otherwise crash the stage."""
    from ..world.entities import EVENT_KINDS, REALM_KINDS

    if history.get("start") not in (None, "present", "dawn"):
        errors.append(f"history.start must be 'present' or 'dawn', got {history.get('start')!r}")
    kinds = history.get("kinds")
    if kinds is not None and not (isinstance(kinds, list) and set(kinds) <= set(EVENT_KINDS)):
        errors.append(f"history.kinds must list event kinds from: {', '.join(EVENT_KINDS)}")
    ages = history.get("age_range")
    if ages is not None and not (
        isinstance(ages, dict)
        and set(ages) == set(REALM_KINDS)
        and all(
            isinstance(v, list)
            and len(v) == 2
            and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in v)
            and 0 <= v[0] <= v[1] <= 1
            for v in ages.values()
        )
    ):
        errors.append(f"history.age_range needs a [min, max] within 0..1 for each of: {', '.join(REALM_KINDS)}")
    _clamp(history, "age_area_weight", 0.0, 1.0, errors, "history")
    colors = history.get("colors")
    if colors is not None:
        needed = {"year", "settlement", "place", *EVENT_KINDS}
        if not isinstance(colors, dict) or not needed <= set(colors):
            errors.append(f"history.colors needs a colour for each of: {', '.join(sorted(needed))}")
        else:
            for name in sorted(colors):
                try:
                    colors[name] = list(_coerce_color(colors[name]))
                except (TypeError, ValueError) as exc:
                    errors.append(f"history.colors.{name}: {exc}")


#: The one tint a view may name that is not a ``render.ramps`` entry: realm colours (see ``render/layers/tint.py``).
REALM_TINT = "realm"


def _validate_render_views(render: Dict[str, Any], errors: List[str]) -> None:
    """Check ``render.ramps`` (a World field and ascending stops, colours coerced) and ``render.views``."""
    from ..world.world import World  # local import: avoids import-order coupling

    ramps = render.get("ramps", {}) or {}
    for name, ramp in ramps.items():
        where = f"render.ramps.{name}"
        if not isinstance(ramp, dict):
            errors.append(f"{where} must be a table with field and stops")
            continue
        if ramp.get("field") not in World.FIELDS:
            errors.append(f"{where}.field must be a World array ({', '.join(World.FIELDS)}), got {ramp.get('field')!r}")
        stops = ramp.get("stops")
        if not isinstance(stops, list) or len(stops) < 2:
            errors.append(f"{where}.stops needs at least two [value, colour] stops")
            continue
        values: List[float] = []
        for index, stop in enumerate(stops):
            try:
                value, colour = stop
                values.append(float(value))
                stops[index] = [value, list(_coerce_color(colour))]
            except (TypeError, ValueError) as exc:
                errors.append(f"{where}.stops[{index}]: {exc}")
        if values != sorted(values):
            errors.append(f"{where}.stops must be in ascending value order")
        if "water_color" in ramp:
            try:
                ramp["water_color"] = list(_coerce_color(ramp["water_color"]))
            except (TypeError, ValueError) as exc:
                errors.append(f"{where}.water_color: {exc}")
    for name, view in (render.get("views", {}) or {}).items():
        where = f"render.views.{name}"
        layers = view.get("layers") if isinstance(view, dict) else None
        if not isinstance(layers, list) or not all(isinstance(layer, str) for layer in layers):
            errors.append(f"{where}.layers must be a list of layer names")
        detail_layers = view.get("detail_layers", []) if isinstance(view, dict) else []
        if not isinstance(detail_layers, list) or not all(isinstance(layer, str) for layer in detail_layers):
            errors.append(f"{where}.detail_layers must be a list of layer names")
        tint = view.get("tint", "") if isinstance(view, dict) else ""
        if tint and tint != REALM_TINT and tint not in ramps:
            errors.append(f"{where}.tint {tint!r} is not a render.ramps entry or {REALM_TINT!r}")


def validate(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and coerce ``cfg`` in place, returning it. Raise :class:`ConfigError` on any problem."""
    errors: List[str] = []

    _validate_world(cfg.get("world", {}), errors)

    # --- probabilities in [0, 1] ---
    roads = cfg.get("roads", {})
    for key in ("civilized_connect_prob", "uncivilized_connect_prob", "extra_edge_prob", "road_discount"):
        _clamp(roads, key, 0.0, 1.0, errors, "roads")

    _validate_history(cfg.get("history", {}), errors)
    _validate_render_views(cfg.get("render", {}), errors)
    if cfg.get("controls", {}).get("pan") not in (None, "edge", "centre"):
        errors.append("controls.pan must be 'edge' or 'centre'")

    # --- every biome name referenced anywhere in config must be a real Biome enum member ---
    _validate_biome_names(cfg, errors)

    # --- the attribute tables loaded from biomegen/data/*.toml (local import: tables imports this module) ---
    from .tables import validate_tables

    validate_tables(cfg, errors)

    # --- biome bands must be ordered by temperature so each cell falls in one band ---
    bands = cfg.get("biomes", {}).get("bands", []) or []
    tops = [band.get("max_temp_c") for band in bands if isinstance(band, dict)]
    numeric = [float(t) for t in tops if isinstance(t, (int, float)) and not isinstance(t, bool)]
    if len(numeric) != len(tops) or numeric != sorted(numeric):
        errors.append("biomes.bands must list numeric max_temp_c in ascending order")

    if errors:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(errors))
    return cfg
