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
from .entities import ChronicleEvent
from .lifespans import place_key
from .territory import WILD, at_end, fallen_id_of, is_fallen_owner, is_predecessor_owner, predecessor_id_of
from .wars import wars_at
from .world import World

Stop = tuple[int, ...]  # (year, month) or (year, month, chronicle event id)
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
        people: Their people and those living outside them (its settled people times the realm's own ratio).
        settled: The people in its settlements and homesteads alone.
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
    settled: int = 0
    strength: float = 0.0
    liege: str = ""
    liege_color: Optional[RGB] = None
    vassals: list[str] = field(default_factory=list)
    vassal_colors: list[RGB] = field(default_factory=list)
    ties: list[tuple[str, str, int]] = field(default_factory=list)
    tie_colors: list[RGB] = field(default_factory=list)


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


def _key(event: ChronicleEvent) -> tuple[int, int, int]:
    return event.year, event.month, event.id


def _ties_with_colors(world: World, owner: int, moment: Stop) -> list[tuple[str, str, int, RGB]]:
    """The wars, rivalries, alliances and trade pacts a realm was in at ``moment``: kind, the other power, the year each
    began and the other's colour."""
    now = at_end(moment)
    ties: list[tuple[str, str, int, RGB]] = []
    for attacker, defender in wars_at(world, moment):
        if owner in (attacker, defender):
            other = defender if owner == attacker else attacker
            begun = next(
                e.year
                for e in world.chronicle
                if e.kind == "war" and e.realm_ids[:2] == [attacker, defender] and _key(e) <= now
            )
            ties.append(("war", owner_name(world, other)[0], begun, owner_name(world, other)[1]))
    for event in world.chronicle:
        if _key(event) > now or event.fallen_ids or owner not in event.realm_ids:
            continue
        others = [r for r in event.realm_ids if r != owner]
        if event.kind == "rivalry" and others:
            ties.append(("rivalry", owner_name(world, others[0])[0], event.year, owner_name(world, others[0])[1]))
        elif event.kind == "treaty" and others and event.tags:
            ties.append((event.tags[0], owner_name(world, others[0])[0], event.year, owner_name(world, others[0])[1]))
    return ties


def _ties(world: World, owner: int, moment: Stop) -> list[tuple[str, str, int]]:
    """The ties of :func:`_ties_with_colors` without the colours."""
    return [(kind, name, year) for kind, name, year, _ in _ties_with_colors(world, owner, moment)]


def _life(
    world: World, opening: str, closing: str, **ids: int
) -> tuple[Optional[tuple[int, int, int]], Optional[tuple[int, int, int]]]:
    """Return the places in time of the ``opening`` and ``closing`` chronicle events naming a fallen realm or
    predecessor (``fallen_ids=`` or ``predecessor_ids=``), or ``None`` for one with no such event."""
    ((field_name, wanted),) = ids.items()

    def key(kind: str) -> Optional[tuple[int, int, int]]:
        event = next((e for e in world.chronicle if e.kind == kind and wanted in getattr(e, field_name)), None)
        return _key(event) if event is not None else None

    return key(opening), key(closing)


def _within(
    moment: Stop,
    began: Optional[tuple[int, int, int]],
    ended: Optional[tuple[int, int, int]],
    first_year: int,
    last_year: int,
) -> bool:
    """Whether ``moment`` is from the opening event up to (not including) the closing one; the years stand in for an
    event the chronicle does not hold (a kind switched off)."""
    start = began if began is not None else (first_year, 1, -1)
    end = ended if ended is not None else (last_year, 1, -1)
    return start <= at_end(moment) < end


def _outside_ratio(world: World, owner: int) -> float:
    """Return how many people a power has for each one in its settlements: its realm's stored population over the
    people in the places it holds today (so each realm keeps its own jitter), or the mean of the realms for a power
    that is not a realm today (a fallen or old realm)."""
    ratios = []
    for realm in world.realms:
        settled = sum(
            p.pop for p in world.pois if (p.civilized or p.kind == "homestead") and world.realm_id[p.y, p.x] == realm.id
        )
        if settled:
            ratios.append(realm.pop / settled)
            if realm.id == owner:
                return ratios[-1]
    return sum(ratios) / len(ratios) if ratios else 1.0


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
        exists = (_key(first) if first is not None else (founded, 1, -1)) <= at_end(moment)
        reign = world.ruler_at(owner, moment[0]) if exists else None
        style_row = f"tables.ruling_styles.{reign.style}" if reign is not None and reign.style else ""
        multiplier = float(config.get(f"{style_row}.strength_mul", 1.0)) if style_row else 1.0
        capital = world.pois[realm.seat_poi].name if realm.seat_poi >= 0 else ""
        lord = world.top_realm_at(owner, *moment)
        ties = _ties_with_colors(world, owner, moment) if exists else []
        vassals = [
            owner_name(world, r.id)
            for r in world.realms
            if r.id != owner and r.id != lord and world.top_realm_at(r.id, *moment) == owner
        ]
        extra = {
            "ruler": reign.name if reign is not None else "",
            "ruler_since": reign.from_year if reign is not None else None,
            "style": str(config.get(f"{style_row}.label")) if style_row else "",
            "capital": capital,
            "liege": owner_name(world, lord)[0] if lord != owner else "",
            "liege_color": owner_name(world, lord)[1] if lord != owner else None,
            "vassals": [name for name, _ in vassals],
            "vassal_colors": [color for _, color in vassals],
            "ties": [t[:3] for t in ties],
            "tie_colors": [t[3] for t in ties],
            "strength": (cells / mean) * multiplier if cells else 0.0,
        }
    elif is_fallen_owner(owner):
        fallen = world.fallen_realms[fallen_id_of(owner)]
        began, ended = _life(world, "founding", "fall", fallen_ids=fallen.id)
        kind, founded, exists = (
            "fallen realm",
            fallen.founded,
            _within(moment, began, ended, fallen.founded, fallen.fell),
        )
        extra = {"strength": cells / mean if cells else 0.0}
    else:
        predecessor = world.predecessors[predecessor_id_of(owner)]
        kind, founded = "old realm", predecessor.founded
        began, ended = _life(world, "founding", "secession", predecessor_ids=predecessor.id)
        exists = _within(moment, began, ended, predecessor.founded, predecessor.split_year)
        extra = {"strength": cells / mean if cells else 0.0}
    now = at_end(moment)
    settlements: dict[str, int] = {}
    settled = 0
    for poi in world.pois:
        if not (poi.civilized or poi.kind == "homestead") or not mine[poi.y, poi.x]:
            continue
        appears = place_key(world, config, poi)
        if appears is not None and appears > now:
            continue
        label = str(config.get(f"tables.tiers.{poi.kind}.label", "Homestead" if poi.kind == "homestead" else poi.kind))
        settlements[label] = settlements.get(label, 0) + 1
        settled += poi.pop
    rank = {str(row["label"]): int(row["rank"]) for row in config.get("tables.tiers").values()}
    ordered = sorted(settlements.items(), key=lambda item: (rank.get(item[0], 99), item[0]))
    outside = _outside_ratio(world, owner)
    people = int(settled * outside) if settled else 0
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
        settled=settled,
        **extra,
    )
