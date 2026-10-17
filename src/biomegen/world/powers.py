"""What a power was like at a moment: its ruler, land, settlements, strength and ties, read from the history.

A *power* is a territory owner (``world.territory``): a realm, a fallen realm or the old realm of a split. Everything
here is derived from the finished world (the owner map at the moment, the chronicle, the rulers and the points of
interest that stood then); nothing is stored, so a later simulation's records can feed the same reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from ..config.model import Config
from .lifespans import poi_appears
from .territory import WILD, fallen_id_of, is_fallen_owner, is_predecessor_owner, predecessor_id_of
from .wars import wars_at
from .world import World

Stop = tuple[int, int]  # (year, month)
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class PowerProfile:
    """A power at a moment.

    Attributes:
        owner: Its territory owner value.
        name: Its name.
        color: Its colour on the map.
        kind: What it is: a realm kind's label, ``fallen realm`` or ``old realm``.
        founded: The year it began, when known.
        exists: Whether it stands at the moment (founded and not yet fallen, split or absent).
        ruler: Its ruler then and the year the reign began, with the ruling style's label ("" when it has none).
        capital: The name of its seat settlement, "" when none.
        cells: The land cells it holds then.
        area_km2: Their area.
        share: Their share of all the land held by anyone then.
        settlements: Settlements it holds then, by tier label, largest tier first.
        people: The people in those settlements.
        strength: Its size over the mean size of the powers holding land then, times its ruler's style multiplier.
        liege: The power it had bowed to by then, "" when independent.
        vassals: The powers that had bowed to it.
        ties: ``(kind, other, since year)`` for each war, rivalry, alliance and trade pact in force then.
    """

    owner: int
    name: str
    color: RGB
    kind: str
    founded: Optional[int]
    exists: bool
    ruler: str = ""
    ruler_since: Optional[int] = None
    style: str = ""
    capital: str = ""
    cells: int = 0
    area_km2: float = 0.0
    share: float = 0.0
    settlements: list[tuple[str, int]] = field(default_factory=list)
    people: int = 0
    strength: float = 0.0
    liege: str = ""
    vassals: list[str] = field(default_factory=list)
    ties: list[tuple[str, str, int]] = field(default_factory=list)


def owner_name(world: World, owner: int) -> tuple[str, RGB]:
    """Return the name and map colour of a territory owner."""
    if owner >= 0:
        realm = world.realms[owner]
        return realm.short or realm.name or f"realm {owner}", realm.color
    if is_fallen_owner(owner):
        fallen = world.fallen_realms[fallen_id_of(owner)]
        return fallen.name or f"fallen realm {fallen.id}", fallen.color
    if is_predecessor_owner(owner):
        predecessor = world.predecessors[predecessor_id_of(owner)]
        return predecessor.name or f"old realm {predecessor.id}", predecessor.color
    return "wild land", (128, 128, 128)


def _ties(world: World, owner: int, moment: Stop) -> list[tuple[str, str, int]]:
    """The wars, rivalries, alliances and trade pacts a realm was in at ``moment``, with the year each began."""
    ties: list[tuple[str, str, int]] = []
    for attacker, defender in wars_at(world, moment):
        if owner in (attacker, defender):
            other = defender if owner == attacker else attacker
            begun = next(
                e.year
                for e in world.chronicle
                if e.kind == "war" and e.realm_ids[:2] == [attacker, defender] and (e.year, e.month) <= moment
            )
            ties.append(("war", owner_name(world, other)[0], begun))
    for event in world.chronicle:
        if (event.year, event.month) > moment or event.fallen_ids or owner not in event.realm_ids:
            continue
        others = [r for r in event.realm_ids if r != owner]
        if event.kind == "rivalry" and others:
            ties.append(("rivalry", owner_name(world, others[0])[0], event.year))
        elif event.kind == "treaty" and others and event.tags:
            ties.append((event.tags[0], owner_name(world, others[0])[0], event.year))
    return ties


def power_profile(world: World, config: Config, owner: int, moment: Stop) -> PowerProfile:
    """Return what power ``owner`` was like at ``moment``."""
    name, color = owner_name(world, owner)
    extra: dict[str, Any]
    owners = world.owners_at(*moment)
    mine = owners == owner
    cells = int(mine.sum())
    held = owners != WILD
    land = int(held.sum())
    cell_km2 = world.scale.cell_area_km2
    holders = [int(o) for o in np.unique(owners[held])] if land else []
    mean = land / len(holders) if holders else 1.0
    if owner >= 0:
        realm = world.realms[owner]
        kind = str(config.get(f"tables.realm_kinds.{realm.kind}.label"))
        first = next((e for e in world.chronicle if e.kind in ("founding", "secession") and owner in e.realm_ids), None)
        founded = first.year if first is not None else realm.founded
        exists = (founded, 1) <= moment
        reign = world.ruler_at(owner, moment[0]) if exists else None
        style_row = f"tables.ruling_styles.{reign.style}" if reign is not None and reign.style else ""
        multiplier = float(config.get(f"{style_row}.strength_mul", 1.0)) if style_row else 1.0
        capital = world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else ""
        lord = world.top_realm_at(owner, *moment)
        vassals = [
            owner_name(world, r.id)[0]
            for r in world.realms
            if r.id != owner and r.id != lord and world.top_realm_at(r.id, *moment) == owner
        ]
        extra = {
            "ruler": reign.name if reign is not None else "",
            "ruler_since": reign.from_year if reign is not None else None,
            "style": str(config.get(f"{style_row}.label")) if style_row else "",
            "capital": capital,
            "liege": owner_name(world, lord)[0] if lord != owner else "",
            "vassals": vassals,
            "ties": _ties(world, owner, moment) if exists else [],
            "strength": (cells / mean) * multiplier if cells else 0.0,
        }
    elif is_fallen_owner(owner):
        fallen = world.fallen_realms[fallen_id_of(owner)]
        kind, founded, exists = "fallen realm", fallen.founded, fallen.founded <= moment[0] < fallen.fell
        extra = {"strength": cells / mean if cells else 0.0}
    else:
        predecessor = world.predecessors[predecessor_id_of(owner)]
        kind, founded = "old realm", predecessor.founded
        exists = predecessor.founded <= moment[0] < predecessor.split_year
        extra = {"strength": cells / mean if cells else 0.0}
    settlements: dict[str, int] = {}
    people = 0
    for index, poi in enumerate(world.pois):
        if not poi.civilized or not mine[poi.y, poi.x]:
            continue
        appears = poi_appears(world, config, index)
        if appears is not None and appears > moment:
            continue
        label = str(config.get(f"tables.tiers.{poi.kind}.label", poi.kind))
        settlements[label] = settlements.get(label, 0) + 1
        people += poi.pop
    rank = {str(row["label"]): int(row["rank"]) for row in config.get("tables.tiers").values()}
    ordered = sorted(settlements.items(), key=lambda item: (rank.get(item[0], 99), item[0]))
    return PowerProfile(
        owner=owner,
        name=name,
        color=color,
        kind=kind,
        founded=founded,
        exists=exists,
        cells=cells,
        area_km2=cells * cell_km2,
        share=cells / land if land else 0.0,
        settlements=ordered,
        people=people,
        **extra,
    )
