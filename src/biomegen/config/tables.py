"""Schema validation for the attribute tables under ``tables`` (see ``config/defaults/tables.py``).

Rows are checked against a per-table schema: every key known, every required key present, and each
value of the right kind. Colours are coerced to ``[r, g, b]`` in place.
Problems are appended to the caller's error list so validation still reports everything at once.
"""

from __future__ import annotations

import string
from typing import Any, Dict, List, TypeGuard

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
    "free_fg": "color",
    "hooks_free": "text_list",
    "hooks_remnant": "text_list",
    "near_target": "bool",
    "centre": "text",
    "reserve": "text",
}
_SITE_ROW = {
    "layout": "text",
    "furniture": "text",
    "extent_tiles": "pair",
    "rows_per_tile": "count",
    "grows_with_pop": "bool",
    "plaza_tiles": "positive",
    "walled": "bool",
    "ruin_standing": "unit_pair",
    "ruin_wall_fall": "unit_pair",
    "ruin_extent_share": "positive",
    "dress": "text",
    "specialized": "range",
}

BUILDING_FUNCTIONS = ("housing", "production", "civic")
BUILDING_SHAPES = ("rect", "L", "T")
BUILDING_SITINGS = ("river", "shore", "edge", "any")
SUIT_TERMS = ("fertility", "forest", "roughness", "fresh_water", "coast")
SITE_TAGS = ("port", "river", "lake")  # the traits a POI's ``tags`` may hold (``needs_tag`` of a building kind)
_BUILDING_ROW = {
    "label": "text",
    "rank": "rank",
    "function": "function",
    "rows": "range",
    "width": "span",
    "shapes": "shapes",
    "roles": "text_list",
    "furniture": "text",
    "roof": "roof",
    "capacity_pop": "count",
    "storage": "nonneg",
    "suits": "suits",
    "min_score": "nonneg",
    "max_per_kind": "count",
    "siting": "siting",
    "tries": "count",
    "needs_tag": "site_tag",
    "dress": "text",
    "apron": "rank",
}
#: The keys a function requires of its rows (a production kind also has the optional ``needs_tag`` and ``dress``);
#: no other function may use them.
_BUILDING_KEYS = {
    "housing": frozenset({"capacity_pop", "storage"}),
    "production": frozenset({"suits", "min_score", "max_per_kind", "siting", "tries"}),
    "civic": frozenset({"apron"}),
}
_BUILDING_PRODUCTION_OPTIONAL = frozenset({"needs_tag", "dress"})

DRESS_CONDITIONS = ("standing", "ruin")  # what a dressing is drawn for: a site that stands, a ruin
DRESS_WEAR = ("void", "rubble", "overgrown")  # what a worn dressing cell becomes
_DRESS_ROW = {"variants": "dress_variants", "wear": "dress_wear"}
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
    "names": "forms",
    "names_fallen": "text_list",
    "hooks": "text_list",
    "hooks_near": "text_list",
    "owner": "owner",
    "dynamic": "bool",
    "connect": "bool",
    "bandit_strength": "count",
    "bandit_radius_km": "positive",
    "lifespan": "count",
    "abandon_chance": "nonneg",
    "occupy_years": "floors",
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
    "front_setback_km": "span",
    "origins": "weights",
    "fall_origin": "text",
    "holding_origins": "weights",
    "marker": "bool",
}
_POI_STYLE_ROW = {
    "generated": "bool",
    "dynamic": "bool",
    "grows_into": "text",
    "homestead_km2_per_poi": "positive",
    "hamlet_km2_per_poi": "positive",
    "min_score": "nonneg",
    "min_land": "unit",
    "min_spacing_km": "positive",
    "kind_spacing_km": "positive",
    "biomes": "text_list",
    "elevation_min_m": "number",
    "elevation_max_m": "number",
    "needs_freshwater_km": "positive",
    "needs_coast_km": "positive",
    "near_freshwater": "nonneg",
    "coastal": "nonneg",
    "remoteness": "nonneg",
    "fertility": "nonneg",
    "relief": "nonneg",
    "forest": "nonneg",
    "near_settlement": "nonneg",
    "near_settlement_km": "positive",
    "near_road": "nonneg",
    "near_road_km": "positive",
    "building": "text",
    "names": "forms",
    "hooks_homestead": "text_list",
    "hooks_homestead_near": "text_list",
    "hooks_hamlet": "text_list",
    "hooks_hamlet_near": "text_list",
}
_POI_FATE_ROW = {"weight": "positive", "sim_only": "bool", "bandits": "bool"}
_FREE_FATE_ROW = {"weight": "positive", "sim_only": "bool", "factors": "text_list"}
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
}
_REASON_ROW = {"templates": "text_list"}
_REASON_TOKEN_ROW = {"fallback": "text"}
_RULING_STYLE_ROW = {
    "label": "text",
    "weight": "positive",
    "strength_mul": "positive",
    "temper": "temper",
    "traits": "traits",
}
_CHRONICLE_ROW = {"templates": "text_list", "templates_near": "text_list"}
SECESSION_TERMS = ("proximity", "size", "age", "relation", "prosperity", "leader", "strength")
SECESSION_FORMS = ("offshoot", "split", "defection")
SECESSION_TAGS = ("bitter", "amicable")  # how a break is worded, by the relation between the two sides
_SECESSION_TERM_ROW = {"weight": "nonneg"}
_SECESSION_RELATION_ROW = {"score": "unit", "tag": "secession_tag"}
_SECESSION_FORM_ROW = {"weight": "nonneg"}

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
        "names_fallen",
        "hooks",
        "hooks_near",
        "bandit_strength",
        "bandit_radius_km",
        "lifespan",
        "abandon_chance",
        "occupy_years",
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
        "front_setback_km",
        "origins",
        "fall_origin",
        "holding_origins",
        "marker",
    }
)

