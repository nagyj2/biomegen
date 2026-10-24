"""Names for fallen realms and the text of the chronicle's events.

A fallen realm takes the culture its ruins' biome favours and a name from the same forms as a living major realm. Each
event's raw template (picked by the history stage) then has its ``{tokens}`` filled from the now-named realms, places
and relations. Runs last in the naming stage, after realms, places and the wording of relations, so every token
resolves. Every draw is keyed on the entity, so a name never depends on processing order.
"""

from __future__ import annotations

from typing import Optional

from ..config.model import Config
from ..world.entities import (
    REF_FALLEN,
    REF_POI,
    REF_PREDECESSOR,
    REF_REALM,
    REF_RULER,
    ChronicleEvent,
    FallenRealm,
    Predecessor,
    Realm,
    Relation,
)
from ..world.tile import Relief
from ..world.world import World
from . import cultures, polity
from .render import Where, render_template


def name_fallen_realm(world: World, config: Config, seed: int, fallen: FallenRealm) -> None:
    """Fill ``fallen``'s ``culture`` (from its site's biome) and ``name`` (a major realm's form).

    The name is made by :func:`polity.name_realm` for a stand-in major realm of the site's biome whose id is negative
    (``-1 - fallen id``), so its streams never meet a living realm's. The draws are keyed on the fallen realm alone, so
    naming one never depends on naming another (a simulation can name a realm that falls).
    """
    x, y = fallen.location
    biome = int(world.biome[y, x])
    fallen.culture = cultures.culture_for_site(seed, biome, fallen.id)
    stand_in = Realm(
        id=-1 - fallen.id,
        kind="major",
        culture=fallen.culture,
        dominant_biome=biome,
        highland=int(world.relief[y, x]) != int(Relief.NONE),
    )
    polity.name_realm(seed, stand_in, "", config)
    fallen.name = stand_in.name


def name_fallen_realms(world: World, config: Config, seed: int) -> None:
    """Name every fallen realm (see :func:`name_fallen_realm`)."""
    for fallen in world.fallen_realms:
        name_fallen_realm(world, config, seed, fallen)


_PREDECESSOR_BASE = 1_000_000  # a predecessor's stand-in realm has id -(this + its id), clear of the fallen realms' ids


def name_predecessor(world: World, config: Config, seed: int, predecessor: Predecessor) -> None:
    """Fill ``predecessor``'s ``culture`` (its first child's) and ``name`` (a major realm's form).

    The name is made by :func:`polity.name_realm` for a stand-in major realm of the child's biome whose id is negative
    and far from the fallen realms' stand-ins, so its streams never meet another realm's. The draws are keyed on the
    predecessor alone, so a simulation can name one it adds.
    """
    child = world.realms[predecessor.children[0]] if predecessor.children else None
    stand_in = Realm(
        id=-_PREDECESSOR_BASE - predecessor.id,
        kind="major",
        culture=child.culture if child else "common",
        dominant_biome=child.dominant_biome if child else 0,
        highland=child.highland if child else False,
    )
    predecessor.culture = stand_in.culture
    polity.name_realm(seed, stand_in, "", config)
    predecessor.name = stand_in.name


def name_predecessors(world: World, config: Config, seed: int) -> None:
    """Name every predecessor (see :func:`name_predecessor`)."""
    for predecessor in world.predecessors:
        name_predecessor(world, config, seed, predecessor)


def _ruler(world: World, realm: Realm, year: int) -> tuple[str, tuple[str, int] | None]:
    """Return the name of ``realm``'s ruler in ``year`` and what it refers to (``None``: the realm has no ruler records,
    so its ``ruler`` string stands and names no one in particular)."""
    ruler = world.ruler_at(realm.id, year)
    if ruler is None:
        return realm.ruler, None
    return ruler.name, (REF_RULER, ruler.id)


def _offshoot_tokens(
    world: World, event: ChronicleEvent, child: Realm, parent: Realm, tokens: dict[str, object], where: Where
) -> None:
    """Fill the tokens of an offshoot's secession: the new realm, the realm it left, its founder and its capital."""
    seat = world.pois[child.seat_poi].name if child.seat_poi >= 0 else child.short
    tokens.update(realm=child.name, short=child.short, parent=parent.name, parent_short=parent.short, seat=seat)
    where.update(realm=(REF_REALM, child.id), short=(REF_REALM, child.id))
    where.update(parent=(REF_REALM, parent.id), parent_short=(REF_REALM, parent.id))
    where["seat"] = (REF_POI, child.seat_poi) if child.seat_poi >= 0 else (REF_REALM, child.id)
    tokens["ruler"], ref = _ruler(world, child, event.year)
    if ref:
        where["ruler"] = ref


