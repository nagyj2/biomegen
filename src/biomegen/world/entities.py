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

import numpy as np

REALM_KINDS: Tuple[str, ...] = ("major", "city_state", "tribal")
RELATION_KINDS: Tuple[str, ...] = ("war", "rivalry", "alliance", "trade")
REALM_ORIGINS: Tuple[str, ...] = ("", "offshoot", "split")  # how a realm began: ex nihilo, or by a secession
EVENT_KINDS: Tuple[str, ...] = (
    "founding",
    "secession",
    "settling",
    "expansion",
    "creation",
    "abandon",
    "occupation",
    "road",
    "conquest",
    "succession",
    "war",
    "rivalry",
    "treaty",
    "battle",
    "peace",
    "fall",
)
SALIENCES: Tuple[str, ...] = ("major", "minor")  # how noteworthy a chronicle event is; minor is hidden by default
TRAITS: Tuple[str, ...] = ("aggression", "greed", "trust", "expansionism", "caution")  # a ruler's personality
NO_LOCATION: Tuple[int, int] = (-1, -1)  # a chronicle event not tied to a cell
REF_KINDS: Tuple[str, ...] = (
    "realm",
    "poi",
    "fallen",
    "ruler",
    "feature",
    "predecessor",
)  # what a name in a text can refer to
REF_REALM, REF_POI, REF_FALLEN, REF_RULER, REF_FEATURE, REF_PREDECESSOR = REF_KINDS


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
    pop: int = 0  # population (a settlement's, or a ruin's at its peak)
    ruin_of: str = ""  # a ruin's origin: the settlement tier it was (a tables.tiers row); empty for every other kind
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
    style: str = ""  # a homestead's or generated hamlet's style (a tables.poi_styles row); empty for every other kind
    potential: str = ""  # the largest settlement tier its site could grow into (sites.potential); empty: no plan
    connect: bool = True  # whether the roads stage may link it (from its kind's row; a shrine variant may differ)
    tags: Tuple[str, ...] = ()  # site traits, e.g. "port", "river"
    extra: dict = field(default_factory=dict)  # kind-specific data (e.g. boat cargo type)

    @property
    def free(self) -> bool:
        """Whether this is a settlement no realm holds; derived from ``realm_id``, so an owner change needs no flag."""
        return self.civilized and self.realm_id < 0


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
    origin: str = (
        ""  # how it began, one of REALM_ORIGINS: "" founded outright, "offshoot" or "split" from another realm
    )
    parent: int = -1  # an offshoot's parent realm id (the realm it left, which lives on); -1 otherwise
    predecessor: int = -1  # a split's index into World.predecessors (the realm that ended in the split); -1 otherwise


@dataclass
class Ruler:
    """One ruler of a realm: the founder, then one per succession (a succession that keeps the style included).

    ``from_year`` is the year the reign began and ``to_year`` the year the next began (None for the present ruler), so a
    realm's reigns tile its life. ``traits`` holds a value in [0, 1] for each of :data:`TRAITS`: the ruling style's base
    values plus seeded noise. History creates the records; the naming stage fills ``name`` (title and personal name).
    """

    id: int  # index into World.rulers
    realm_id: int  # index into World.realms
    from_year: int
    to_year: Optional[int]
    style: str  # a tables.ruling_styles row
    traits: dict = field(default_factory=dict)  # TRAITS entry -> value in [0, 1]
    name: str = ""


@dataclass
class Relation:
    """A diplomatic tie between two independent powers (realm ids ``a`` < ``b``).

    ``why`` is the reason text. Only a war has an ``attacker`` (a or b) and a ``claim_poi`` (index into
    ``World.pois``, -1 if none); ``border_km`` is the length of the shared border (0 across the sea). ``places`` holds,
    for each ``{river}``, ``{range}`` or ``{sea}`` token the reason template uses, the nearby feature it names.
    """

    a: int
    b: int
    kind: str  # "war" | "rivalry" | "alliance" | "trade"
    border_km: float = 0.0
    why: str = ""
    attacker: int = -1
    claim_poi: int = -1
    places: dict = field(default_factory=dict)  # reason token ({river}, {range}, {sea}) -> id in World.features
    why_refs: List[Tuple[int, int, str, int]] = field(default_factory=list)  # (start, end, REF_KINDS entry, id) in why


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
    color: Tuple[int, int, int] = (0, 0, 0)  # its colour in the chronicle, distinct from every realm's (set by history)


@dataclass
class Predecessor:
    """A realm that ended in a clean split into two new realms (``children``, realm ids), known only by its name.

    It is not in ``World.realms``, so the partition and the vassal tree never see it, and it is not a ``FallenRealm``:
    it left no ruins and fought no wars. ``founded`` and ``split_year`` are chronicle years (the children's founding
    year is the split year); the naming stage fills ``culture`` and ``name``, the history stage the colour.
    """

    id: int  # index into World.predecessors
    founded: int
    split_year: int
    children: List[int] = field(default_factory=list)
    culture: str = ""
    name: str = ""
    color: Tuple[int, int, int] = (0, 0, 0)  # its colour in the chronicle, distinct from every realm's


@dataclass
class ChronicleEvent:
    """One entry of the derived history (``World.chronicle``), plain data a later simulation can also emit.

    ``realm_ids``, ``poi_ids``, ``fallen_ids`` and ``predecessor_ids`` index ``World.realms``, ``World.pois``,
    ``World.fallen_realms`` and ``World.predecessors``.
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
    predecessor_ids: List[int] = field(
        default_factory=list
    )  # index into World.predecessors (a clean split's old realm)
    location: Tuple[int, int] = NO_LOCATION
    template: str = ""
    text: str = ""
    tags: Tuple[str, ...] = ()
    salience: str = "major"  # one of SALIENCES; the derived history emits only major events
    near_poi: int = -1  # the settlement {near} names (same landmass, within history.near_km), -1 when none
    refs: List[Tuple[int, int, str, int]] = field(
        default_factory=list
    )  # (start, end, REF_KINDS entry, id) per name in text
    month: int = 1  # 1 to history.months_per_year within ``year``; events of a year are in month order
    tick: int = 0  # the absolute month, ``month_tick(year, month, ...)``; a simulation's clock reads the same number
    derived: bool = False  # made by the generation from the present state (False: a simulation emitted it)


def month_tick(year: int, month: int, months_per_year: int) -> int:
    """Return the absolute month of ``month`` (1 upward) in ``year``: month 1 of year 0 is tick 0."""
    return year * months_per_year + month - 1


@dataclass
class RoadLink:
    """One road laid between two points of interest (or from one to the nearest road): what the history viewer draws
    once both ends exist and the road is built.

    Attributes:
        a: Index into ``World.pois`` of the first end.
        b: Index of the second end, or -1 for a spur that runs to the nearest road tile.
        tier: 1 for a trunk road, 2 for a spur (as ``World.road_tier``).
        cells: Sorted unique flat row-major indices (``y * width + x``) of the cells it covers, ``int32``.
        event_id: The ``road`` chronicle event that laid it (set by the annals), or -1.
        joins: For a spur, the index in ``World.road_links`` of the road it runs into (it cannot be laid before that
            one), else -1.
    """

    a: int
    b: int
    tier: int
    cells: np.ndarray
    event_id: int = -1
    joins: int = -1
