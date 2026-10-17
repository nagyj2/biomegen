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
            (any case); see :func:`event_names`. An expression: ``|`` is or, ``&`` is and (:func:`parse_expression`).
        text: Keep events whose year, kind or text contains this text (any case); also an expression.
        salience: ``"major"`` keeps major events only (the default); ``"all"`` also keeps minor ones.
    """

    kinds: tuple[str, ...] = ()
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    realm: str = ""
    text: str = ""
    salience: str = "major"

    @property
    def active(self) -> bool:
        """Whether any field is set."""
        return self != ChronicleFilter()


def parse_expression(text: str) -> list[list[str]]:
    """Split a filter into alternatives (``|``) of required terms (``&``), lowercased; ``&`` binds tighter than ``|``.

    Whitespace round a term is trimmed, so ``"HI |Lo"`` and ``"HI|Lo"`` are both ``"hi"`` or ``"lo"``; spaces inside
    a term stay. Empty terms are dropped, so an expression of only operators has no alternatives and keeps everything.
    """
    groups = [[term.strip().lower() for term in part.split("&") if term.strip()] for part in text.split("|")]
    return [[term.strip() for term in group] for group in groups if group]


def expression_terms(groups: list[list[str]]) -> list[str]:
    """Return each distinct term of ``groups``, in order of appearance."""
    return list(dict.fromkeys(term for group in groups for term in group))


def matches_expression(groups: list[list[str]], haystacks: Sequence[str]) -> bool:
    """Return whether some alternative of ``groups`` has every term inside at least one of the lowercase ``haystacks``.

    No alternatives at all matches everything.
    """
    return not groups or any(all(any(term in text for text in haystacks) for term in group) for group in groups)


def event_line_text(event: ChronicleEvent) -> str:
    """Return the event as one plain line without padding: ``year kind text`` (what a search matches)."""
    return f"{event.year} {event.kind} {event.text}"


#: What each kind of named entity is called in a listing.
ENTITY_LABELS = {
    REF_REALM: "realm",
    REF_FALLEN: "fallen realm",
    REF_PREDECESSOR: "old realm",
    REF_RULER: "ruler",
    REF_POI: "settlement",
}


def event_entities(world: World, event: ChronicleEvent) -> list[tuple[str, str]]:
    """Return ``(name, kind)`` for the realms, fallen and old realms, rulers and settlements an event involves.

    ``kind`` is a key of :data:`ENTITY_LABELS`. That is the entities its ids list and the ones its text names
    (``refs``), each once; a river, range or other named land is not included.
    """
    found = [(world.realms[i].name, REF_REALM) for i in event.realm_ids]
    found += [(world.fallen_realms[i].name, REF_FALLEN) for i in event.fallen_ids]
    found += [(world.predecessors[i].name, REF_PREDECESSOR) for i in event.predecessor_ids]
    found += [(world.place(i).name, REF_POI) for i in event.poi_ids]
    for _start, _end, kind, ref in event.refs:
        if kind == REF_REALM:
            found.append((world.realms[ref].name, kind))
        elif kind == REF_RULER:
            found.append((world.rulers[ref].name, kind))
        elif kind == REF_FALLEN:
            found.append((world.fallen_realms[ref].name, kind))
        elif kind == REF_PREDECESSOR:
            found.append((world.predecessors[ref].name, kind))
        elif kind == REF_POI:
            found.append((world.place(ref).name, kind))
    return list(dict.fromkeys(entry for entry in found if entry[0]))


def event_names(world: World, event: ChronicleEvent) -> list[str]:
    """Return the names of :func:`event_entities` (no repeats)."""
    return list(dict.fromkeys(name for name, _kind in event_entities(world, event)))


def chronicle_names(world: World) -> list[tuple[str, str]]:
    """Return every ``(name, kind)`` :func:`event_entities` finds in the chronicle, sorted by name (any case)."""
    found = {entry for event in world.chronicle for entry in event_entities(world, event)}
    return sorted(found, key=lambda entry: (entry[0].lower(), entry[0], entry[1]))


def filter_events(world: World, chronicle_filter: ChronicleFilter) -> list[ChronicleEvent]:
    """Return the chronicle's events that pass ``chronicle_filter``, in chronicle order."""
    kinds = set(chronicle_filter.kinds)
    realm = parse_expression(chronicle_filter.realm)
    text = parse_expression(chronicle_filter.text)
    show_minor = chronicle_filter.salience == "all"
    return [
        event
        for event in world.chronicle
        if (not kinds or event.kind in kinds)
        and (show_minor or event.salience == "major")
        and (chronicle_filter.year_from is None or event.year >= chronicle_filter.year_from)
        and (chronicle_filter.year_to is None or event.year <= chronicle_filter.year_to)
        and matches_expression(realm, [name.lower() for name in event_names(world, event)])
        and matches_expression(text, [event_line_text(event).lower()])
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
    if chronicle_filter.salience == "all":
        parts.append("major and minor")
    return "  ".join(parts)


def chronicle_title(world: World) -> str:
    """Return the title line of the text output."""
    return f"The Chronicle of {world.island_name or 'the island'} (seed {world.seed}, year {world.year})"


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
    named_places = {i for event in world.chronicle for i in event.poi_ids}  # a tower or dungeon an event is about
    return {
        "island": world.island_name,
        "seed": world.seed,
        "year": world.year,
        "events": [
            {
                "id": e.id,
                "year": e.year,
                "month": e.month,
                "tick": e.tick,
                "derived": e.derived,
                "kind": e.kind,
                "text": e.text,
                "tags": list(e.tags),
                "salience": e.salience,
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
        "settlements": [  # every settlement, and any other place an event names (its kind says which)
            {
                "id": i,
                "name": p.name,
                "kind": p.kind,
                "style": p.style,
                "realm_id": None if p.realm_id < 0 else p.realm_id,
                "founded": p.founded,
            }
            for i, p in enumerate((*world.pois, *world.vanished))
            if p.civilized or i in named_places
        ],
    }


def chronicle_json(world: World, events: Optional[Sequence[ChronicleEvent]] = None) -> str:
    """Return :func:`chronicle_data` as indented JSON (keys in a fixed order, non-ASCII names kept as they are)."""
    return json.dumps(chronicle_data(world, events), indent=2, ensure_ascii=False)
