"""Names for realms and the wording of diplomatic relations.

A realm is named from its kind's ``tables.realm_forms`` rows: the habitat of its land favours some forms, a seeded
weighted draw picks one, and the realm's base word and its ruler's personal name are made in the realm's culture. A
relation's reason is a raw template from ``tables.reasons`` (picked by the diplomacy stage); once places are named,
:func:`describe_relations` fills its tokens. Every draw is keyed on realm id or relation index, so a name never depends
on the order realms are processed in.
"""

from __future__ import annotations

import random
from typing import Optional

from ..config.model import Config
from ..util import rng
from ..world.entities import Realm, Relation
from ..world.tile import BIOME_NAME
from ..world.world import World
from . import forge

_THE = "The "


def habitats(realm: Realm, config: Config) -> set[str]:
    """Return the habitats of a realm's land: ``high`` when mostly relief, else the groups of its dominant biome."""
    if realm.highland:
        return {"high"}
    biome = BIOME_NAME[realm.dominant_biome]
    groups = config.get("politics.habitats")
    return {name for name in sorted(groups) if biome in groups[name]}


def _candidate_forms(realm: Realm, config: Config) -> list[tuple[str, dict]]:
    """The ``(name, row)`` forms open to ``realm``, sorted by name: its kind's ``any`` rows and its habitats' rows.

    When the realm's habitats favour no form of its kind, its ``any`` and ``open`` rows are used.
    """
    rows = config.get("tables.realm_forms")
    of_kind = [(name, rows[name]) for name in sorted(rows) if rows[name]["kind"] == realm.kind]
    wanted = {"any"} | habitats(realm, config)
    chosen = [(name, row) for name, row in of_kind if row["habitat"] in wanted]
    if not any(row["habitat"] != "any" for _, row in chosen):
        chosen = [(name, row) for name, row in of_kind if row["habitat"] in ("any", "open")]
    return chosen


def _weighted(stream: random.Random, options: list[tuple[str, dict]]) -> dict:
    """Pick a form row by its ``weight`` (options are in a fixed order)."""
    pick = stream.random() * sum(float(row["weight"]) for _, row in options)
    for _, row in options:
        pick -= float(row["weight"])
        if pick < 0:
            return row
    return options[-1][1]


def name_realm(seed: int, realm: Realm, seat_name: str, config: Config) -> None:
    """Fill the realm's ``name``, ``short`` and ``ruler`` from a form of its kind, in its culture."""
    generators, naming_cfg = config.get("naming.generators"), config.section("naming")
    base = forge.name_entity(seed, "realm", (realm.id,), realm.culture, generators, naming_cfg)
    person = forge.name_entity(seed, "ruler", (realm.id,), realm.culture, generators, naming_cfg)
    stream = rng.derive(seed, "naming", "realm_form", realm.id)
    row = _weighted(stream, _candidate_forms(realm, config))
    seat = seat_name or base
    realm.name = str(row["form"]).format(n=base, s=seat)
    realm.ruler = str(stream.choice(list(row["rulers"]))).format(p=person, n=base)
    realm.short = seat if realm.kind == "city_state" else base


def _goods(realm: Realm, config: Config) -> str:
    """The trade good of a realm's land (iron for highland, else its dominant biome's), or ``""`` for none."""
    if realm.highland:
        return str(config.get("tables.relief.mountain.goods"))
    return str(config.get(f"tables.biomes.{BIOME_NAME[realm.dominant_biome]}.goods"))


def _trade_goods(a: Realm, b: Realm, config: Config) -> tuple[str, str]:
    """Return the goods ``a`` sells ``b`` and ``b`` sells ``a``, using ``politics.fallback_goods`` for a missing one."""
    first, second, tie = (str(g) for g in config.get("politics.fallback_goods"))
    goods_a, goods_b = _goods(a, config) or first, _goods(b, config) or second
    if goods_a == goods_b:
        goods_b = second if goods_a != second else tie
    return goods_a, goods_b


def _largest(world: World, kind: str, config: Config, fallback: str) -> str:
    """Name of the biggest named feature of ``kind`` (longest river), without a leading "The ", else ``fallback``."""
    features = [f for f in world.features if f.kind == kind and f.name]
    if not features:
        return fallback
    best = max(features, key=lambda f: (f.length_km if kind == "river" else f.area_km2, -f.id))
    return best.name.removeprefix(_THE)


def _town(world: World, config: Config, relation: Relation, stream: random.Random, tops: dict[int, int]) -> str:
    """The claimed town of a war, else a random settlement of either power, else any, else the fallback words."""
    if relation.claim_poi >= 0:
        return world.pois[relation.claim_poi].name
    kinds = set(config.get("politics.reason_town_kinds"))
    towns = [p for p in world.pois if p.civilized and p.kind in kinds and p.name]
    ours = [p for p in towns if tops.get(p.realm_id) in (relation.a, relation.b)]
    pool = ours or towns
    return stream.choice(pool).name if pool else str(config.get("tables.reason_tokens.town.fallback"))


def describe_relations(world: World, config: Config, seed: int) -> None:
    """Replace each relation's raw reason template by its text, naming the town, river, range, sea and goods."""
    from ..pipeline.civilization.diplomacy import top_of  # local: naming sits above the stages that make realms

    realms = world.realms
    tops = {r.id: top_of(realms, r.id) for r in realms}
    places = {
        "river": _largest(world, "river", config, str(config.get("tables.reason_tokens.river.fallback"))),
        "range": _largest(world, "range", config, str(config.get("tables.reason_tokens.range.fallback"))),
        "sea": _largest(world, "sea", config, str(config.get("tables.reason_tokens.sea.fallback"))),
    }
    for index, relation in enumerate(world.relations):
        stream = rng.derive(seed, "naming", "reason", index)
        a, b = realms[relation.a], realms[relation.b]
        goods_a, goods_b = _trade_goods(a, b, config)
        tokens = {
            **places,
            "town": _town(world, config, relation, stream, tops),
            "goods_a": goods_a,
            "goods_b": goods_b,
            "short_a": a.short,
            "short_b": b.short,
        }
        relation.why = relation.why.format(**tokens)


def seat_name(world: World, realm: Realm) -> Optional[str]:
    """Name of the realm's seat settlement, or ``None`` for a tribe with none."""
    return world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else None