#: The style row keys a style may omit: growth, the hamlet count, the optional eligibility and score terms, the texts
#: of the hamlet kind and the ``_near`` variants (``_validate_poi_styles`` checks which the other keys require).
_POI_STYLE_OPTIONAL = frozenset(
    {
        "grows_into",
        "min_land",
        "homestead_km2_per_poi",
        "hamlet_km2_per_poi",
        "kind_spacing_km",
        "elevation_min_m",
        "elevation_max_m",
        "needs_freshwater_km",
        "needs_coast_km",
        "near_freshwater",
        "coastal",
        "remoteness",
        "fertility",
        "relief",
        "forest",
        "near_settlement",
        "near_settlement_km",
        "near_road",
        "near_road_km",
        "building",
        "hooks_homestead_near",
        "hooks_hamlet",
        "hooks_hamlet_near",
    }
)

POI_SOURCES = ("location", "history", "both", "style")
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

#: The tokens a POI kind's names and hooks may use (``names_fallen`` adds ``fallen``, ``hooks_near`` adds ``near``).
_NAME_TOKENS = frozenset({"n", "fort"})
_HOOK_TOKENS = frozenset({"name"})

#: The tokens each chronicle row may use besides {year}; a "near" sentence may also use {near} (and must).
_CHRONICLE_TOKENS = {
    "founding": frozenset({"realm", "short", "ruler", "seat"}),
    "settling": frozenset({"realm", "short", "town"}),
    "expansion": frozenset({"realm", "short", "ruler", "seat"}),
    "expansion_fallen": frozenset({"fallen"}),
    "creation_tower": frozenset({"place"}),
    "creation_dungeon": frozenset({"place"}),
    "creation_watchtower": frozenset({"place"}),
    "abandon_watchtower": frozenset({"place"}),
    "dismantle_watchtower": frozenset({"place"}),
    "occupation_tower": frozenset({"place"}),
    "road_trunk": frozenset({"a", "b"}),
    "road_spur": frozenset({"a"}),
    "founding_predecessor": frozenset({"predecessor"}),
    "settling_free": frozenset({"town"}),
    "settling_remnant": frozenset({"town", "fallen"}),
    "conquest": frozenset({"realm", "short", "liege", "liege_short", "ruler"}),
    "war": frozenset({"attacker", "attacker_short", "defender", "defender_short", "reason", "town"}),
    "rivalry": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "treaty_alliance": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "treaty_trade": frozenset({"a", "a_short", "b", "b_short", "reason"}),
    "battle": frozenset({"winner", "winner_short", "loser", "loser_short", "reason"}),
    "fall": frozenset({"fallen", "founded"}),
    "succession": frozenset({"realm", "short", "style", "old_style", "ruler", "old_ruler"}),
    "founding_fallen": frozenset({"fallen"}),
    "war_ended": frozenset({"attacker", "attacker_short", "defender", "defender_short"}),
    "war_fallen": frozenset({"attacker", "attacker_short", "defender", "defender_short", "fallen"}),
    "peace": frozenset({"winner", "winner_short", "loser", "loser_short"}),
    "fall_conquered": frozenset({"fallen", "founded", "victor", "victor_short"}),
    "secession_offshoot_bitter": frozenset({"realm", "short", "parent", "parent_short", "ruler", "seat"}),
    "secession_offshoot_amicable": frozenset({"realm", "short", "parent", "parent_short", "ruler", "seat"}),
    "secession_split_bitter": frozenset(
        {"predecessor", "realm_a", "short_a", "ruler_a", "realm_b", "short_b", "ruler_b"}
    ),
    "secession_split_amicable": frozenset(
        {"predecessor", "realm_a", "short_a", "ruler_a", "realm_b", "short_b", "ruler_b"}
    ),
    "secession_defection_bitter": frozenset({"town", "realm", "short", "parent", "parent_short"}),
    "secession_defection_amicable": frozenset({"town", "realm", "short", "parent", "parent_short"}),
}

