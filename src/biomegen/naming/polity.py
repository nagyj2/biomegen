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
from ..world.entities import REF_FEATURE, REF_POI, Realm, Relation, Ruler
from ..world.resources import goods_word
from ..world.tile import BIOME_NAME
from ..world.world import World
from . import forge
from .render import Where, render_template

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


def _form_row(seed: int, realm: Realm, config: Config) -> dict:
    """The ``tables.realm_forms`` row the realm is named and ruled by (the first draw of its form stream)."""
    return _weighted(rng.derive(seed, "naming", "realm_form", realm.id), _candidate_forms(realm, config))


def name_ruler(seed: int, ruler: Ruler, realm: Realm, config: Config) -> str:
    """Return the name of ``ruler`` of ``realm``: a title from the realm's form and a personal name in its culture.

    Pure: the draws are keyed on the realm and the reign, so the name never depends on the order rulers are named in,
    and a later simulation can name a ruler it adds. The realm needs its culture.
    """
    generators, naming_cfg = config.get("naming.generators"), config.section("naming")
    base = forge.name_entity(seed, "realm", (realm.id,), realm.culture, generators, naming_cfg)
    person = forge.name_entity(seed, "ruler", (realm.id, ruler.id), realm.culture, generators, naming_cfg)
    title = rng.derive(seed, "naming", "ruler_title", realm.id, ruler.id).choice(
        list(_form_row(seed, realm, config)["rulers"])
    )
    return str(title).format(p=person, n=base)


def name_rulers(world: World, config: Config, seed: int) -> None:
    """Name every ruler, then make each realm's ``ruler`` its present ruler's name."""
    for ruler in world.rulers:
        ruler.name = name_ruler(seed, ruler, world.realms[ruler.realm_id], config)
    for realm in world.realms:
        present = world.ruler_at(realm.id, world.year)
        if present is not None:
            realm.ruler = present.name


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


def good_name(world: World, config: Config, realm_id: int, resource: str) -> str:
    """Return the chronicle's word for ``resource`` as ``realm_id``'s land knows it (else the resource's label)."""
    return (
        goods_word(world, config, realm_id, resource) or str(config.get(f"tables.resources.{resource}.label")).lower()
    )


def _trade_goods(world: World, a: Realm, b: Realm, relation: Relation, config: Config) -> tuple[str, str]:
    """Return the goods ``a`` sells ``b`` and ``b`` sells ``a``.

    A swap the history stage struck names them from its resources; otherwise each realm's biome good is used, with
    ``politics.fallback_goods`` for a missing one.
    """
    if relation.kind == "trade" and len(relation.goods) == 2:
        return good_name(world, config, a.id, relation.goods[0]), good_name(world, config, b.id, relation.goods[1])
    first, second, tie = (str(g) for g in config.get("politics.fallback_goods"))
    goods_a, goods_b = _goods(a, config) or first, _goods(b, config) or second
    if goods_a == goods_b:
        goods_b = second if goods_a != second else tie
    return goods_a, goods_b


def _place(world: World, relation: Relation, token: str, config: Config) -> str:
    """The name of the feature the diplomacy stage chose for ``token`` (no leading "The "), else the fallback words."""
    feature = relation.places.get(token)
    if feature is not None and world.features[feature].name:
        return world.features[feature].name.removeprefix(_THE)
    return str(config.get(f"tables.reason_tokens.{token}.fallback"))


def _town(
    world: World, config: Config, relation: Relation, stream: random.Random, tops: dict[int, int]
) -> tuple[str, int]:
    """The claimed town of a war, else a random settlement of either power, else any, as ``(name, index)``.

    With no settlement at all it is the fallback words and index -1.
    """
    if relation.claim_poi >= 0:
        return world.pois[relation.claim_poi].name, relation.claim_poi
    kinds = set(config.get("politics.reason_town_kinds"))
    towns = [(i, p) for i, p in enumerate(world.pois) if p.civilized and p.kind in kinds and p.name]
    ours = [(i, p) for i, p in towns if tops.get(p.realm_id) in (relation.a, relation.b)]
    pool = ours or towns
    if not pool:
        return str(config.get("tables.reason_tokens.town.fallback")), -1
    index, poi = stream.choice(pool)
    return poi.name, index


def describe_relations(world: World, config: Config, seed: int) -> None:
    """Replace the raw reason template of each relation and each ended episode by its text, naming the town, river,
    range, sea and goods.

    A river, range or sea is the nearby feature diplomacy recorded in ``relation.places``.
    """
    realms = world.realms
    tops = {r.id: world.top_realm(r.id) for r in realms}
    labelled = [("relation", i, r) for i, r in enumerate(world.relations)] + [
        ("episode", i, r) for i, r in enumerate(world.episodes)
    ]
    for label, index, relation in labelled:
        stream = (
            rng.derive(seed, "naming", "reason", index)
            if label == "relation"
            else rng.derive(seed, "naming", "reason", label, index)
        )
        a, b = realms[relation.a], realms[relation.b]
        goods_a, goods_b = _trade_goods(world, a, b, relation, config)
        town, town_index = _town(world, config, relation, stream, tops)
        tokens = {
            **{token: _place(world, relation, token, config) for token in ("river", "range", "sea")},
            "town": town,
            "goods_a": goods_a,
            "goods_b": goods_b,
            "short_a": a.short,
            "short_b": b.short,
        }
        where: Where = {token: (REF_FEATURE, feature) for token, feature in relation.places.items()}
        if town_index >= 0:
            where["town"] = (REF_POI, town_index)
        relation.why, relation.why_refs = render_template(relation.why, tokens, where)


def seat_name(world: World, realm: Realm) -> Optional[str]:
    """Name of the realm's seat settlement, or ``None`` for a tribe with none."""
    return world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else None
