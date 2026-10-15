"""Schema validation for the attribute tables under ``tables`` (see ``config/defaults/tables.py``).

Rows are checked against a per-table schema: every key known, every required key present, and each
value of the right kind. Colours are coerced to ``[r, g, b]`` in place.
Problems are appended to the caller's error list so validation still reports everything at once.
"""

from __future__ import annotations

import string
from typing import Any, Dict, List

from .validate import _coerce_color

# Value kinds: "text" any string; "char" exactly one character; "char?" zero or one; "color" an
# [r, g, b] / "#rrggbb" colour; "bool"; "unit" a number in [0, 1]; "cost" a number >= 1;
# "nonneg" a number >= 0; "positive" a number > 0; "rank" an int >= 0; "count" an int >= 1;
# "range" [min, max] ints >= 0; "pair" a [w, h] of numbers > 0; "forms" a non-empty list of name patterns,
# each containing "{n}" exactly once; "ascii_char" / "ascii_char?" / "ascii_text" are "char" / "char?" /
# "text" restricted to 7-bit characters; "factor" one of "none", "moisture", "elevation"; "span" [min, max]
# numbers with 0 <= min <= max; "text_list" a non-empty list of strings; "number" any number; "source", "owner",
# "temper" and "land" one of `POI_SOURCES` / `POI_OWNERS` / `TEMPERS` / `SITE_LANDS`; "floors" a storey count or a
# [min, max] range of them.
_BIOME_ROW = {
    "label": "text",
    "glyph": "char",
    "ascii": "char",
    "fg": "color",
    "bg": "color",
    "water": "bool",
    "sparse": "bool",
    "habitability": "unit",
    "move_cost": "cost",
    "goods": "text",
    "priority": "rank",
}
_RELIEF_ROW = {
    "label": "text",
    "glyph": "char?",
    "ascii": "char?",
    "fg": "color",
    "habitability_mul": "unit",
    "move_cost": "nonneg",
    "goods": "text",
    "priority": "rank",
    "min_elevation_m": "nonneg",
}
_DETAIL_ROW = {
    "floor": "char",
    "floor_ascii": "ascii_char",
    "clutter": "text",
    "clutter_ascii": "ascii_text",
    "density": "unit",
    "factor": "factor",
}
_DETAIL_RELIEF_ROW = {**_DETAIL_ROW, "floor": "char?", "floor_ascii": "ascii_char?"}
_TIER_ROW = {
    "label": "text",
    "rank": "rank",
    "glyph": "char",
    "ascii": "char",
    "fg": "color",
    "bg": "color",
    "pop": "range",
    "floors": "range",
    "spacing_km": "positive",
    "land_per_settlement_km2": "positive",
    "backbone": "bool",
    "dynamic": "bool",
    "connect": "bool",
    "map_marker": "bool",
}
_SITE_ROW = {
    "layout": "text",
    "furniture": "text",
    "extent_tiles": "pair",
    "rows_per_tile": "count",
    "grows_with_pop": "bool",
    "plaza_tiles": "positive",
    "walled": "bool",
}
_POI_ROW = {
    "priority": "rank",
    "source": "source",
    "km2_per_poi": "positive",
    "min_spacing_km": "positive",
    "biomes": "text_list",
    "on_water": "bool",
    "elevation_min_m": "number",
    "elevation_max_m": "number",
    "near_freshwater": "nonneg",
    "coastal": "nonneg",
    "remoteness": "nonneg",
    "wild": "nonneg",
    "seat_remoteness": "nonneg",
    "event_spacing_km": "positive",
    "floors": "floors",
    "owner": "owner",
    "dynamic": "bool",
    "connect": "bool",
    "bandit_strength": "count",
    "bandit_radius_km": "positive",
    "lifespan": "count",
    "purpose": "text",
    "events": "text_list",
    "tags": "text_list",
    "chance": "unit",
    "min_age_years": "nonneg",
    "kind_spacing_km": "positive",
    "holdings": "range",
    "fated": "bool",
    "holding_km": "span",
    "offset_km": "positive",
    "holding_spacing_km": "positive",
    "per_km_of_front": "positive",
    "max_per_event": "count",
}
_POI_FATE_ROW = {"weight": "positive", "sim_only": "bool", "bandits": "bool"}
_POI_SITE_ROW = {
    "kind": "text",
    "temper": "temper",
    "land": "land",
    "min_km": "nonneg",
    "max_km": "positive",
    "connect": "bool",
    "near_freshwater": "nonneg",
    "remoteness": "nonneg",
}
_STYLE_ROW = {
    "label": "text",
    "weight": "nonneg",
    "land_fraction": "unit",
    "base_feature_km": "positive",
    "base_weight": "nonneg",
    "continent_weight": "nonneg",
    "centre_weight": "nonneg",
    "blob_weight": "nonneg",
}

