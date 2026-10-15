"""Names for fallen realms and the text of the chronicle's events.

A fallen realm takes the culture its ruins' biome favours and a name from the same forms as a living major realm. Each
event's raw template (picked by the history stage) then has its ``{tokens}`` filled from the now-named realms, places
and relations. Runs last in the naming stage, after realms, places and the wording of relations, so every token
resolves. Every draw is keyed on the entity, so a name never depends on processing order.
"""

from __future__ import annotations

import string

from ..config.model import Config
from ..world.entities import REF_FALLEN, REF_POI, REF_REALM, REF_RULER, ChronicleEvent, Realm, Relation
from ..world.tile import Relief
from ..world.world import World
from . import cultures, polity


def name_fallen_realms(world: World, config: Config, seed: int) -> None:
    """Fill each fallen realm's ``culture`` (from its site's biome) and ``name`` (a major realm's form).

    The name is made by :func:`polity.name_realm` for a stand-in major realm of the site's biome whose id is negative
    (``-1 - fallen id``), so its streams never meet a living realm's.
    """
    for fallen in world.fallen_realms:
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


Where = dict[str, tuple[str, int]]  # token -> (what it names, its id); what is "realm", "poi", "fallen" or "ruler"


def _tokens(
    world: World, config: Config, event: ChronicleEvent, relations: dict[tuple[int, int], Relation]
) -> tuple[dict[str, object], Where]:
    """Return every token an event's wording may use (a superset; a template uses its row's) and what each names."""
    realms = [world.realms[i] for i in event.realm_ids]
    fallen = world.fallen_realms[event.fallen_ids[0]] if event.fallen_ids else None
    pair = relations.get((min(event.realm_ids), max(event.realm_ids))) if len(event.realm_ids) == 2 else None
    tokens: dict[str, object] = {
        "year": event.year,
        "near": world.pois[event.near_poi].name if event.near_poi >= 0 else "",
        "reason": pair.why if pair else "",
    }
    where: Where = {"near": (REF_POI, event.near_poi)} if event.near_poi >= 0 else {}
    if fallen is not None:
        tokens.update(fallen=fallen.name, founded=fallen.founded)
        where["fallen"] = (REF_FALLEN, fallen.id)
    if event.kind == "succession" and realms:
        realm = realms[0]
        styles = dict(tag.split(":") for tag in event.tags)
        label = {key: str(config.get(f"tables.ruling_styles.{name}.label")) for key, name in styles.items()}
        tokens.update(realm=realm.name, short=realm.short, style=label["to"], old_style=label["from"])
        where.update(realm=(REF_REALM, realm.id), short=(REF_REALM, realm.id))
    elif event.kind in ("founding", "settling", "conquest") and realms:
        realm = realms[0]
        seat = world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else realm.short
        tokens.update(realm=realm.name, short=realm.short, ruler=realm.ruler, seat=seat)
        where.update(realm=(REF_REALM, realm.id), short=(REF_REALM, realm.id), ruler=(REF_RULER, realm.id))
        where["seat"] = (REF_POI, realm.seat_poi) if realm.seat_poi >= 0 else (REF_REALM, realm.id)
        if event.kind == "settling":
            tokens["town"] = world.pois[event.poi_ids[0]].name
            where["town"] = (REF_POI, event.poi_ids[0])
        if event.kind == "conquest":
            liege = realms[1]
            tokens.update(liege=liege.name, liege_short=liege.short, ruler=liege.ruler)
            where.update(liege=(REF_REALM, liege.id), liege_short=(REF_REALM, liege.id), ruler=(REF_RULER, liege.id))
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
    return tokens, where


def _render(template: str, tokens: dict[str, object], where: Where) -> tuple[str, list[tuple[int, int, str, int]]]:
    """Fill ``template`` and return the text with the ``(start, end, what, id)`` span of every name in it."""
    out: list[str] = []
    refs: list[tuple[int, int, str, int]] = []
    length = 0
    for literal, field, _, _ in string.Formatter().parse(template):
        out.append(literal)
        length += len(literal)
        if field is None:
            continue
        value = str(tokens[field])
        if value and field in where:
            refs.append((length, length + len(value), *where[field]))
        out.append(value)
        length += len(value)
    return "".join(out), refs


def describe_events(world: World, config: Config, seed: int) -> None:
    """Render ``text`` and ``refs`` of every event from its raw template; fallen realms are named first.

    The first letter of the text is capitalised (a ruler's title such as "the Synod of ..." may open it); no span moves.
    """
    name_fallen_realms(world, config, seed)
    relations = {(r.a, r.b): r for r in world.relations}
    for event in world.chronicle:
        text, event.refs = _render(event.template, *_tokens(world, config, event, relations))
        event.text = text[:1].upper() + text[1:]