# Table name -> (row schema, keys a row may omit).
SCHEMAS: Dict[str, tuple[Dict[str, str], frozenset[str]]] = {
    "biomes": (_BIOME_ROW, frozenset()),
    "relief": (_RELIEF_ROW, frozenset({"min_elevation_m"})),
    "detail": (_DETAIL_ROW, frozenset()),
    "detail_relief": (_DETAIL_RELIEF_ROW, frozenset()),
    "tiers": (
        _TIER_ROW,
        frozenset(
            {
                "bg",
                "dynamic",
                "connect",
                "map_marker",
                "free_fg",
                "hooks_free",
                "hooks_remnant",
                "near_target",
                "reserve",
            }
        ),
    ),
    "dress": (_DRESS_ROW, frozenset({"variants", "wear"})),
    "buildings": (
        _BUILDING_ROW,
        frozenset(key for keys in _BUILDING_KEYS.values() for key in keys) | _BUILDING_PRODUCTION_OPTIONAL,
    ),
    "styles": (_STYLE_ROW, frozenset()),
    "geo_names": (_GEO_NAME_ROW, frozenset()),
    "sites": (
        _SITE_ROW,
        frozenset(
            {"plaza_tiles", "walled", "ruin_standing", "ruin_wall_fall", "ruin_extent_share", "dress", "specialized"}
        ),
    ),
    "pois": (_POI_ROW, _POI_OPTIONAL),
    "poi_fates": (_POI_FATE_ROW, frozenset()),
    "free_fates": (_FREE_FATE_ROW, frozenset()),
    "poi_sites": (_POI_SITE_ROW, frozenset()),
    "poi_styles": (_POI_STYLE_ROW, _POI_STYLE_OPTIONAL),
    "realm_kinds": (_REALM_KIND_ROW, frozenset()),
    "realm_forms": (_REALM_FORM_ROW, frozenset()),
    "relation_weights": (_RELATION_WEIGHT_ROW, frozenset()),
    "realm_colors": (_REALM_COLOR_ROW, frozenset()),
    "reasons": (_REASON_ROW, frozenset()),
    "reason_tokens": (_REASON_TOKEN_ROW, frozenset()),
    "ruling_styles": (_RULING_STYLE_ROW, frozenset()),
    "chronicle": (_CHRONICLE_ROW, frozenset({"templates_near"})),
    "secession_terms": (_SECESSION_TERM_ROW, frozenset()),
    "secession_relations": (_SECESSION_RELATION_ROW, frozenset()),
    "secession_forms": (_SECESSION_FORM_ROW, frozenset()),
}


def _is_number(value: Any) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_traits(value: Any) -> bool:
    """A ruler's trait values: exactly the names of ``world.entities.TRAITS``, each a number in [0, 1]."""
    from ..world.entities import TRAITS  # local import: avoids import-order coupling

    return (
        isinstance(value, dict)
        and set(value) == set(TRAITS)
        and all(_is_number(v) and 0.0 <= v <= 1.0 for v in value.values())
    )


def _is_floors(value: Any) -> bool:
    """A storey count (an int >= 1) or a [min, max] range of them."""
    if isinstance(value, list):
        return (
            len(value) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in value)
            and 1 <= value[0] <= value[1]
        )
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


_VARIANT_KEYS = frozenset({"cell", "glyph", "ascii", "color", "label", "rank", "standing", "ruin", "kinds"})
_VARIANT_LOOK = ("glyph", "ascii", "color", "label", "rank")