_GEO_NAME_ROW = {
    "forms": "forms",
    "syllables": "range",
}

_REALM_KIND_ROW = {
    "label": "text",
    "strength": "span",
    "rural_per_km2": "span",
    "vassal_chance": "unit",
}
_REALM_FORM_ROW = {
    "kind": "text",
    "habitat": "text",
    "weight": "positive",
    "form": "text",
    "rulers": "text_list",
}
_RELATION_WEIGHT_ROW = {
    "war": "nonneg",
    "rivalry": "nonneg",
    "alliance": "nonneg",
    "trade": "nonneg",
    "none": "nonneg",
}
_REALM_COLOR_ROW = {
    "saturation": "unit",
    "value": "unit",
    "hue_jitter": "unit",
    "hue_offset": "unit",
}
_REASON_ROW = {"templates": "text_list"}
_REASON_TOKEN_ROW = {"fallback": "text"}
_RULING_STYLE_ROW = {"label": "text", "weight": "positive", "strength_mul": "positive", "temper": "temper"}
_CHRONICLE_ROW = {"templates": "text_list", "templates_near": "text_list"}

#: The POI row keys a kind may omit (placement numbers a history-only kind lacks, and the optional seam fields).
_POI_OPTIONAL = frozenset(
    {
        "km2_per_poi",
        "biomes",
        "on_water",
        "elevation_min_m",
        "elevation_max_m",
        "near_freshwater",
        "coastal",
        "remoteness",
        "wild",
        "seat_remoteness",
        "event_spacing_km",
        "bandit_strength",
        "bandit_radius_km",
        "lifespan",
        "purpose",
        "events",
        "tags",
        "chance",
        "min_age_years",
        "kind_spacing_km",
        "holdings",
        "fated",
        "holding_km",
        "offset_km",
        "holding_spacing_km",
        "per_km_of_front",
        "max_per_event",
    }
)

POI_SOURCES = ("location", "history", "both")
POI_OWNERS = ("realm", "wild")
TEMPERS = ("aggressive", "passive")
SITE_LANDS = ("realm", "any")

DETAIL_FACTORS = ("none", "moisture", "elevation")

#: Habitats a realm form may name: the biome groups of ``politics.habitats``, ``high`` (mostly relief) and the
#: ``open`` fallback of a realm with none; ``any`` suits every realm of the kind.
HABITATS = ("any", "dry", "cold", "wood", "high", "open")

#: The ``str.format`` tokens each text of the political tables may use.
_FORM_TOKENS = frozenset({"n", "s"})
_RULER_TOKENS = frozenset({"p", "n"})
_REASON_TOKENS = {
    "war": frozenset({"town", "river", "range", "sea"}),
    "rivalry": frozenset({"town", "river", "range", "sea"}),
    "alliance": frozenset(),
    "trade": frozenset({"goods_a", "goods_b", "short_a", "short_b"}),
}

#: The tokens each chronicle row may use besides {year}; a "near" sentence may also use {near} (and must).
_CHRONICLE_TOKENS = {
    "founding": frozenset({"realm", "short", "ruler", "seat"}),
    "settling": frozenset({"realm", "short", "town"}),
    "conquest": frozenset({"realm", "short", "liege", "liege_short", "ruler"}),
    "war": frozenset({"attacker", "attacker_short", "defender", "defender_short", "reason", "town"}),
    "rivalry": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "treaty_alliance": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "treaty_trade": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "battle": frozenset({"winner", "winner_short", "loser", "loser_short", "reason"}),
    "fall": frozenset({"fallen", "founded"}),
    "succession": frozenset({"realm", "short", "style", "old_style"}),
    "founding_fallen": frozenset({"fallen"}),
    "war_ended": frozenset({"attacker", "attacker_short", "defender", "defender_short"}),
    "war_fallen": frozenset({"attacker", "attacker_short", "defender", "defender_short", "fallen"}),
    "peace": frozenset({"winner", "winner_short", "loser", "loser_short"}),
    "fall_conquered": frozenset({"fallen", "founded", "victor", "victor_short"}),
}