def _predecessor_tokens(
    world: World, event: ChronicleEvent, realms: list[Realm], tokens: dict[str, object], where: Where
) -> None:
    """Fill the tokens of an event of a realm that ended in a clean split: its founding, or the split itself.

    The split also names the two new realms with their founders.
    """
    predecessor = world.predecessors[event.predecessor_ids[0]]
    tokens["predecessor"] = predecessor.name
    where["predecessor"] = (REF_PREDECESSOR, predecessor.id)
    for suffix, realm in zip(("a", "b"), realms, strict=False):
        tokens[f"realm_{suffix}"], tokens[f"short_{suffix}"] = realm.name, realm.short
        where[f"realm_{suffix}"] = where[f"short_{suffix}"] = (REF_REALM, realm.id)
        tokens[f"ruler_{suffix}"], ref = _ruler(world, realm, event.year)
        if ref:
            where[f"ruler_{suffix}"] = ref


def _defection_tokens(
    world: World, event: ChronicleEvent, holder: Realm, old: Realm, tokens: dict[str, object], where: Where
) -> None:
    """Fill the tokens of a defection: the settlement, the realm it joins and the realm it leaves."""
    town = event.poi_ids[0]
    tokens.update(town=world.pois[town].name, realm=holder.name, short=holder.short)
    tokens.update(parent=old.name, parent_short=old.short)
    where.update(town=(REF_POI, town), realm=(REF_REALM, holder.id), short=(REF_REALM, holder.id))
    where.update(parent=(REF_REALM, old.id), parent_short=(REF_REALM, old.id))


def _secession_tokens(
    world: World, event: ChronicleEvent, realms: list[Realm], tokens: dict[str, object], where: Where
) -> None:
    """Fill the tokens of a secession event: a split (or its old realm's founding), a defection or an offshoot."""
    if event.predecessor_ids:
        _predecessor_tokens(world, event, realms, tokens, where)
    elif "defection" in event.tags:
        _defection_tokens(world, event, realms[0], realms[1], tokens, where)
    else:
        _offshoot_tokens(world, event, realms[0], realms[1], tokens, where)


def _name_the_place(world: World, event: ChronicleEvent, tokens: dict[str, object], where: Where) -> bool:
    """Fill the tokens of an event that names one place and nothing else, and return whether it was one: a tower
    raised, delved, left or taken (``{place}``), a road laid (``{a}`` and ``{b}``) or a settlement no realm holds
    (``{town}``)."""
    if event.kind in ("creation", "abandon", "occupation"):
        tokens["place"] = world.place(event.poi_ids[0]).name
        where["place"] = (REF_POI, event.poi_ids[0])
        if event.realm_ids:  # a camp pitched on a realm's land: the realm made it
            realm = world.realms[event.realm_ids[0]]
            tokens.update(realm=realm.name, short=realm.short)
            where.update(realm=(REF_REALM, realm.id), short=(REF_REALM, realm.id))
    elif event.kind == "settling" and "free" in event.tags:
        tokens["town"] = world.pois[event.poi_ids[0]].name
        where["town"] = (REF_POI, event.poi_ids[0])
    elif event.kind == "road":  # a road between two places, or a spur from one
        for token, poi_id in zip(("a", "b"), event.poi_ids, strict=False):
            tokens[token] = world.pois[poi_id].name
            where[token] = (REF_POI, poi_id)
    else:
        return False
    return True


def _relation_of(world: World, event: ChronicleEvent, relations: dict[tuple[int, int], Relation]) -> Optional[Relation]:
    """The relation an event of two powers belongs to: its ended episode, else the pair's present relation."""
    if event.episode >= 0:
        return world.episodes[event.episode]
    return relations.get((min(event.realm_ids), max(event.realm_ids))) if len(event.realm_ids) == 2 else None


def _commerce_tokens(
    world: World,
    config: Config,
    event: ChronicleEvent,
    relation: Optional[Relation],
    tokens: dict[str, object],
    where: Where,
) -> None:
    """Fill the buyer, the seller and the good of a treaty that is a purchase (a trade struck for money).

    The good is worded as the seller's land knows it.
    """
    if event.kind != "treaty" or relation is None or not relation.goods or relation.buyer < 0:
        return
    seller = world.realms[relation.b if relation.buyer == relation.a else relation.a]
    buyer = world.realms[relation.buyer]
    for prefix, realm in (("buyer", buyer), ("seller", seller)):
        tokens[prefix], tokens[f"{prefix}_short"] = realm.name, realm.short
        where[prefix] = where[f"{prefix}_short"] = (REF_REALM, realm.id)
    tokens["goods"] = polity.good_name(world, config, seller.id, relation.goods[0])


