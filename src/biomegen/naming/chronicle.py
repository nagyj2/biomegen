"""Names for fallen realms and the text of the chronicle's events.

A fallen realm takes the culture its ruins' biome favours and a name from the same forms as a living major realm. Each
event's raw template (picked by the history stage) then has its ``{tokens}`` filled from the now-named realms, places
and relations. Runs last in the naming stage, after realms, places and the wording of relations, so every token
resolves. Every draw is keyed on the entity, so a name never depends on processing order.
"""

from __future__ import annotations

from ..config.model import Config
from ..world.entities import ChronicleEvent, Realm, Relation
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


def _tokens(world: World, config: Config, event: ChronicleEvent, relations: dict[tuple[int, int], Relation]) -> dict:
    """Return every token an event's wording may use (a superset: a template uses only its row's)."""
    realms = [world.realms[i] for i in event.realm_ids]
    pair = relations.get((min(event.realm_ids), max(event.realm_ids))) if len(event.realm_ids) == 2 else None
    tokens: dict[str, object] = {
        "year": event.year,
        "near": world.pois[event.near_poi].name if event.near_poi >= 0 else "",
        "reason": pair.why if pair else "",
    }
    if event.kind in ("founding", "settling", "conquest") and realms:
        realm = realms[0]
        seat = world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else realm.short
        tokens.update(realm=realm.name, short=realm.short, ruler=realm.ruler, seat=seat)
        if event.kind == "settling":
            tokens["town"] = world.pois[event.poi_ids[0]].name
        if event.kind == "conquest":
            liege = realms[1]
            tokens.update(liege=liege.name, liege_short=liege.short, ruler=liege.ruler)
    elif len(realms) == 2:
        first, second = realms
        town = (
            world.pois[event.poi_ids[0]].name
            if event.poi_ids
            else str(config.get("tables.reason_tokens.town.fallback"))
        )
        tokens.update(
            attacker=first.name,
            attacker_short=first.short,
            defender=second.name,
            defender_short=second.short,
            winner=first.name,
            winner_short=first.short,
            loser=second.name,
            loser_short=second.short,
            a=first.name,
            a_short=first.short,
            b=second.name,
            b_short=second.short,
            town=town,
        )
    if event.kind == "fall":
        fallen = world.fallen_realms[event.fallen_ids[0]]
        tokens.update(fallen=fallen.name, founded=fallen.founded)
    return tokens


def describe_events(world: World, config: Config, seed: int) -> None:
    """Render ``text`` of every event from its raw template, first letter capitalised; fallen realms are named first."""
    name_fallen_realms(world, config, seed)
    relations = {(r.a, r.b): r for r in world.relations}
    for event in world.chronicle:
        text = event.template.format(**_tokens(world, config, event, relations))
        event.text = text[:1].upper() + text[1:]  # a ruler's title ("the Synod of ...") may open the sentence