def _check_variant(variant: Any, where: str, errors: List[str]) -> None:
    """Check one dress variant: an existing cell or a look of its own, a weight per condition, optional kinds."""
    from ..world.tile import Cell

    if not isinstance(variant, dict):
        errors.append(f"{where}: expected a table")
        return
    for key in sorted(set(variant) - _VARIANT_KEYS):
        errors.append(f"{where}: unknown key {key!r}")
    own = [key for key in _VARIANT_LOOK if key in variant]
    if "cell" in variant:
        if own:
            errors.append(f"{where}: has a cell and a look of its own ({', '.join(own)}); needs one or the other")
        elif not (isinstance(variant["cell"], str) and variant["cell"].upper() in Cell.__members__):
            errors.append(f"{where}.cell: no cell named {variant['cell']!r}")
    elif len(own) != len(_VARIANT_LOOK):
        missing = [key for key in _VARIANT_LOOK if key not in variant]
        errors.append(f"{where}: needs a cell, or a look of its own: missing {', '.join(missing)}")
    else:
        _check_roof_like(variant, where, errors)
    for condition in DRESS_CONDITIONS:
        raw = variant.get(condition)
        if not (_is_number(raw) and raw >= 0.0):
            errors.append(f"{where}.{condition}: expected a weight >= 0, got {raw!r}")
    kinds = variant.get("kinds")
    if "kinds" in variant and not (isinstance(kinds, list) and kinds and all(isinstance(k, str) for k in kinds)):
        errors.append(f"{where}.kinds: expected a non-empty list of POI kinds, got {kinds!r}")


def _check_roof_like(variant: Dict[str, Any], where: str, errors: List[str]) -> None:
    """Check the look of a variant of its own: one glyph, one 7-bit character, a colour, a label and a rank."""
    if not (isinstance(variant["glyph"], str) and len(variant["glyph"]) == 1):
        errors.append(f"{where}.glyph: expected one character, got {variant['glyph']!r}")
    if not (isinstance(variant["ascii"], str) and len(variant["ascii"]) == 1 and variant["ascii"].isascii()):
        errors.append(f"{where}.ascii: expected one 7-bit character, got {variant['ascii']!r}")
    if not isinstance(variant["label"], str):
        errors.append(f"{where}.label: expected text, got {variant['label']!r}")
    rank = variant["rank"]
    if not (isinstance(rank, int) and not isinstance(rank, bool) and rank >= 0):
        errors.append(f"{where}.rank: expected an int >= 0, got {rank!r}")
    try:
        variant["color"] = list(_coerce_color(variant["color"]))
    except (TypeError, ValueError) as exc:
        errors.append(f"{where}.color: {exc}")


def _check_variants(row: Dict[str, Any], key: str, where: str, errors: List[str]) -> None:
    """Check a dressing's ``variants``: each valid, and each condition has a variant with a weight above 0."""
    variants = row[key]
    if not (isinstance(variants, dict) and variants):
        errors.append(f"{where}.{key}: expected a non-empty table of variants, got {variants!r}")
        return
    for name in sorted(variants):
        _check_variant(variants[name], f"{where}.{key}.{name}", errors)
    for condition in DRESS_CONDITIONS:
        weights = [v.get(condition) for v in variants.values() if isinstance(v, dict)]
        if not any(_is_number(w) and w > 0.0 for w in weights):
            errors.append(f"{where}.{key}: needs a variant with a {condition} weight above 0")


def _check_wear(row: Dict[str, Any], key: str, where: str, errors: List[str]) -> None:
    """Check a dressing's ``wear``: shares of ``void``, ``rubble`` and ``overgrown`` in [0, 1], at most 1 together."""
    wear = row[key]
    shares = wear if isinstance(wear, dict) else {}
    ok = (
        isinstance(wear, dict)
        and set(wear) <= set(DRESS_WEAR)
        and all(_is_number(v) and 0.0 <= v <= 1.0 for v in shares.values())
        and sum(shares.values()) <= 1.0
    )
    if not ok:
        errors.append(
            f"{where}.{key}: expected shares of {', '.join(DRESS_WEAR)} in [0, 1] summing to at most 1, got {wear!r}"
        )