# Table name -> (row schema, keys a row may omit).
SCHEMAS: Dict[str, tuple[Dict[str, str], frozenset[str]]] = {
    "biomes": (_BIOME_ROW, frozenset()),
    "relief": (_RELIEF_ROW, frozenset({"min_elevation_m"})),
    "detail": (_DETAIL_ROW, frozenset()),
    "detail_relief": (_DETAIL_RELIEF_ROW, frozenset()),
    "tiers": (_TIER_ROW, frozenset({"bg", "dynamic", "connect", "map_marker"})),
    "styles": (_STYLE_ROW, frozenset()),
    "geo_names": (_GEO_NAME_ROW, frozenset()),
    "sites": (_SITE_ROW, frozenset({"plaza_tiles", "walled"})),
    "pois": (_POI_ROW, _POI_OPTIONAL),
    "poi_fates": (_POI_FATE_ROW, frozenset()),
    "poi_sites": (_POI_SITE_ROW, frozenset()),
    "realm_kinds": (_REALM_KIND_ROW, frozenset()),
    "realm_forms": (_REALM_FORM_ROW, frozenset()),
    "relation_weights": (_RELATION_WEIGHT_ROW, frozenset()),
    "realm_colors": (_REALM_COLOR_ROW, frozenset()),
    "reasons": (_REASON_ROW, frozenset()),
    "reason_tokens": (_REASON_TOKEN_ROW, frozenset()),
    "ruling_styles": (_RULING_STYLE_ROW, frozenset()),
    "chronicle": (_CHRONICLE_ROW, frozenset({"templates_near"})),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_floors(value: Any) -> bool:
    """A storey count (an int >= 1) or a [min, max] range of them."""
    if isinstance(value, list):
        return (
            len(value) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in value)
            and 1 <= value[0] <= value[1]
        )
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _check_value(row: Dict[str, Any], key: str, kind: str, where: str, errors: List[str]) -> None:
    """Check (and for colours, coerce) ``row[key]`` against ``kind``; record a problem if it fails."""
    value = row[key]
    if kind == "color":
        try:
            row[key] = list(_coerce_color(value))
        except (TypeError, ValueError) as exc:
            errors.append(f"{where}.{key}: {exc}")
        return
    checks = {
        "text": lambda v: isinstance(v, str),
        "char": lambda v: isinstance(v, str) and len(v) == 1,
        "char?": lambda v: isinstance(v, str) and len(v) <= 1,
        "ascii_char": lambda v: isinstance(v, str) and len(v) == 1 and v.isascii(),
        "ascii_char?": lambda v: isinstance(v, str) and len(v) <= 1 and v.isascii(),
        "ascii_text": lambda v: isinstance(v, str) and v.isascii(),
        "factor": lambda v: v in DETAIL_FACTORS,
        "source": lambda v: v in POI_SOURCES,
        "owner": lambda v: v in POI_OWNERS,
        "temper": lambda v: v in TEMPERS,
        "land": lambda v: v in SITE_LANDS,
        "number": _is_number,
        "floors": _is_floors,
        "bool": lambda v: isinstance(v, bool),
        "unit": lambda v: _is_number(v) and 0.0 <= v <= 1.0,
        "cost": lambda v: _is_number(v) and v >= 1.0,
        "nonneg": lambda v: _is_number(v) and v >= 0.0,
        "positive": lambda v: _is_number(v) and v > 0.0,
        "rank": lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
        "count": lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 1,
        "pair": lambda v: isinstance(v, list) and len(v) == 2 and all(_is_number(n) and n > 0.0 for n in v),
        "forms": lambda v: (
            isinstance(v, list) and len(v) > 0 and all(isinstance(f, str) and f.count("{n}") == 1 for f in v)
        ),
        "span": lambda v: isinstance(v, list) and len(v) == 2 and all(_is_number(n) for n in v) and 0.0 <= v[0] <= v[1],
        "text_list": lambda v: isinstance(v, list) and len(v) > 0 and all(isinstance(t, str) for t in v),
        "range": lambda v: (
            isinstance(v, list)
            and len(v) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in v)
            and 0 <= v[0] <= v[1]
        ),
    }
    if not checks[kind](value):
        errors.append(f"{where}.{key}: expected {kind}, got {value!r}")


