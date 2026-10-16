"""Plain-text and JSON output of a world's chronicle.

Both read only the finished :class:`~biomegen.world.world.World`, so any layer above may call them. The text is one line
per event, oldest first; the JSON holds every event plus the realms, rulers, fallen realms, predecessors and
settlements its ids refer to, so it can be read without the rest of the world.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .entities import EVENT_KINDS, REF_FALLEN, REF_POI, REF_PREDECESSOR, REF_REALM, REF_RULER, ChronicleEvent
from .world import World

#: Width of the event-type column of the text output.
KIND_WIDTH = max(len(kind) for kind in EVENT_KINDS)


@dataclass(frozen=True)
class ChronicleFilter:
    """Which events of the chronicle to show; an unset field lets every event through.

    Attributes:
        kinds: Event kinds to keep (any of them); empty keeps every kind.
        year_from: Keep events in this year or later.
        year_to: Keep events in this year or earlier.
        realm: Keep events involving a realm, fallen or old realm, ruler or settlement whose name contains this text
            (any case); see :func:`event_names`.
        text: Keep events whose year, kind or text contains this text (any case).
    """

    kinds: tuple[str, ...] = ()
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    realm: str = ""
    text: str = ""

    @property
    def active(self) -> bool:
        """Whether any field is set."""
        return self != ChronicleFilter()


def event_line_text(event: ChronicleEvent) -> str:
    """Return the event as one plain line without padding: ``year kind text`` (what a search matches)."""
    return f"{event.year} {event.kind} {event.text}"


def event_names(world: World, event: ChronicleEvent) -> list[str]:
    """Return the names of the realms, fallen and old realms, rulers and settlements an event involves (no repeats).

    That is the entities its ids list and the ones its text names (``refs``); a river, range or other named land is not
    included.
    """
    names = [world.realms[i].name for i in event.realm_ids]
    names += [world.fallen_realms[i].name for i in event.fallen_ids]
    names += [world.predecessors[i].name for i in event.predecessor_ids]
    names += [world.pois[i].name for i in event.poi_ids]
    for _start, _end, kind, ref in event.refs:
        if kind == REF_REALM:
            names.append(world.realms[ref].name)
        elif kind == REF_RULER:
            names.append(world.rulers[ref].name)
        elif kind == REF_FALLEN:
            names.append(world.fallen_realms[ref].name)
        elif kind == REF_PREDECESSOR:
            names.append(world.predecessors[ref].name)
        elif kind == REF_POI:
            names.append(world.pois[ref].name)
    return list(dict.fromkeys(name for name in names if name))


def chronicle_names(world: World) -> list[str]:
    """Return every name :func:`event_names` finds in the chronicle, sorted by name without regard to case."""
    names = {name for event in world.chronicle for name in event_names(world, event)}
    return sorted(names, key=lambda name: (name.lower(), name))


def filter_events(world: World, chronicle_filter: ChronicleFilter) -> list[ChronicleEvent]:
    """Return the chronicle's events that pass ``chronicle_filter``, in chronicle order."""
    kinds = set(chronicle_filter.kinds)
    realm = chronicle_filter.realm.lower()
    text = chronicle_filter.text.lower()
    return [
        event
        for event in world.chronicle
        if (not kinds or event.kind in kinds)
        and (chronicle_filter.year_from is None or event.year >= chronicle_filter.year_from)
        and (chronicle_filter.year_to is None or event.year <= chronicle_filter.year_to)
        and (not realm or any(realm in name.lower() for name in event_names(world, event)))
        and (not text or text in event_line_text(event).lower())
    ]


def describe_filter(chronicle_filter: ChronicleFilter) -> str:
    """Return the filter as a short phrase for a status line (empty when nothing is filtered)."""
    parts = []
    if chronicle_filter.kinds:
        parts.append("kind " + ",".join(chronicle_filter.kinds))
    if chronicle_filter.year_from is not None or chronicle_filter.year_to is not None:
        low = "" if chronicle_filter.year_from is None else str(chronicle_filter.year_from)
        high = "" if chronicle_filter.year_to is None else str(chronicle_filter.year_to)
        parts.append(f"years {low}-{high}")
    if chronicle_filter.realm:
        parts.append(f"name {chronicle_filter.realm!r}")
    if chronicle_filter.text:
        parts.append(f"text {chronicle_filter.text!r}")
    return "  ".join(parts)


