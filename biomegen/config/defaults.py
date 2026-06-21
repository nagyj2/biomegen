"""The authoritative in-code default configuration.

:data:`DEFAULTS` mirrors the structure of ``config.toml`` exactly. Every controllable value in the
program has an entry here, so the application runs correctly with zero config present and a user's
TOML only needs to specify the handful of keys they want to override. Keep this in sync with
``config.example.toml`` (the example is generated to match these values).

Conventions:
    * Scalar fields (elevation/temperature/moisture) are normalised to [0, 1].
    * Probabilities are in [0, 1]; clamped during validation.
    * Colours are ``[r, g, b]`` 0-255 triples (TOML may also give ``"#rrggbb"``; validation coerces).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

# NOTE: this dict is never mutated in place by the rest of the program - callers always work on a
# deep copy (see :func:`get_defaults`). The merge in the loader copies before merging.
DEFAULTS: Dict[str, Any] = {
    # -------------------------------------------------------------- general
    "general": {
        # Master seed. 0 / absent means "pick a random seed and echo it" so a random run is still
        # reproducible afterwards. May also be set on the CLI (which takes precedence).
        "seed": 0,
    },
    # -------------------------------------------------------------- world dimensions
    "world": {
        # Default sized so the whole map fits a typical terminal at 1:1 with room for the status
        # panel below it (the reference terminal is ~209x58; 44 + status_height(12) <= 58, 192 <= 209).
        "width": 192,
        "height": 75,
        # Sea level on the normalised [0, 1] elevation scale: tiles below this are ocean/water.
        "sea_level": 0.40,
        # "fixed" keeps the dimensions above (reproducible across terminals). "auto" fits the world to
        # the current terminal at launch (nicer fit, but the same seed yields different worlds on
        # differently sized terminals - documented trade-off).
        "size_mode": "fixed",
        # Global per-axis multipliers applied to noise sample coordinates: >1 stretches features along
        # that axis (zooms out), <1 compresses them. Distinct from per-feature ``terrain.scale``.
        "scale_x": 1.0,
        "scale_y": 1.0,
        # The island-mask sanity gate regenerates with a perturbed seed up to this many times if a
        # seed produces less than ``min_land_fraction`` land (prevents empty-world cascades).
        "regen_attempts": 8,
        "min_land_fraction": 0.12,
    },
    # -------------------------------------------------------------- compute backends
    "compute": {
        # Backend for connected-components / distance transforms / nearest-neighbour queries.
        #   "scipy" : ndimage.label + distance_transform_edt + cKDTree (default, fastest).
        #   "numpy" / "pure" : in-house implementations (no scipy needed).
        "backend": "scipy",
    },
    # -------------------------------------------------------------- terrain / heightmap
    "terrain": {
        # Noise backend selector (see biomegen.util.noise). "perlin" is our deterministic numpy
        # gradient noise and is the reproducibility-guaranteed default.
        "noise_backend": "perlin",
        "octaves": 7,  # number of fBm octaves summed (more = finer detail)
        "persistence": 0.54,  # amplitude falloff per octave (higher = rougher terrain)
        "lacunarity": 2.0,  # frequency growth per octave
        "scale": 58.0,  # base feature size in tiles (larger = broader landforms)
        "warp_strength": 0.55,  # domain-warp magnitude (higher = more meandering coasts/ridges)
        "warp_scale": 80.0,  # feature size of the warp field
        "warp_octaves": 3,
        "falloff_power": 2.2,  # radial island falloff steepness (lower = broader/larger main island)
        "falloff_strength": 1.0,  # how strongly the falloff pulls edges to ocean (0..1)
        "redistribution": 1.0,  # exponent applied after normalisation (>1 lowers mid heights)
        # Gentle interior lift: elevation = mask * (land_floor + (1-land_floor)*base). A small value
        # nudges the main island slightly larger/solider while keeping terrain variation (so the
        # interior still has hills, valleys and lakes). High values flatten and bloat - keep it low.
        "land_floor": 0.18,
        # --- coastline detail & archipelago shaping (see heightmap.py) ---
        # Coastline irregularity. Applied only NEAR the shore (interior stays solid), so it makes the
        # outline organic/non-round with peninsulas and bays WITHOUT fragmenting the island.
        "coast_detail": 0.42,
        "coast_scale": 20.0,  # feature size of the coastline-detail noise (smaller = finer wiggle)
        # Low-frequency, positive-only land lobes in the OUTER ring -> small satellite islands around
        # the main one (archipelago). 0 gives a single island.
        "archipelago": 0.42,
        "archipelago_scale": 68.0,
    },
    # -------------------------------------------------------------- climate
    "climate": {
        # "equator-center": warm band across the vertical middle, cooler toward top & bottom.
        # "north-pole-top": cold at the top, warm at the bottom.
        "orientation": "equator-center",
        "equator_temp": 1.0,  # normalised temperature at the warm latitude
        "pole_temp": 0.05,  # normalised temperature at the cold latitude
        "lapse_rate": 0.55,  # temperature drop with elevation (higher = colder mountains)
        "moisture_scale": 95.0,
        "moisture_octaves": 4,
        "moisture_persistence": 0.5,
        # Exponent applied to normalised moisture: >1 biases the map drier (more desert/savanna/
        # grassland and less forest/jungle), giving more biome variety. 1.0 = neutral.
        "moisture_redistribution": 1.5,
        "coastal_bias": 0.10,  # extra moisture near the coast (0 disables; lower => drier interiors)
        "coastal_range": 7.0,  # tiles over which the coastal moisture bonus decays
    },
    # -------------------------------------------------------------- hydrology
    "hydrology": {
        "flow_model": "d8",  # "d8" (default) or "dinf"
        "accumulation_threshold": 55,  # min drainage area for a tile to become a river channel
        "min_lake_size": 5,  # depression pools smaller than this are not treated as lakes
        "lake_min_depth": 0.0008,  # min (filled - elevation) for a cell to count as standing water
        "source_min_elevation": 0.55,  # rivers only start above this elevation
        "max_rivers": 24,  # cap on traced rivers (largest-accumulation sources first)
        "meander_strength": 0.0,  # extra lateral wobble added to river paths (0 = pure downhill)
        # River width grows with drainage area: a channel carrying ``ratio`` x the channelisation
        # threshold widens by ``(ratio-1) * river_width_scale`` tiles, capped at ``river_max_width``.
        # So small streams stay 1 tile; great rivers near the sea span several tiles.
        "river_width_scale": 0.5,
        "river_max_width": 5,
        "moisture_radius": 5,  # tiles within this of fresh water get a moisture boost
        "moisture_strength": 0.28,  # magnitude of the freshwater-proximity moisture boost
    },
    # -------------------------------------------------------------- biomes
    "biomes": {
        "classifier": "whittaker",
        # Elevation/water override thresholds (normalised elevation).
        "beach_max": 0.45,  # land at/below this AND next to ocean becomes beach
        "beach_dist": 2.0,  # max distance-to-ocean (tiles) for a tile to be eligible for beach
        "mountain_min": 0.76,  # bare rock above this
        "snow_min": 0.88,  # permanent snow above this
        "snow_temp": 0.18,  # ...or below this temperature at high-ish elevation
        "smooth_passes": 1,  # majority-vote de-speckle passes (0 disables)
        # Band edges that split the normalised temperature/moisture axes into rows/cols of the matrix.
        "temp_bands": [0.20, 0.40, 0.60, 0.80],  # -> 5 temperature bands (cold..hot)
        "moisture_bands": [0.22, 0.38, 0.52, 0.67, 0.83],  # -> 6 moisture bands (dry..wet)
        # Whittaker lookup: matrix[temp_band][moisture_band] -> biome name.
        # Rows are temperature cold->hot; columns are moisture dry->wet.
        "matrix": [
            ["tundra", "tundra", "taiga", "taiga", "taiga", "taiga"],  # coldest
            ["shrubland", "grassland", "taiga", "forest", "forest", "forest"],  # cool
            ["grassland", "grassland", "forest", "forest", "forest", "swamp"],  # temperate
            ["desert", "savanna", "grassland", "forest", "jungle", "jungle"],  # warm
            ["desert", "savanna", "savanna", "jungle", "jungle", "jungle"],  # hottest
        ],
    },
    # -------------------------------------------------------------- regions
    "regions": {
        # Tiles are grouped into a region with neighbours of a "similar" biome. Each entry lists the
        # biomes considered interchangeable for grouping (so e.g. forest+jungle+taiga form woodland
        # regions). Any biome not listed groups only with its own kind.
        "similarity_groups": [
            ["forest", "jungle", "taiga", "swamp"],
            ["grassland", "shrubland", "savanna"],
            ["desert"],
            ["tundra", "snow"],
            ["mountain"],
            ["beach"],
            ["lake", "river"],
        ],
        "min_region_size": 22,  # regions smaller than this are merged into their best neighbour
        "max_region_size": 100,  # regions larger than this are split into equal sub-regions
        # ocean tiles within this many steps of land get a region name; deeper tiles stay anonymous
        "coastal_ocean_depth": 3,
        "color_jitter": 28,  # +/- RGB jitter applied per region to its biome base colour
    },
    # -------------------------------------------------------------- POIs (placement + per-type rules)
    "poi": {
        "sampler": "bluenoise",  # "bluenoise" (default), "random", or "grid"
        # Falloff scales (tiles) mapping distance fields to [0,1] suitability weights, and the random
        # tie-break jitter strength. Smaller scale => the bonus decays faster with distance.
        "freshwater_scale": 6.0,
        "coastal_scale": 9.0,
        "remoteness_scale": 22.0,
        "jitter": 0.15,
        # Minimum fraction of a land structure's (max) footprint that must be dry land for an anchor to
        # be eligible. Keeps a coastal structure substantial (most of it on land) while still allowing
        # shoreline sites - the terrain-aware interior builder forms the structure around whatever water
        # the footprint clips. 1.0 forbids any footprint water (the old behaviour); 0 disables the check.
        "min_footprint_land": 0.5,
        # Per-kind rules. ``count`` is a target; ``min_spacing`` enforces blue-noise separation;
        # ``biomes`` whitelists land cover; ``civilized`` affects road connection probability.
        "types": {
            "city": {
                "count": 1,
                "min_spacing": 40,
                "civilized": True,
                "biomes": ["grassland", "savanna", "forest", "shrubland"],
                "elevation_max": 0.70,
                "near_freshwater": 0.6,
                "coastal": 0.2,
                "floors": 1,
            },
            "town": {
                "count": 3,
                "min_spacing": 24,
                "civilized": True,
                "biomes": ["grassland", "savanna", "forest", "shrubland", "beach"],
                "elevation_max": 0.72,
                "near_freshwater": 0.5,
                "coastal": 0.3,
                "floors": 1,
            },
            "village": {
                "count": 7,
                "min_spacing": 12,
                "civilized": True,
                "biomes": ["grassland", "savanna", "forest", "shrubland", "taiga"],
                "elevation_max": 0.74,
                "near_freshwater": 0.5,
                "coastal": 0.1,
                "floors": 1,
            },
            "tower": {
                "count": 4,
                "min_spacing": 16,
                "civilized": False,
                "biomes": ["mountain", "grassland", "forest", "tundra", "shrubland"],
                "elevation_min": 0.55,
                "remoteness": 0.5,
                "floors": [2, 4],
            },
            "dungeon": {
                "count": 4,
                "min_spacing": 18,
                "civilized": False,
                "biomes": ["mountain", "forest", "tundra", "desert", "swamp"],
                "elevation_min": 0.45,
                "remoteness": 0.7,
                "floors": [2, 5],
            },
            "ruin": {
                "count": 5,
                "min_spacing": 14,
                "civilized": False,
                "biomes": ["grassland", "forest", "desert", "savanna", "tundra", "jungle"],
                "remoteness": 0.6,
                "floors": 1,
            },
            "camp": {
                "count": 6,
                "min_spacing": 10,
                "civilized": False,
                "biomes": ["grassland", "forest", "tundra", "shrubland", "savanna", "taiga"],
                "remoteness": 0.3,
                "floors": 1,
            },
            "boat": {
                "count": 5,
                "min_spacing": 14,
                "civilized": False,
                "biomes": ["ocean", "lake"],
                "on_water": True,
                "floors": 1,
            },
        },
    },
    # -------------------------------------------------------------- POI interiors
    "interiors": {
        "partition": "bsp",  # "bsp" (in-house default) or "tcod_bsp"
        # Each POI interior is generated once at a CANONICAL resolution of cells_per_tile detail cells
        # per world tile across its footprint, then the detail renderer samples that single artifact
        # into whatever cell block the current scale provides - so the zoom and local views are coarse
        # vs fine samplings of the SAME interior (mirroring the biome-blend philosophy).
        "cells_per_tile": 6,
        "room_min": 4,  # min room side in detail cells
        "room_max": 10,
        # Coast strip (in canonical detail cells) kept clear between a structure and any water its
        # footprint clips: the buildable area is pulled back this many cells from the water, so a band of
        # bare biome floor (beach/grass via the blend) reads as a little shoreline around the structure -
        # like the biome blend. 0 builds right up to the water's edge. Only affects coastal POIs.
        "coast_margin": 2,
        # When a coastal footprint loses land to the water it clips, grow the footprint (keeping the
        # anchor centred) until its dry-land area is back to nominal, capped at this multiple of the
        # nominal footprint area. Growth never overlaps another POI; water is simply carved again. 1.0
        # (or less) disables the restoration, so carved coastal structures stay smaller.
        "expand_max_factor": 2.0,
        "clutter_density": 0.10,  # fraction of free interior cells that receive clutter/furniture
        "ruin_erosion": 0.45,  # fraction of a ruined structure carved away by erosion noise
        # Per-POI footprint size variation (fraction). Each footprint dimension of a kind that HAS an
        # interior builder is scaled by a deterministic factor in [1-jitter, 1+jitter], so structures
        # of the same kind spawn a bit larger or smaller. 0 disables (every footprint stays nominal).
        "size_jitter": 0.4,
        # Outer-boundary SHAPE algorithm for the solid-building archetypes (dungeon/tower/ruin; see
        # biomegen.world.interiors.shapes / SHAPES registry): "rectangle" (boxy), "blob", "cellular",
        # "drunkard", "diamond", "cross", or "mixed" (default) to pick a different organic shape per
        # structure so none is square. The shape is filled solid with rooms+rock; terrain shows around
        # its organic outline. (Settlements, camps and boats use their own layout, not this shape.)
        "shape": "mixed",
        # Per-kind interior footprint in WORLD TILES (w, h), centred on the POI anchor. Render-only
        # metadata (the base ``poi_index`` array still marks just the anchor). Every kind below has an
        # interior builder (Phase 5 complete); only ``bridge`` (placed by the roads stage, absent here)
        # stays a plain map marker.
        "footprints": {
            "dungeon": [6, 4],
            "tower": [3, 3],
            "city": [7, 5],
            "town": [5, 4],
            "village": [4, 3],
            "ruin": [4, 3],
            "camp": [3, 3],
            "boat": [3, 2],
        },
    },
    # -------------------------------------------------------------- roads
    "roads": {
        "pathfinder": "astar",  # "astar" (in-house default), "tcod", or "dijkstra"
        "k_neighbors": 5,  # candidate edges per POI (k-nearest)
        "civilized_connect_prob": 0.9,  # keep-probability for edges between civilized POIs
        "uncivilized_connect_prob": 0.25,  # keep-probability for edges touching uncivilized POIs
        "extra_edge_prob": 0.15,  # chance to keep a non-tree candidate edge (creates loops)
        "base_cost": 1.0,  # per-step movement cost on flat ground
        "uphill_surcharge": 2.5,  # extra cost factor for climbing (makes roads contour)
        "slope_cost": 6.0,  # cost factor on absolute elevation change
        "water_cost": 14.0,  # cost to cross a water tile: high enough that roads prefer land and
        # never run ALONG a river, but low enough that crossing a narrow river
        # (a bridge) beats a long detour. Ocean is unroutable regardless.
        "mountain_cost": 14.0,  # extra cost over mountain/snow tiles
        "road_discount": 0.3,  # cost multiplier when reusing an existing road tile (encourages joins)
        "turn_cost": 0.1,  # flat penalty added whenever the path changes direction; values in
        # the 1–3× base_cost range reduce zigzagging without over-straightening
        "meander_strength": 0.30,  # deterministic per-tile noise added to cost so paths curve
        # Bridges: when a road is forced to cross a river/water tile, a "bridge" POI is placed there
        # and the crossing tile is flagged as a bridge (implemented with the roads stage in Phase 4).
        "bridges": True,
    },
    # -------------------------------------------------------------- naming / lore
    "naming": {
        "markov_order": 2,
        "max_name_len": 12,
        "min_name_len": 4,
        # Per-category generator: "syllable" (default; clean culture-distinct roots + affixes) or
        # "markov" (order-2 chain over a per-culture corpus; organic but rougher with affixes).
        "generators": {
            "island": "syllable",
            "region": "syllable",
            "poi": "syllable",
            "river": "syllable",
            "lake": "syllable",
        },
        "lore_min": 1,
        "lore_max": 4,
    },
    # -------------------------------------------------------------- rendering / UI
    "render": {
        # Detail views. There are three view scales: the biome map, "zoom" (mid), and "local" (close).
        # Both detail scales are aspect-corrected: cell HEIGHT sets the magnification and cell width is
        # widened by cell_aspect so a biome tile reads ~square (terminal cells are taller than wide).
        "zoom_scale": 5,  # ZOOM scale: detail-cell height per biome tile (width = x cell_aspect)
        # LOCAL scale: the screen shows roughly this many biome tiles vertically, each magnified.
        "local_rows": 5,
        "cell_aspect": 1.0,
        # Biome blending at the detail scales: each detail cell looks up the biome at its world
        # position perturbed by a coherent noise warp, so tile boundaries become irregular/interleaved
        # and the square biome grid is hard to see. The warp is a function of world position only, so
        # the zoom and local views are consistent samplings of the same blend (they look like zooms of
        # each other). 0 strength = crisp grid.
        "blend_strength": 0.85,  # how far (in tiles) the biome boundary can bleed
        "blend_scale": 2.5,  # feature size (tiles) of the blend warp (larger = broader fingers)
        # Water gets a special blend: a detail cell is water when the bilinear "water coverage" of the
        # surrounding tiles exceeds this threshold. A value below 0.5 fills the gap between two
        # diagonally-adjacent (corner-touching) water tiles, so rivers/lakes read as connected instead
        # of a checkerboard. Lower = more water bleed.
        "water_blend_threshold": 0.42,
        "default_view": "fit",  # "fit" (whole map downsampled) or "onetoone" (1:1 panning)
        "status_height": 12,  # rows reserved below the map for the status/legend panel
        "show_legend": True,
        "try_truecolor": True,  # attempt per-region RGB via init_color where the terminal allows
        # Biome -> RGB base colour (0-255). The single source of truth for both curses and SVG/PNG.
        "palette": {
            "ocean": [28, 70, 140],
            "lake": [60, 120, 205],
            "river": [80, 140, 220],
            "beach": [240, 226, 165],
            "grassland": [120, 190, 92],
            "shrubland": [156, 176, 86],
            "savanna": [200, 196, 110],
            "forest": [46, 135, 60],
            "jungle": [24, 110, 44],
            "taiga": [96, 142, 112],
            "desert": [226, 200, 124],
            "tundra": [176, 184, 174],
            "swamp": [82, 110, 84],
            "mountain": [134, 128, 122],
            "snow": [244, 246, 250],
        },
        # Biome -> single display glyph. ASCII by default for maximum windows-curses compatibility;
        # override with unicode in your own config if your terminal handles it.
        "glyphs": {
            "ocean": "~",
            "lake": "~",
            "river": "~",
            "beach": ".",
            "grassland": ",",
            "shrubland": ";",
            "savanna": '"',
            "forest": "f",
            "jungle": "F",
            "taiga": "t",
            "desert": ":",
            "tundra": "u",
            "swamp": "w",
            "mountain": "^",
            "snow": "*",
        },
        # Overlay glyphs drawn on top of biome cells.
        "markers": {
            "road": "+",
            "city": "C",
            "town": "T",
            "village": "v",
            "tower": "I",
            "dungeon": "D",
            "ruin": "r",
            "camp": "a",
            "boat": "b",
            "bridge": "=",
            "cursor": "X",
        },
        # Glyphs for interior Cell values (used by the zoom view from Phase 5).
        "interior_glyphs": {
            "floor": ".",
            "wall": "#",
            "door": "/",
            "stairs_up": "<",
            "stairs_down": ">",
            "water": "~",
            "path": ":",
            "bed": "=",
            "table": "T",
            "chair": "h",
            "chest": "$",
            "hearth": "*",
            "barrel": "o",
            "crate": "%",
            "shelf": "=",
            "rubble": "&",
            "tent": "^",
            "campfire": "*",
            "wagon": "W",
            "tree": "t",
            "rock": "o",
            "bush": '"',
            "cargo": "$",
            "void": " ",
        },
        # Interior Cell -> RGB base colour, used when a detail cell belongs to a POI interior (the
        # single colour authority for interiors, shared with SVG/PNG export later). ``void`` is never
        # drawn (the surrounding terrain shows through), so it has no colour entry.
        "interior_palette": {
            "floor": [78, 66, 55],
            "wall": [128, 118, 105],
            "door": [186, 150, 84],
            "stairs_up": [214, 214, 168],
            "stairs_down": [150, 156, 214],
            "water": [80, 140, 220],
            "path": [120, 108, 84],
            "bed": [150, 120, 150],
            "table": [160, 120, 80],
            "chair": [140, 104, 70],
            "chest": [216, 176, 72],
            "hearth": [226, 120, 60],
            "barrel": [150, 116, 70],
            "crate": [168, 132, 80],
            "shelf": [150, 120, 84],
            "rubble": [110, 104, 98],
            "tent": [180, 170, 120],
            "campfire": [230, 130, 60],
            "wagon": [150, 110, 70],
            "tree": [60, 130, 60],
            "rock": [130, 124, 116],
            "bush": [110, 150, 90],
            "cargo": [200, 170, 90],
            "reserved": [128, 128, 128],
        },
    },
    # -------------------------------------------------------------- export (in-game keypress)
    "export": {
        "dir": "./images",
        "cell_px": 12,  # pixel size of one tile in exported images
        "png": True,  # also write a PNG (via Pillow) next to the SVG
        "filename_pattern": "{name}_{seed}_{view}",
    },
    # -------------------------------------------------------------- key bindings
    "keys": {
        "zoom": " ",  # step OUT a zoom level: biome<->zoom, and local->zoom
        "local": "z",  # step IN to the deeper "local" scale (zoom->local). Rebindable; most
        # terminals can't distinguish Shift+Space from Space, so a real key is used.
        "floor_up": "<",  # cycle to the floor above (towers)
        "floor_down": ">",  # cycle to the floor below (dungeons)
        "export_view": "e",  # export the current view to ./images
        "export_world": "E",  # export the whole island map to ./images
        "toggle_scale": "f",  # toggle fit-to-screen <-> 1:1 panning
        "refresh": "r",  # regenerate the world with a fresh random seed
        "quit": "q",
    },
    # -------------------------------------------------------------- controls / cursor movement
    "controls": {
        # Holding Shift with an arrow key (or using capital W/A/S/D / H/J/K/L) moves this many tiles
        # at once for fast travel across the map.
        "fast_step": 8,
    },
}


def get_defaults() -> Dict[str, Any]:
    """Return a deep copy of :data:`DEFAULTS` so callers can merge/mutate without side effects."""
    return deepcopy(DEFAULTS)