def _validate_furniture(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the furniture families: each a table of roles, each role a table of weights, every key a furniture cell,
    every weight a number >= 0, no role all zero; and that every site row names a family that exists."""
    from ..world.tile import Cell

    furniture = tables.get("furniture", {})
    if not isinstance(furniture, dict):
        errors.append("tables.furniture must be a table of families")
        return
    names = {cell.name.lower() for cell in Cell}
    for family in sorted(furniture):
        roles = furniture[family]
        if not isinstance(roles, dict):
            errors.append(f"tables.furniture.{family} must be a table of roles")
            continue
        for role in sorted(roles):
            weights = roles[role]
            where = f"tables.furniture.{family}.{role}"
            if not isinstance(weights, dict):
                errors.append(f"{where} must be a table of cell weights")
                continue
            for key in sorted(weights):
                if key not in names:
                    errors.append(f"{where}: unknown cell {key!r}")
                elif not _is_number(weights[key]) or weights[key] < 0:
                    errors.append(f"{where}.{key}: expected a weight >= 0, got {weights[key]!r}")
            if weights and all(_is_number(w) and w == 0 for w in weights.values()):
                errors.append(f"{where}: needs at least one weight above 0")
    sites = tables.get("sites", {})
    if isinstance(sites, dict):
        for kind in sorted(sites):
            row = sites[kind]
            if isinstance(row, dict) and row.get("furniture") not in furniture:
                errors.append(f"tables.sites.{kind}.furniture: no furniture family named {row.get('furniture')!r}")


def _validate_member_tables(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check that the tables keyed by an enum have exactly one row per member, and that tier ranks are unique."""
    from ..world.tile import BIOME_BY_NAME, RELIEF_BY_NAME

    biomes = tables.get("biomes", {})
    if isinstance(biomes, dict) and set(biomes) != set(BIOME_BY_NAME):
        errors.append(f"tables.biomes must have exactly one row per Biome member: {', '.join(sorted(BIOME_BY_NAME))}")

    relief = tables.get("relief", {})
    if isinstance(relief, dict) and set(relief) != set(RELIEF_BY_NAME):
        errors.append(f"tables.relief must have exactly one row per Relief member: {', '.join(sorted(RELIEF_BY_NAME))}")

    detail = tables.get("detail", {})
    if isinstance(detail, dict) and set(detail) != set(BIOME_BY_NAME):
        errors.append(f"tables.detail must have exactly one row per Biome member: {', '.join(sorted(BIOME_BY_NAME))}")

    detail_relief = tables.get("detail_relief", {})
    if isinstance(detail_relief, dict) and set(detail_relief) != set(RELIEF_BY_NAME):
        errors.append(
            f"tables.detail_relief must have exactly one row per Relief member: {', '.join(sorted(RELIEF_BY_NAME))}"
        )

    tiers = tables.get("tiers", {})
    if isinstance(tiers, dict):
        ranks = [row["rank"] for row in tiers.values() if isinstance(row, dict) and isinstance(row.get("rank"), int)]
        if len(ranks) != len(set(ranks)):
            errors.append("tables.tiers: every tier needs a unique rank")


def _tokens(text: str) -> set[str] | None:
    """Return the ``str.format`` field names of ``text``, or ``None`` when it is not a valid format string."""
    try:
        return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}
    except ValueError:
        return None


def _check_tokens(text: object, allowed: frozenset[str], where: str, errors: List[str]) -> None:
    """Record a problem when ``text`` uses a ``{token}`` outside ``allowed`` (or is not a format string)."""
    if not isinstance(text, str):
        return
    used = _tokens(text)
    if used is None:
        errors.append(f"{where}: {text!r} is not a valid pattern")
    elif used - allowed:
        errors.append(f"{where}: unknown token {{{sorted(used - allowed)[0]}}} in {text!r}")