def _check_roof(row: Dict[str, Any], key: str, where: str, errors: List[str]) -> None:
    """Check a building's ``roof`` look: a ``glyph`` (one character), an ``ascii`` (one 7-bit) and a ``color``."""
    look = row[key]
    if not isinstance(look, dict) or set(look) != {"glyph", "ascii", "color"}:
        errors.append(f"{where}.{key}: expected a table of glyph, ascii and color, got {look!r}")
        return
    if not (isinstance(look["glyph"], str) and len(look["glyph"]) == 1):
        errors.append(f"{where}.{key}.glyph: expected one character, got {look['glyph']!r}")
    if not (isinstance(look["ascii"], str) and len(look["ascii"]) == 1 and look["ascii"].isascii()):
        errors.append(f"{where}.{key}.ascii: expected one 7-bit character, got {look['ascii']!r}")
    try:
        look["color"] = list(_coerce_color(look["color"]))
    except (TypeError, ValueError) as exc:
        errors.append(f"{where}.{key}.color: {exc}")


def _check_value(row: Dict[str, Any], key: str, kind: str, where: str, errors: List[str]) -> None:
    """Check (and for colours, coerce) ``row[key]`` against ``kind``; record a problem if it fails."""
    value = row[key]
    if kind == "color":
        try:
            row[key] = list(_coerce_color(value))
        except (TypeError, ValueError) as exc:
            errors.append(f"{where}.{key}: {exc}")
        return
    if kind in ("dress_variants", "dress_wear"):
        (_check_variants if kind == "dress_variants" else _check_wear)(row, key, where, errors)
        return
    if kind == "roof":
        _check_roof(row, key, where, errors)
        return
    checks = {
        "function": lambda v: v in BUILDING_FUNCTIONS,
        "siting": lambda v: v in BUILDING_SITINGS,
        "site_tag": lambda v: v in SITE_TAGS,
        "shapes": lambda v: (
            isinstance(v, list) and len(v) > 0 and all(s in BUILDING_SHAPES for s in v) and len(set(v)) == len(v)
        ),
        "suits": lambda v: (
            isinstance(v, dict)
            and len(v) > 0
            and all(k in SUIT_TERMS and _is_number(w) and w >= 0.0 for k, w in v.items())
            and any(w > 0.0 for w in v.values())
        ),
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
        "secession_tag": lambda v: v in SECESSION_TAGS,
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
        "unit_pair": lambda v: (
            isinstance(v, list) and len(v) == 2 and all(_is_number(n) and 0.0 <= n <= 1.0 for n in v)
        ),
        "traits": _is_traits,
        "weights": lambda v: (
            isinstance(v, dict)
            and len(v) > 0
            and all(isinstance(k, str) and _is_number(w) and w >= 0.0 for k, w in v.items())
            and any(w > 0.0 for w in v.values())
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
    if isinstance(colors, dict) and set(colors) != {"major", "vassal", "city_state", "tribal", "fallen"}:
        errors.append("tables.realm_colors must have the rows major, vassal, city_state, tribal and fallen")
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


def _listed(row: Dict[str, Any], key: str) -> List[Any]:
    """The list under ``key`` of a row, or an empty list when it is absent or not a list."""
    value = row.get(key)
    return value if isinstance(value, list) else []


def _validate_poi_history(kind: str, row: Dict[str, Any], styles: Dict[str, Any], errors: List[str]) -> None:
    """Check one POI row's history keys: known event kinds, known styles in ``to:`` / ``from:`` tags, events present."""
    from ..world.entities import EVENT_KINDS  # local import: avoids import-order coupling

    where = f"tables.pois.{kind}"
    for event in _listed(row, "events"):
        if event not in EVENT_KINDS:
            errors.append(f"{where}.events: unknown event kind {event!r} (valid: {', '.join(EVENT_KINDS)})")
    for tag in _listed(row, "tags"):
        side, _, style = str(tag).partition(":")
        if side in ("to", "from") and style not in styles:
            errors.append(f"{where}.tags: {tag!r} names no ruling style")
    if row.get("source") == "history" and not row.get("events"):
        errors.append(f"{where}: a history kind needs events")


def _validate_poi_text(kind: str, row: Dict[str, Any], errors: List[str]) -> None:
    """Check one POI row's name patterns and hook texts: only their tokens, and the token each variant exists for."""
    where = f"tables.pois.{kind}"
    if row.get("source") in ("location", "both") and not row.get("hooks"):
        errors.append(f"{where}: a kind placed by location needs hooks")
    for key, allowed, needs in (
        ("names", _NAME_TOKENS, None),
        ("names_fallen", _NAME_TOKENS | {"fallen"}, "fallen"),
        ("hooks", _HOOK_TOKENS, None),
        ("hooks_near", _HOOK_TOKENS | {"near"}, "near"),
    ):
        for text in _listed(row, key):
            _check_tokens(text, allowed, f"{where}.{key}", errors)
            if needs and isinstance(text, str) and needs not in (_tokens(text) or set()):
                errors.append(f"{where}.{key}: {text!r} must use {{{needs}}}")


def _validate_poi_sites(sites: Any, pois: Dict[str, Any], errors: List[str]) -> None:
    """Check the ``poi_sites`` rows: a known kind, a band that runs outward, and every kind covering both tempers."""
    if not isinstance(sites, dict):
        return
    tempers: Dict[str, set] = {}
    for name in sorted(sites):
        row = sites[name]
        if not isinstance(row, dict):
            continue
        if row.get("kind") not in pois:
            errors.append(f"tables.poi_sites.{name}.kind: no POI kind named {row.get('kind')!r}")
        near, far = row.get("min_km"), row.get("max_km")
        if isinstance(near, (int, float)) and isinstance(far, (int, float)) and near >= far:
            errors.append(f"tables.poi_sites.{name}: min_km must be below max_km")
        tempers.setdefault(str(row.get("kind")), set()).add(row.get("temper"))
    for kind in sorted(tempers):
        if tempers[kind] != set(TEMPERS):
            errors.append(f"tables.poi_sites: kind {kind!r} needs a site for each temper ({', '.join(TEMPERS)})")


_RUIN_SITE_KEYS = ("ruin_standing", "ruin_wall_fall", "ruin_extent_share")


def _validate_ruin_origins(
    row: Dict[str, Any], tiers: Dict[str, Any], sites: Dict[str, Any], errors: List[str]
) -> None:
    """Check the ruin row's origins: every key present, every named origin a settlement tier, and each tier's site
    row carrying the numbers that draw it as a ruin."""
    where = "tables.pois.ruin"
    for key in ("origins", "fall_origin", "holding_origins"):
        if key not in row:
            errors.append(f"{where}: needs {key}")
    named = [row["fall_origin"]] if isinstance(row.get("fall_origin"), str) else []
    for key in ("origins", "holding_origins"):
        if isinstance(row.get(key), dict):
            named += sorted(row[key])
    for name in named:
        if name not in tiers:
            errors.append(f"{where}: origin {name!r} is no settlement tier")
        elif isinstance(sites.get(name), dict):
            for key in _RUIN_SITE_KEYS:
                if key not in sites[name]:
                    errors.append(f"tables.sites.{name}: needs {key} (it can be a ruin's origin)")


def _validate_tier_hooks(tiers: Dict[str, Any], errors: List[str]) -> None:
    """Check a free settlement's texts: ``hooks_free`` uses only {name}, ``hooks_remnant`` also needs {fallen}."""
    for tier in sorted(tiers):
        row = tiers[tier]
        if not isinstance(row, dict):
            continue
        for key, allowed, needs in (
            ("hooks_free", _HOOK_TOKENS, None),
            ("hooks_remnant", _HOOK_TOKENS | {"fallen"}, "fallen"),
        ):
            for text in _listed(row, key):
                _check_tokens(text, allowed, f"tables.tiers.{tier}.{key}", errors)
                if needs and isinstance(text, str) and needs not in (_tokens(text) or set()):
                    errors.append(f"tables.tiers.{tier}.{key}: {text!r} must use {{{needs}}}")


#: Style score terms that name a falloff scale in km: the weight key and the key that must then be present.
_STYLE_SCALES = (("near_settlement", "near_settlement_km"), ("near_road", "near_road_km"))
_STYLE_TEXTS: tuple[tuple[str, frozenset[str]], ...] = (
    ("hooks_homestead", frozenset()),
    ("hooks_hamlet", frozenset()),
    ("hooks_homestead_near", frozenset({"near"})),
    ("hooks_hamlet_near", frozenset({"near"})),
)


def _validate_poi_styles(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the ``poi_styles`` rows: what a style makes, what growth needs, the scale of each km term and its texts.

    Every style is a homestead style (it needs ``hooks_homestead``). A hamlet count needs ``grows_into`` (a settlement
    tier), because a hamlet is generated only for a style a homestead could grow by; a style that grows needs
    ``hooks_hamlet``. A generated style needs a count. A weighted ``near_settlement`` or ``near_road`` needs its scale.
    """
    styles = tables.get("poi_styles", {})
    tiers = tables.get("tiers", {})
    if not isinstance(styles, dict) or not isinstance(tiers, dict):
        return
    for name in sorted(styles):
        row = styles[name]
        where = f"tables.poi_styles.{name}"
        if not isinstance(row, dict):
            continue
        counts = [key for key in ("homestead_km2_per_poi", "hamlet_km2_per_poi") if key in row]
        if row.get("generated") is True and not counts:
            errors.append(f"{where}: a generated style needs homestead_km2_per_poi or hamlet_km2_per_poi")
        if "hamlet_km2_per_poi" in row and "grows_into" not in row:
            errors.append(f"{where}: a style that makes hamlets needs grows_into")
        if isinstance(row.get("grows_into"), str) and row["grows_into"] not in tiers:
            errors.append(f"{where}.grows_into: {row['grows_into']!r} is no settlement tier")
        if "hooks_homestead" not in row:
            errors.append(f"{where}: needs hooks_homestead")
        if "grows_into" in row and "hooks_hamlet" not in row:
            errors.append(f"{where}: a style that grows needs hooks_hamlet")
        for weight, scale in _STYLE_SCALES:
            if weight in row and scale not in row:
                errors.append(f"{where}: {weight} needs {scale}")
        for text in _listed(row, "names"):
            _check_tokens(text, _NAME_TOKENS, f"{where}.names", errors)
        for key, extra in _STYLE_TEXTS:
            for text in _listed(row, key):
                _check_tokens(text, _HOOK_TOKENS | extra, f"{where}.{key}", errors)
                if extra and isinstance(text, str) and "near" not in (_tokens(text) or set()):
                    errors.append(f"{where}.{key}: {text!r} must use {{near}}")


def _validate_building_keys(where: str, row: Dict[str, Any], errors: List[str]) -> None:
    """Check that a building row has exactly the keys of its function (production adds two optional ones)."""
    function = row.get("function")
    if function not in _BUILDING_KEYS:
        return
    for owner, keys in _BUILDING_KEYS.items():
        for key in sorted(keys):
            if owner == function and key not in row:
                errors.append(f"{where}: a {function} kind needs {key!r}")
            elif owner != function and key in row:
                errors.append(f"{where}.{key}: only a {owner} kind has this key")
    if function != "production":
        for key in sorted(_BUILDING_PRODUCTION_OPTIONAL & set(row)):
            errors.append(f"{where}.{key}: only a production kind has this key")


def _validate_building_names(tables: Dict[str, Any], kinds: Dict[str, str], errors: List[str]) -> None:
    """Check that a tier's ``centre`` and ``reserve`` name civic kinds and a style's ``building`` a production kind."""
    tiers, styles = tables.get("tiers", {}), tables.get("poi_styles", {})
    for tier in sorted(tiers) if isinstance(tiers, dict) else []:
        tier_row = tiers[tier]
        for key in ("centre", "reserve"):
            if isinstance(tier_row, dict) and key in tier_row and kinds.get(tier_row[key]) != "civic":
                errors.append(f"tables.tiers.{tier}.{key}: {tier_row[key]!r} is no civic building kind")
    for style in sorted(styles) if isinstance(styles, dict) else []:
        style_row = styles[style]
        if isinstance(style_row, dict) and "building" in style_row and kinds.get(style_row["building"]) != "production":
            errors.append(
                f"tables.poi_styles.{style}.building: {style_row['building']!r} is no production building kind"
            )


def _validate_buildings(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the building kinds' ranks, their function's keys, furniture families and the rows that name a kind.

    Ranks are unique and below ``KIND_ROOF_SLOTS`` (a rank is a roof cell id offset). A kind has exactly the keys of its
    function (a housing kind its population and storage, a production kind its suits, siting and counts, a civic kind
    its apron).
    """
    from ..world.tile import KIND_ROOF_SLOTS

    buildings = tables.get("buildings", {})
    if not isinstance(buildings, dict):
        return
    furniture = tables.get("furniture", {})
    kinds: Dict[str, str] = {}
    ranks: Dict[int, str] = {}
    for name in sorted(buildings):
        row = buildings[name]
        where = f"tables.buildings.{name}"
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("function"), str):
            kinds[name] = row["function"]
        rank = row.get("rank")
        if isinstance(rank, int) and not isinstance(rank, bool):
            if rank >= KIND_ROOF_SLOTS:
                errors.append(f"{where}.rank: {rank} does not fit the roof block of {KIND_ROOF_SLOTS} kinds")
            if rank in ranks:
                errors.append(f"{where}.rank: {rank} is also the rank of {ranks[rank]!r}")
            ranks[rank] = name
        _validate_building_keys(where, row, errors)
        if isinstance(furniture, dict) and row.get("furniture") not in furniture:
            errors.append(f"{where}.furniture: no furniture family named {row.get('furniture')!r}")
    _validate_building_names(tables, kinds, errors)


def _validate_dress(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the dress tables' cross references: unique ranks below ``DRESS_SLOTS``; variant kinds are POI kinds."""
    from ..world.tile import DRESS_SLOTS

    dress = tables.get("dress", {})
    if not isinstance(dress, dict):
        return
    known = set(tables.get("pois", {})) | set(tables.get("tiers", {}))
    ranks: Dict[int, str] = {}
    for name in sorted(dress):
        row = dress[name]
        if isinstance(row, dict) and not ({"variants", "wear"} & set(row)):
            errors.append(f"tables.dress.{name}: needs variants or wear")
        variants = row.get("variants") if isinstance(row, dict) else None
        if not isinstance(variants, dict):
            continue
        for variant_name in sorted(variants):
            variant, where = variants[variant_name], f"tables.dress.{name}.variants.{variant_name}"
            if not isinstance(variant, dict):
                continue
            rank = variant.get("rank")
            if isinstance(rank, int) and not isinstance(rank, bool):
                if rank >= DRESS_SLOTS:
                    errors.append(f"{where}.rank: {rank} does not fit the dress block of {DRESS_SLOTS} variants")
                if rank in ranks:
                    errors.append(f"{where}.rank: {rank} is also the rank of {ranks[rank]}")
                ranks[rank] = f"{name}.{variant_name}"
            for kind in variant.get("kinds", []) if isinstance(variant.get("kinds"), list) else []:
                if known and kind not in known:
                    errors.append(f"{where}.kinds: {kind!r} is no POI kind")


def _validate_pois(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the POI kinds' history keys, name patterns and hook texts, and the shrine-like sites."""
    pois, styles = tables.get("pois", {}), tables.get("ruling_styles", {})
    if not isinstance(pois, dict) or not isinstance(styles, dict):
        return
    for kind in sorted(pois):
        if isinstance(pois[kind], dict):
            _validate_poi_history(kind, pois[kind], styles, errors)
            _validate_poi_text(kind, pois[kind], errors)
    if isinstance(tables.get("tiers"), dict):
        _validate_tier_hooks(tables["tiers"], errors)
    if isinstance(pois.get("ruin"), dict) and isinstance(tables.get("tiers"), dict):
        _validate_ruin_origins(pois["ruin"], tables["tiers"], tables.get("sites", {}), errors)
    _validate_poi_sites(tables.get("poi_sites", {}), pois, errors)
    _validate_poi_styles(tables, errors)


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


def _validate_secession(tables: Dict[str, Any], errors: List[str]) -> None:
    """Check the secession tables: exactly the known terms, forms and relation kinds (and ``none``)."""
    from ..world.entities import RELATION_KINDS  # local import: avoids import-order coupling

    for name, expected in (
        ("secession_terms", SECESSION_TERMS),
        ("secession_forms", SECESSION_FORMS),
        ("secession_relations", (*RELATION_KINDS, "none")),
    ):
        rows = tables.get(name)
        if isinstance(rows, dict) and set(rows) != set(expected):
            errors.append(f"tables.{name} must have exactly the rows: {', '.join(expected)}")
    forms = tables.get("secession_forms")
    if isinstance(forms, dict) and forms and all(isinstance(r, dict) and r.get("weight") == 0 for r in forms.values()):
        errors.append("tables.secession_forms: needs at least one weight above 0")


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
    _validate_buildings(tables, errors)
    _validate_dress(tables, errors)
    _validate_secession(tables, errors)

    styles = tables.get("styles", {})
    style = cfg.get("terrain", {}).get("style")
    if isinstance(styles, dict) and style is not None and style != "seed" and style not in styles:
        errors.append(f"terrain.style must be 'seed' or a style name ({', '.join(sorted(styles))}), got {style!r}")
    if isinstance(styles, dict) and style == "seed":
        weights = [row.get("weight") for row in styles.values() if isinstance(row, dict)]
        if not any(isinstance(w, (int, float)) and w > 0 for w in weights):
            errors.append("tables.styles: terrain.style = 'seed' needs at least one style with weight > 0")