def chronicle_title(world: World) -> str:
    """Return the title line of the text output."""
    return f"The Chronicle of {world.island_name or 'the island'} (year {world.year})"


def chronicle_text(world: World, events: Optional[Sequence[ChronicleEvent]] = None) -> str:
    """Return the chronicle as text in three columns, ``year  kind  text`` per event, oldest first, under a title.

    ``events`` (default: every event) is the part of the chronicle to list, e.g. from :func:`filter_events`.
    """
    shown = world.chronicle if events is None else events
    lines = [chronicle_title(world), ""]
    lines += [f"{event.year:>5}  {event.kind:<{KIND_WIDTH}}  {event.text}" for event in shown]
    if events is not None and not shown:
        lines.append("(no matching events)")
    return "\n".join(lines)


def chronicle_data(world: World, events: Optional[Sequence[ChronicleEvent]] = None) -> dict[str, Any]:
    """Return the chronicle as plain data: the events and the entities their ids name.

    With ``events`` only those are listed; the entities stay whole so every id still resolves.
    """
    shown = world.chronicle if events is None else events
    return {
        "island": world.island_name,
        "seed": world.seed,
        "year": world.year,
        "events": [
            {
                "id": e.id,
                "year": e.year,
                "kind": e.kind,
                "text": e.text,
                "tags": list(e.tags),
                "location": None if e.location == (-1, -1) else list(e.location),
                "realm_ids": e.realm_ids,
                "poi_ids": e.poi_ids,
                "fallen_ids": e.fallen_ids,
                "predecessor_ids": e.predecessor_ids,
                "near_poi": None if e.near_poi < 0 else e.near_poi,
                "refs": [{"start": a, "end": b, "type": kind, "id": ref} for a, b, kind, ref in e.refs],
            }
            for e in shown
        ],
        "realms": [
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind,
                "founded": r.founded,
                "ruling_style": r.ruling_style,
                "liege": None if r.liege < 0 else r.liege,
                "seat_poi": None if r.seat_poi < 0 else r.seat_poi,
                "ruler": r.ruler,
                "origin": r.origin or None,
                "parent": None if r.parent < 0 else r.parent,
                "predecessor": None if r.predecessor < 0 else r.predecessor,
            }
            for r in world.realms
        ],
        "rulers": [
            {
                "id": ruler.id,
                "realm_id": ruler.realm_id,
                "name": ruler.name,
                "from_year": ruler.from_year,
                "to_year": ruler.to_year,
                "style": ruler.style,
                "traits": {name: round(value, 3) for name, value in ruler.traits.items()},
            }
            for ruler in world.rulers
        ],
        "fallen_realms": [
            {
                "id": f.id,
                "name": f.name,
                "culture": f.culture,
                "location": list(f.location),
                "founded": f.founded,
                "fell": f.fell,
            }
            for f in world.fallen_realms
        ],
        "predecessors": [
            {
                "id": p.id,
                "name": p.name,
                "culture": p.culture,
                "founded": p.founded,
                "split_year": p.split_year,
                "children": p.children,
            }
            for p in world.predecessors
        ],
        "settlements": [
            {
                "id": i,
                "name": p.name,
                "kind": p.kind,
                "realm_id": None if p.realm_id < 0 else p.realm_id,
                "founded": p.founded,
            }
            for i, p in enumerate(world.pois)
            if p.civilized
        ],
    }


def chronicle_json(world: World, events: Optional[Sequence[ChronicleEvent]] = None) -> str:
    """Return :func:`chronicle_data` as indented JSON (keys in a fixed order, non-ASCII names kept as they are)."""
    return json.dumps(chronicle_data(world, events), indent=2, ensure_ascii=False)