def _validate_realm_forms(forms: Any, errors: List[str]) -> None:
    """Check each realm form's kind, habitat and name tokens, and that every realm kind has a fallback form."""
    from ..world.entities import REALM_KINDS

    if not isinstance(forms, dict):
        return
    usable = {kind: False for kind in REALM_KINDS}
    for name in sorted(forms):
        row = forms[name]
        where = f"tables.realm_forms.{name}"
        if not isinstance(row, dict):
            continue
        if row.get("kind") not in REALM_KINDS:
            errors.append(f"{where}.kind: expected one of {', '.join(REALM_KINDS)}, got {row.get('kind')!r}")
        elif row.get("habitat") in ("any", "open"):
            usable[row["kind"]] = True
        if row.get("habitat") not in HABITATS:
            errors.append(f"{where}.habitat: expected one of {', '.join(HABITATS)}, got {row.get('habitat')!r}")
        _check_tokens(row.get("form"), _FORM_TOKENS, f"{where}.form", errors)
        for ruler in row.get("rulers", []) if isinstance(row.get("rulers"), list) else []:
            _check_tokens(ruler, _RULER_TOKENS, f"{where}.rulers", errors)
    for kind in REALM_KINDS:
        if forms and not usable[kind]:
            errors.append(f"tables.realm_forms: realm kind {kind!r} needs a form with habitat 'any' or 'open'")


