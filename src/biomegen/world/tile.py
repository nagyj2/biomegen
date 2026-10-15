"""Per-cell enumerations and a lightweight read accessor.

Tiles are deliberately **not** Python objects (a 192x44 world has thousands of them; per-object
overhead in pure Python would be wasteful). Instead each cell is described by small integers stored
in parallel numpy arrays on the :class:`~biomegen.world.world.World`. This module defines the meaning
of those integers - the :class:`Biome`, :class:`WaterType` and interior :class:`Cell` enums - and a
:class:`TileView` convenience that gathers every field for a single coordinate on demand (e.g. for
the cursor info panel).

All enums are :class:`enum.IntEnum` so their members compare/serialise as plain ``int`` and can be
written straight into ``uint8`` arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Biome(IntEnum):
    """The discrete land-cover / water class of a cell (the reference generator's biome set).

    Values are stored in ``uint8`` arrays; append new biomes at the end rather than renumbering. Every
    attribute (label, glyphs, colours, habitability, move cost, goods) lives in the ``biomes`` table of
    ``data/biomes.toml``, keyed by the lower-case member name. Rivers are not a biome: a river cell keeps
    its land biome and is marked fresh water in :class:`WaterType`. High ground is the orthogonal
    :class:`Relief`.
    """

    DEEP = 0  # deep ocean
    SHALLOW = 1  # sea within a short distance of land
    SEAICE = 2  # frozen sea or frozen lake
    LAKE = 3  # standing fresh water
    BEACH = 4  # low, warm shore next to the sea
    DESERT = 5
    SAVANNA = 6
    GRASS = 7  # grassland
    FOREST = 8  # temperate forest
    JUNGLE = 9  # tropical rainforest
    SWAMP = 10  # wetland on wet lowland
    TAIGA = 11  # boreal / cold conifer forest
    TUNDRA = 12
    SNOW = 13  # snow / glacier, and every high peak


class POIType(IntEnum):
    """Available points of interest."""

    CITY = 0
    TOWN = 1
    VILLAGE = 2
    TOWER = 3
    DUNGEON = 4
    RUIN = 5
    CAMP = 6


class WaterType(IntEnum):
    """Salt-vs-fresh classification of a water tile (orthogonal to :class:`Biome`)."""

    NONE = 0  # dry land
    SALT = 1  # ocean-connected
    FRESH = 2  # inland lake / river


class Relief(IntEnum):
    """Landform roughness of a tile, orthogonal to :class:`Biome` (a forest can be hilly).

    Stored as a ``uint8`` array. Attributes (name, glyphs, colour) live in the relief table of
    ``data/biomes.toml``, keyed by the lower-case member name.
    """

    NONE = 0  # flat or rolling land, and all water
    HILLS = 1
    MOUNTAIN = 2
    PEAK = 3  # the highest summits of a range
    VOLCANO = 4


class Cell(IntEnum):
    """Tiles used inside the zoomed-in detail grid (POI interiors and biome-floor clutter).

    Only relevant from Phase 5 onward, but defined here so the value space is fixed early. Glyphs and
    colours for these are data-driven in config (``render.interior_glyphs`` / palette), not hard-coded.
    """

    VOID = 0  # outside the structure / not yet generated
    FLOOR = 1
    WALL = 2
    DOOR = 3
    STAIRS_UP = 4
    STAIRS_DOWN = 5
    WATER = 6
    PATH = 7  # outdoor path / road segment within an interior
    # --- furniture & clutter (placed by the role-based furnishing pass) ---
    BED = 8
    TABLE = 9
    CHAIR = 10
    CHEST = 11
    HEARTH = 12  # fireplace / forge
    BARREL = 13
    CRATE = 14
    SHELF = 15
    RUBBLE = 16  # collapsed masonry (ruin)
    TENT = 17
    CAMPFIRE = 18
    WAGON = 19
    TREE = 20  # outdoor vegetation clutter
    ROCK = 21
    BUSH = 22
    CARGO = 23  # boat shipments (goods/fish/weapons distinguished in POI metadata)
    RESERVED = 24  # reserved marker slot for future use
    BRIDGE = 25  # interior bridge deck (settlement bridge over water)
    BRIDGE_WALL = 26  # interior bridge railing / wall
    SOLID = 27  # solid rock round the rooms of an underground floor
    ROOF = 28  # the top of a building seen from outside
    STONE = 29  # a wall seen from outside (a city wall, a ruin's stub), drawn solid
    HULL = 30  # a boat's planked side
    WHEEL = 31  # a mill's water wheel, standing in the river beside it


# Convenient lookup tables for config parsing and HUD display. Names are lower-case so they read
# naturally both in TOML (e.g. ``biomes = ["grass", "forest"]``) and in status text.
BIOME_BY_NAME: dict[str, Biome] = {b.name.lower(): b for b in Biome}
BIOME_NAME: dict[int, str] = {int(b): b.name.lower() for b in Biome}
RELIEF_BY_NAME: dict[str, Relief] = {r.name.lower(): r for r in Relief}
RELIEF_NAME: dict[int, str] = {int(r): r.name.lower() for r in Relief}

# Biomes that are water surfaces. A river cell is water too but keeps its land biome, so "is this cell
# water?" is ``water_type != WaterType.NONE``; this set answers "is the cover itself water?".
WATER_BIOMES: frozenset[int] = frozenset({int(Biome.DEEP), int(Biome.SHALLOW), int(Biome.SEAICE), int(Biome.LAKE)})


def biome_from_name(name: str) -> Biome:
    """Resolve a config/string biome name to its :class:`Biome`, with a clear error if unknown."""
    try:
        return BIOME_BY_NAME[name.lower()]
    except KeyError:
        valid = ", ".join(sorted(BIOME_BY_NAME))
        raise KeyError(f"unknown biome {name!r}; valid: {valid}") from None


@dataclass(frozen=True)
class TileView:
    """A snapshot of every field at one coordinate, gathered on demand for display.

    Created by :meth:`biomegen.world.world.World.view` (and overlaid with any runtime edits by the
    render layer). It is a plain value object - cheap to build for the single tile under the cursor,
    never materialised for the whole map.
    """

    x: int
    y: int
    elevation_m: float
    temperature_c: float
    rain_mm: float
    moisture: float
    biome: Biome
    relief: Relief
    landmass_id: int
    water_type: WaterType
    realm_id: int
    road: bool
    road_tier: int
    dist_to_ocean: float
    flow_accum: float
    poi_index: int

    @property
    def biome_name(self) -> str:
        return self.biome.name.lower()

    @property
    def is_water(self) -> bool:
        return self.water_type != WaterType.NONE
