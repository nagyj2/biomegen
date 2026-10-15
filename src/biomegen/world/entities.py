"""Sparse world objects that do not belong in a per-tile array.

POIs, realms, rivers, lakes and geographic features are few in number but rich in attributes, so they
live in plain dataclasses held in lists on the :class:`~biomegen.world.world.World`. Tiles reference them by index
(e.g. ``world.poi_index[y, x]`` -> ``world.pois[i]``; ``world.realm_id[y, x]`` -> ``world.realms[i]``) and the
objects reference back via coordinates. Keeping the heavy attributes here keeps the per-tile arrays small and
cache-friendly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

REALM_KINDS: Tuple[str, ...] = ("major", "city_state", "tribal")
RELATION_KINDS: Tuple[str, ...] = ("war", "rivalry", "alliance", "trade")
EVENT_KINDS: Tuple[str, ...] = (
    "founding",
    "settling",
    "conquest",
    "succession",
    "war",
    "rivalry",
    "treaty",
    "battle",
    "peace",
    "fall",
)
NO_LOCATION: Tuple[int, int] = (-1, -1)  # a chronicle event not tied to a cell
REF_KINDS: Tuple[str, ...] = ("realm", "poi", "fallen", "ruler")  # what a name in an event's text can refer to
REF_REALM, REF_POI, REF_FALLEN, REF_RULER = REF_KINDS


@dataclass
class POI:
    """A point of interest (village, town, city, capital, tower, dungeon, ruin, camp, boat, ...).

    Placement fills the location, kind and floors, the realms stage the realm; the plan of each floor is generated
    lazily from ``interior_seed`` (see :mod:`biomegen.sites`) and never stored here.
    """

    kind: str  # "capital", "city", "town", "village", "tower", "dungeon", ...
    x: int  # anchor cell on the biome map
    y: int
    interior_seed: int  # per-POI seed minted at placement; deterministic lazy interiors
    name: str = ""
    civilized: bool = False  # towns/villages/cities are "civilized"; towers/dungeons/etc. are not
    realm_id: int = -1  # the realm holding the anchor cell (-1 = wild); set by the realms stage
    floor_count: int = 1  # >1 for towers (above ground) and dungeons (below ground)
    lowest_floor: int = 0  # 0 for ground-level; negative for dungeons going underground
    pop: int = 0  # population (settlements only)
    founded: int = 0  # chronicle year the settlement was founded (set by the history stage; 0 = not dated)
    fell: int | None = None  # year it fell or was dismantled (None while it stands); set by a later simulation
    event_ids: List[int] = field(
        default_factory=list
    )  # chronicle events that made or marked it (the link runs POI -> event)
    hook: str = ""  # its story text, rendered by the naming stage
    hook_refs: List[Tuple[int, int, str, int]] = field(
        default_factory=list
    )  # (start, end, REF_KINDS entry, id) per name in hook
    bandit_strength: int = 0  # bandits it holds (a wild tower, dungeon or ruin); data only until a simulation reads it
    purpose: str = ""  # a camp's purpose (founding, bandit, army); empty for every other kind
    tags: Tuple[str, ...] = ()  # site traits, e.g. "port", "river"
    extra: dict = field(default_factory=dict)  # kind-specific data (e.g. boat cargo type)


@dataclass
class Realm:
    """A political power: a major realm, a city-state or a tribal land.

    ``seat_poi`` indexes ``World.pois`` (-1 for a tribe with no settlement). ``liege`` is the realm id of the
    overlord (-1 when independent); ``vassals`` lists the realms that swore fealty to this one. Names, ruler and
    culture are filled by the naming stage; ``color`` by the diplomacy stage.
    """

    id: int  # index into World.realms
    kind: str  # "major" | "city_state" | "tribal"
    seat_poi: int = -1
    name: str = ""
    short: str = ""
    ruler: str = ""
    culture: str = ""
    area_km2: float = 0.0
    pop: int = 0
    dominant_biome: int = 0  # the Biome (int) covering most of the realm's cells
    highland: bool = False  # more than half of the realm's cells have relief (hills or higher)
    liege: int = -1
    vassals: List[int] = field(default_factory=list)
    color: Tuple[int, int, int] = (0, 0, 0)
    founded: int = 0  # chronicle year the realm was founded (set by the history stage)
    ruling_style: str = ""  # the ruler's style now, a tables.ruling_styles row (set by the history stage)


@dataclass
class Relation:
    """A diplomatic tie between two independent powers (realm ids ``a`` < ``b``).

    ``why`` is the reason text. Only a war has an ``attacker`` (a or b) and a ``claim_poi`` (index into
    ``World.pois``, -1 if none); ``border_km`` is the length of the shared border (0 across the sea).
    """

    a: int
    b: int
    kind: str  # "war" | "rivalry" | "alliance" | "trade"
    border_km: float = 0.0
    why: str = ""
    attacker: int = -1
    claim_poi: int = -1


@dataclass
class River:
    """A traced freshwater channel from a highland source toward the sea."""

    id: int
    path: List[Tuple[int, int]] = field(default_factory=list)  # ordered upstream→downstream cells
    name: str = ""
    length: int = 0  # number of channel cells in ``path``
    mouth: Optional[Tuple[int, int]] = None  # where it meets ocean/lake (None if it dries out inland)
    source: Tuple[int, int] = (0, 0)  # first (most upstream) cell of ``path``
    length_km: float = 0.0  # length along ``path`` in km (aspect-aware step lengths)


@dataclass
class Lake:
    """A standing water body. ``salt`` is True only if connected to the open sea."""

    id: int
    tiles: List[Tuple[int, int]] = field(default_factory=list)
    name: str = ""
    area: int = 0  # number of cells
    salt: bool = False
    area_km2: float = 0.0
    surface_m: float = 0.0  # height of the flat water surface (the depression's spill level)


@dataclass
class GeoFeature:
    """A named physical feature: a landmass, mountain range, sea, lake, river or peak.

    ``ref`` points into the matching per-kind data: the ``landmass_id`` value for a landmass, the index
    into ``World.lakes`` / ``World.rivers`` for a lake or river, and -1 otherwise. ``anchor`` is the
    cell a label or gazetteer entry refers to (a summit, a sea's centre, a river's mouth).
    """

    id: int  # index into World.features
    kind: str  # "landmass" | "range" | "sea" | "lake" | "river" | "peak"
    anchor: Tuple[int, int]
    ref: int = -1
    name: str = ""
    cells: List[Tuple[int, int]] = field(default_factory=list)  # area features only (landmass, range, lake)
    area_km2: float = 0.0
    length_km: float = 0.0  # rivers
    elevation_m: float = 0.0  # summit height (peak, range, landmass) or greatest depth below sea (sea, < 0)
    summit: int = -1  # feature id of the highest peak (landmass, range)
    into: int = -1  # rivers: feature id of the lake or sea at the mouth (-1 if none)


@dataclass
class FallenRealm:
    """A realm that vanished before the present, known only by its ruins on wild land.

    It is not in ``World.realms``, so the realm partition and vassal tree never see it. ``location`` is the cell of its
    ruins, ``founded`` and ``fell`` are chronicle years; the naming stage fills ``culture`` and ``name``.
    """

    id: int  # index into World.fallen_realms
    location: Tuple[int, int]
    founded: int
    fell: int
    culture: str = ""
    name: str = ""


@dataclass
class ChronicleEvent:
    """One entry of the derived history (``World.chronicle``), plain data a later simulation can also emit.

    ``realm_ids``, ``poi_ids`` and ``fallen_ids`` index ``World.realms``, ``World.pois`` and ``World.fallen_realms``.
    ``location`` is a cell (:data:`NO_LOCATION` when none). ``template`` is the raw wording with its ``{tokens}``; the
    naming stage renders it into ``text``. The list is sorted by ``(year, kind order, creation order)`` and ``id`` is
    the index into it.
    """

    id: int
    year: int
    kind: str  # one of EVENT_KINDS
    realm_ids: List[int] = field(default_factory=list)
    poi_ids: List[int] = field(default_factory=list)
    fallen_ids: List[int] = field(default_factory=list)
    location: Tuple[int, int] = NO_LOCATION
    template: str = ""
    text: str = ""
    tags: Tuple[str, ...] = ()
    near_poi: int = -1  # the settlement {near} names (same landmass, within history.near_km), -1 when none
    refs: List[Tuple[int, int, str, int]] = field(
        default_factory=list
    )  # (start, end, REF_KINDS entry, id) per name in text