def _tokens(
    world: World, config: Config, event: ChronicleEvent, relations: dict[tuple[int, int], Relation]
) -> tuple[dict[str, object], Where]:
    """Return every token an event's wording may use (a superset; a template uses its row's) and what each names."""
    realms = [world.realms[i] for i in event.realm_ids]
    fallen = world.fallen_realms[event.fallen_ids[0]] if event.fallen_ids else None
    pair = _relation_of(world, event, relations)
    tokens: dict[str, object] = {
        "year": event.year,
        "near": world.pois[event.near_poi].name if event.near_poi >= 0 else "",
        "reason": pair.why if pair else "",
    }
    where: Where = {"near": (REF_POI, event.near_poi)} if event.near_poi >= 0 else {}
    if fallen is not None:
        tokens.update(fallen=fallen.name, founded=fallen.founded)
        where["fallen"] = (REF_FALLEN, fallen.id)
    if _name_the_place(world, event, tokens, where):
        return tokens, where
    if event.predecessor_ids or (event.kind == "secession" and len(realms) == 2):
        _secession_tokens(world, event, realms, tokens, where)
    elif event.kind == "succession" and realms:
        realm = realms[0]
        styles = dict(tag.split(":") for tag in event.tags if tag.partition(":")[0] in ("from", "to"))
        label = {key: str(config.get(f"tables.ruling_styles.{name}.label")) for key, name in styles.items()}
        tokens.update(realm=realm.name, short=realm.short, style=label["to"], old_style=label["from"])
        where.update(realm=(REF_REALM, realm.id), short=(REF_REALM, realm.id))
        for token, year in (("ruler", event.year), ("old_ruler", event.year - 1)):  # the new reign and the one it ends
            tokens[token], ref = _ruler(world, realm, year)
            if ref:
                where[token] = ref
    elif event.kind in ("founding", "settling", "conquest", "expansion") and realms:
        realm = realms[0]
        seat = world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else realm.short
        tokens.update(realm=realm.name, short=realm.short, seat=seat)
        where.update(realm=(REF_REALM, realm.id), short=(REF_REALM, realm.id))
        tokens["ruler"], ref = _ruler(world, realm, event.year)  # a founding's ruler is the founder
        if ref:
            where["ruler"] = ref
        where["seat"] = (REF_POI, realm.seat_poi) if realm.seat_poi >= 0 else (REF_REALM, realm.id)
        if event.kind == "settling":
            tokens["town"] = world.pois[event.poi_ids[0]].name
            where["town"] = (REF_POI, event.poi_ids[0])
        if event.kind == "conquest":
            liege = realms[1]
            tokens.update(liege=liege.name, liege_short=liege.short)
            where.update(liege=(REF_REALM, liege.id), liege_short=(REF_REALM, liege.id))
            tokens["ruler"], ref = _ruler(
                world, liege, event.year
            )  # the overlord's ruler when the vassal bent the knee
            if ref:
                where["ruler"] = ref
            else:
                where.pop("ruler", None)
    elif fallen is not None and realms:
        realm = realms[0]
        tokens.update(victor=realm.name, victor_short=realm.short)
        where.update(victor=(REF_REALM, realm.id), victor_short=(REF_REALM, realm.id))
        sides = {
            "realm": (realm.name, realm.short, (REF_REALM, realm.id)),
            "fallen": (fallen.name, fallen.name, (REF_FALLEN, fallen.id)),
        }
        attacker, defender = ("fallen", "realm") if "attacker:fallen" in event.tags else ("realm", "fallen")
        winner, loser = ("fallen", "realm") if "won_by_fallen" in event.tags else ("realm", "fallen")
        for prefix, side in (("attacker", attacker), ("defender", defender), ("winner", winner), ("loser", loser)):
            name, short, ref = sides[side]
            tokens[prefix], tokens[f"{prefix}_short"] = name, short
            where[prefix] = where[f"{prefix}_short"] = ref
    elif len(realms) == 2:
        first, second = realms
        town = (
            world.pois[event.poi_ids[0]].name
            if event.poi_ids
            else str(config.get("tables.reason_tokens.town.fallback"))
        )
        if event.poi_ids:
            where["town"] = (REF_POI, event.poi_ids[0])
        for prefixes, realm in ((("attacker", "winner", "a"), first), (("defender", "loser", "b"), second)):
            for prefix in prefixes:
                tokens[prefix], tokens[f"{prefix}_short"] = realm.name, realm.short
                where[prefix] = where[f"{prefix}_short"] = (REF_REALM, realm.id)
        tokens["town"] = town
        _commerce_tokens(world, config, event, pair, tokens, where)
    return tokens, where


def describe_event(
    world: World,
    config: Config,
    event: ChronicleEvent,
    relations: Optional[dict[tuple[int, int], Relation]] = None,
) -> None:
    """Render ``text`` and ``refs`` of ``event`` from its raw template, as it is worded at generation.

    Pure apart from writing the event: it needs every realm, ruler, place and fallen or old realm the event names to be
    named already. The first letter of the text is capitalised (a ruler's title such as "the Synod of ..." may open it);
    no span moves. ``relations`` is ``{(a, b): Relation}`` for ``world.relations`` (built here when not given; a caller
    describing many events builds it once).
    """
    if relations is None:
        relations = {(r.a, r.b): r for r in world.relations}
    tokens, where = _tokens(world, config, event, relations)
    pair = _relation_of(world, event, relations)
    inner = {"reason": pair.why_refs} if pair else None
    text, event.refs = render_template(event.template, tokens, where, inner)
    event.text = text[:1].upper() + text[1:]


def describe_events(world: World, config: Config, seed: int) -> None:
    """Render ``text`` and ``refs`` of every event from its raw template; fallen realms are named first."""
    name_fallen_realms(world, config, seed)
    name_predecessors(world, config, seed)
    relations = {(r.a, r.b): r for r in world.relations}
    for event in world.chronicle:
        describe_event(world, config, event, relations)
