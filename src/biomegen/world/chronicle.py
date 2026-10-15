"""Plain-text and JSON output of a world's chronicle.

Both read only the finished :class:`~biomegen.world.world.World`, so any layer above may call them. The text is one line
per event, oldest first; the JSON holds every event plus the realms, rulers, fallen realms, predecessors and
settlements its ids refer to, so it can be read without the rest of the world.
"""

from __future__ import annotations

import json
from typing import Any

from .entities import EVENT_KINDS
from .world import World

#: Width of the event-type column of the text output.
KIND_WIDTH = max(len(kind) for kind in EVENT_KINDS)


def chronicle_title(world: World) -> str:
    """Return the title line of the text output."""
    return f"The Chronicle of {world.island_name or 'the island'} (year {world.year})"


def chronicle_text(world: World) -> str:
    """Return the chronicle as text in three columns, ``year  kind  text`` per event, oldest first, under a title."""
    lines = [chronicle_title(world), ""]
    lines += [f"{event.year:>5}  {event.kind:<{KIND_WIDTH}}  {event.text}" for event in world.chronicle]
    return "\n".join(lines)


def chronicle_data(world: World) -> dict[str, Any]:
    """Return the chronicle as plain data: the events and the entities their ids name."""
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
            for e in world.chronicle
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


def chronicle_json(world: World) -> str:
    """Return :func:`chronicle_data` as indented JSON (keys in a fixed order, non-ASCII names kept as they are)."""
    return json.dumps(chronicle_data(world), indent=2, ensure_ascii=False)
