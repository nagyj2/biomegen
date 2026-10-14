"""Schema validation for the attribute tables under ``tables`` (see ``config/defaults/tables.py``).

Rows are checked against a per-table schema: every key known, every required key present, and each
value of the right kind. Colours are coerced to ``[r, g, b]`` in place, as for ``render.palette``.
Problems are appended to the caller's error list so validation still reports everything at once.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .validate import _coerce_color

# Value kinds: "text" any string; "char" exactly one character; "char?" zero or one; "color" an
# [r, g, b] / "#rrggbb" colour; "bool"; "unit" a number in [0, 1]; "cost" a number >= 1;
# "nonneg" a number >= 0; "positive" a number > 0; "rank" an int >= 0; "count" an int >= 1;
# "range" [min, max] ints >= 0; "pair" a [w, h] of numbers > 0; "forms" a non-empty list of name patterns,
# each containing "{n}" exactly once; "ascii_char" / "ascii_char?" / "ascii_text" are "char" / "char?" /
# "text" restricted to 7-bit characters; "factor" one of "none", "moisture", "elevation".
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
    "spacing_km": "positive",
    "land_per_settlement_km2": "positive",
    "backbone": "bool",
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

DETAIL_FACTORS = ("none", "moisture", "elevation")

# Table name -> (row schema, keys a row may omit).
SCHEMAS: Dict[str, tuple[Dict[str, str], frozenset[str]]] = {
    "biomes": (_BIOME_ROW, frozenset()),
    "relief": (_RELIEF_ROW, frozenset({"min_elevation_m"})),
    "detail": (_DETAIL_ROW, frozenset()),
    "detail_relief": (_DETAIL_RELIEF_ROW, frozenset()),
    "tiers": (_TIER_ROW, frozenset({"bg"})),
    "styles": (_STYLE_ROW, frozenset()),
    "geo_names": (_GEO_NAME_ROW, frozenset()),
    "sites": (_SITE_ROW, frozenset({"plaza_tiles", "walled"})),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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

    styles = tables.get("styles", {})
    style = cfg.get("terrain", {}).get("style")
    if isinstance(styles, dict) and style is not None and style != "seed" and style not in styles:
        errors.append(f"terrain.style must be 'seed' or a style name ({', '.join(sorted(styles))}), got {style!r}")
    if isinstance(styles, dict) and style == "seed":
        weights = [row.get("weight") for row in styles.values() if isinstance(row, dict)]
        if not any(isinstance(w, (int, float)) and w > 0 for w in weights):
            errors.append("tables.styles: terrain.style = 'seed' needs at least one style with weight > 0")
