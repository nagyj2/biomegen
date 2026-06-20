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
    """The discrete land-cover / water class shown on the biome map.

    Values are stable (stored in ``uint8`` arrays and hashed by the golden-world test), so append new
    biomes at the end rather than renumbering. Water classes (OCEAN/LAKE/RIVER) describe appearance;
    the orthogonal :class:`WaterType` field carries the salt-vs-fresh *semantics* used by lore and
    rendering tints.
    """

    OCEAN = 0  # open saltwater sea (connected to the map edge)
    LAKE = 1  # standing freshwater body
    RIVER = 2  # flowing freshwater channel
    BEACH = 3  # sandy shore: low-elevation land adjacent to the ocean
    GRASSLAND = 4
    SHRUBLAND = 5
    SAVANNA = 6
    FOREST = 7  # temperate forest
    JUNGLE = 8  # tropical rainforest
    TAIGA = 9  # boreal / cold conifer forest
    DESERT = 10
    TUNDRA = 11
    SWAMP = 12  # wetland / marsh
    MOUNTAIN = 13  # bare high-elevation rock
    SNOW = 14  # permanent snow cap


class WaterType(IntEnum):
    """Salt-vs-fresh classification of a water tile (orthogonal to :class:`Biome`)."""

    NONE = 0  # dry land
    SALT = 1  # ocean-connected
    FRESH = 2  # inland lake / river


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
    RUBBLE = 16  # collapsed masonry (ruins)
    TENT = 17
    CAMPFIRE = 18
    WAGON = 19
    TREE = 20  # outdoor vegetation clutter
    ROCK = 21
    BUSH = 22
    CARGO = 23  # boat shipments (goods/fish/weapons distinguished in POI metadata)
    RESERVED = 24  # reserved marker slot for future use


# Convenient lookup tables for config parsing and HUD display. Names are lower-case so they read
# naturally both in TOML (e.g. ``biomes = ["grassland", "forest"]``) and in status text.
BIOME_BY_NAME: dict[str, Biome] = {b.name.lower(): b for b in Biome}
BIOME_NAME: dict[int, str] = {int(b): b.name.lower() for b in Biome}

# Biomes that are water surfaces (used by several stages to test "is this a water tile?").
WATER_BIOMES: frozenset[int] = frozenset({int(Biome.OCEAN), int(Biome.LAKE), int(Biome.RIVER)})


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
    elevation: float
    temperature: float
    moisture: float
    biome: Biome
    water_type: WaterType
    region_id: int
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
        return int(self.biome) in WATER_BIOMES