def _validate_polity(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the political tables against each other: realm kinds, relation kinds, habitats and text tokens."""
    from ..world.entities import REALM_KINDS, RELATION_KINDS

    kinds = tables.get("realm_kinds", {})
    if isinstance(kinds, dict) and set(kinds) != set(REALM_KINDS):
        errors.append(f"tables.realm_kinds must have exactly one row per realm kind: {', '.join(REALM_KINDS)}")
    _validate_realm_forms(tables.get("realm_forms", {}), errors)
    weights = tables.get("relation_weights", {})
    if isinstance(weights, dict):
        if set(weights) != {"major_pair", "other_pair"}:
            errors.append("tables.relation_weights must have the rows major_pair and other_pair")
        for name in sorted(weights):
            row = weights[name]
            if isinstance(row, dict) and row and all(_is_number(w) and w == 0 for w in row.values()):
                errors.append(f"tables.relation_weights.{name}: needs at least one weight above 0")
    colors = tables.get("realm_colors", {})
    if isinstance(colors, dict) and set(colors) != {"major", "vassal", "city_state", "tribal"}:
        errors.append("tables.realm_colors must have the rows major, vassal, city_state and tribal")
    reasons = tables.get("reasons", {})
    if isinstance(reasons, dict):
        if set(reasons) != set(RELATION_KINDS):
            errors.append(f"tables.reasons must have exactly one row per relation kind: {', '.join(RELATION_KINDS)}")
        for name in sorted(reasons):
            row = reasons[name]
            if isinstance(row, dict) and isinstance(row.get("templates"), list) and name in _REASON_TOKENS:
                for template in row["templates"]:
                    _check_tokens(template, _REASON_TOKENS[name], f"tables.reasons.{name}.templates", errors)
    reason_tokens = tables.get("reason_tokens", {})
    if isinstance(reason_tokens, dict) and set(reason_tokens) != {"town", "river", "range", "sea"}:
        errors.append("tables.reason_tokens must have the rows town, river, range and sea")


def _validate_pois(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the history keys of the POI kinds: known event kinds, known styles in `to:` / `from:` tags, a history kind
    with events, and every kind with sites covering both tempers."""
    from ..world.entities import EVENT_KINDS  # local import: avoids import-order coupling

    pois, styles = tables.get("pois", {}), tables.get("ruling_styles", {})
    if not isinstance(pois, dict) or not isinstance(styles, dict):
        return
    for kind in sorted(pois):
        row = pois[kind]
        if not isinstance(row, dict):
            continue
        where = f"tables.pois.{kind}"
        for event in row.get("events", []) if isinstance(row.get("events"), list) else []:
            if event not in EVENT_KINDS:
                errors.append(f"{where}.events: unknown event kind {event!r} (valid: {', '.join(EVENT_KINDS)})")
        for tag in row.get("tags", []) if isinstance(row.get("tags"), list) else []:
            side, _, style = str(tag).partition(":")
            if side in ("to", "from") and style not in styles:
                errors.append(f"{where}.tags: {tag!r} names no ruling style")
        if row.get("source") == "history" and not row.get("events"):
            errors.append(f"{where}: a history kind needs events")
    sites = tables.get("poi_sites", {})
    if not isinstance(sites, dict):
        return
    tempers: Dict[str, set] = {}
    for name in sorted(sites):
        row = sites[name]
        if not isinstance(row, dict):
            continue
        if row.get("kind") not in pois:
            errors.append(f"tables.poi_sites.{name}.kind: no POI kind named {row.get('kind')!r}")
        if isinstance(row.get("min_km"), (int, float)) and isinstance(row.get("max_km"), (int, float)):
            if row["min_km"] >= row["max_km"]:
                errors.append(f"tables.poi_sites.{name}: min_km must be below max_km")
        tempers.setdefault(str(row.get("kind")), set()).add(row.get("temper"))
    for kind in sorted(tempers):
        if tempers[kind] != set(TEMPERS):
            errors.append(f"tables.poi_sites: kind {kind!r} needs a site for each temper ({', '.join(TEMPERS)})")


def _validate_chronicle(chronicle: Any, errors: List[str]) -> None:
    """Check the chronicle rows: exactly the known rows, only that row's tokens, and {near} only where it belongs."""
    if not isinstance(chronicle, dict):
        return
    if set(chronicle) != set(_CHRONICLE_TOKENS):
        errors.append(f"tables.chronicle must have exactly the rows: {', '.join(_CHRONICLE_TOKENS)}")
    for name in sorted(set(chronicle) & set(_CHRONICLE_TOKENS)):
        row = chronicle[name]
        if not isinstance(row, dict):
            continue
        allowed = _CHRONICLE_TOKENS[name] | {"year"}
        for key, extra in (("templates", frozenset()), ("templates_near", frozenset({"near"}))):
            texts = row.get(key)
            for text in texts if isinstance(texts, list) else []:
                where = f"tables.chronicle.{name}.{key}"
                _check_tokens(text, allowed | extra, where, errors)
                if key == "templates_near" and isinstance(text, str) and "near" not in (_tokens(text) or set()):
                    errors.append(f"{where}: {text!r} must use {{near}}")


def validate_tables(cfg: Dict[str, Any], errors: List[str]) -> None:
    """Validate every row of every table under ``cfg["tables"]``, appending problems to ``errors``."""

    tables = cfg.get("tables", {})
    for table_name in sorted(tables):
        rows = tables[table_name]
        if table_name == "furniture":
            continue  # free-form weights, checked by _validate_furniture
        if table_name not in SCHEMAS:
            errors.append(f"tables.{table_name}: unknown table (valid: {', '.join(sorted(SCHEMAS))})")
            continue
        if not isinstance(rows, dict):
            errors.append(f"tables.{table_name} must be a table of rows")
            continue
        fields, optional = SCHEMAS[table_name]
        for row_name in sorted(rows):
            row = rows[row_name]
            where = f"tables.{table_name}.{row_name}"
            if not isinstance(row, dict):
                errors.append(f"{where} must be a table")
                continue
            for key in sorted(set(row) - set(fields)):
                errors.append(f"{where}: unknown key {key!r}")
            for key in sorted(set(fields) - set(row) - optional):
                errors.append(f"{where}: missing key {key!r}")
            for key in sorted(set(fields) & set(row)):
                _check_value(row, key, fields[key], where, errors)

    _validate_member_tables(tables, errors)
    _validate_furniture(tables, errors)
    _validate_polity(tables, errors)
    _validate_chronicle(tables.get("chronicle", {}), errors)
    _validate_pois(tables, errors)

    styles = tables.get("styles", {})
    style = cfg.get("terrain", {}).get("style")
    if isinstance(styles, dict) and style is not None and style != "seed" and style not in styles:
        errors.append(f"terrain.style must be 'seed' or a style name ({', '.join(sorted(styles))}), got {style!r}")
    if isinstance(styles, dict) and style == "seed":
        weights = [row.get("weight") for row in styles.values() if isinstance(row, dict)]
        if not any(isinstance(w, (int, float)) and w > 0 for w in weights):
            errors.append("tables.styles: terrain.style = 'seed' needs at least one style with weight > 0")
