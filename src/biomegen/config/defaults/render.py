"""Defaults for the ``render`` section (rendering / UI)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Detail views. There are three view scales: the biome map, "zoom" (mid), and "local" (close).
    # Both detail scales are aspect-corrected: cell HEIGHT sets the magnification and cell width is
    # widened by cell_aspect so a biome tile reads ~square (terminal cells are taller than wide).
    "zoom_scale": 4,  # ZOOM scale: detail-cell height per biome tile (width = x cell_aspect)
    # LOCAL scale: the screen shows roughly this many biome tiles vertically, each magnified.
    "local_rows": 4,
    "cell_aspect": 2.0,  # detail-cell width / height; terminal cells are ~2:1 tall
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
    # Roads & bridges at the detail scales (zoom, local, site). Roads render as a thin meandering BED, not a full
    # tile: a detail cell is road when it lies within ``road_half_width`` world tiles of the straight line joining two
    # adjacent road-tile centres, so a road is a fixed fraction of a tile wide and scales with the magnification
    # (about one row at zoom, two at the site view). ``road_min_rows`` keeps it at least that many rows thick and
    # ``road_max_rows`` at most that many (a vertical road is as wide in columns as the cell aspect makes it look)
    # when the magnification is low. Because the test is a pure function of world position, every scale draws the same
    # shape. A small coherent ``road_warp`` (in tiles) wobbles the bed so it meanders rather than reading as straight
    # segments. ``road_clutter`` scatters small glyphs along the bed at the detail scales; ``road_clutter_local`` adds
    # extra fine detail at the local scale only.
    "road_half_width": 0.07,
    "road_min_rows": 1.0,
    "road_max_rows": 2.0,
    "road_warp": 0.05,
    # Rounding of the road bed: where a road tile joins exactly two links the corner is a curve from the middle of one
    # link to the middle of the other, steered by the tile's centre; this is how far (0..1) it is pulled from the
    # chord toward the centre. 1 rounds every bend (a staircase of tiles reads as a gentle curve), 0 keeps the sharp
    # polyline.
    "road_smooth": 1.0,
    # ``road_relax`` pulls a tile of exactly two links this far (0..1) toward the middle of its neighbours before it is
    # rounded, so bends cut deeper and a staircase flows (0.5 leaves a right angle about 0.4 of a tile off its corner).
    "road_relax": 0.5,
    # Long-scale meander: positions drift by up to ``road_meander`` tiles in features about ``road_meander_scale`` tiles
    # across (a pure function of position, so every scale and a site's plan agree), which bends a long straight road
    # into a slow wander. 0 turns it off; keep it under half a tile so a road never strays far from its tiles.
    "road_meander": 0.3,
    "road_meander_scale": 5.0,
    "road_bed": {
        "glyphs": {"horizontal": "─", "vertical": "│", "rising": "╱", "falling": "╲"},
        "ascii": {"horizontal": "-", "vertical": "|", "rising": "/", "falling": "\\"},
    },
    "road_clutter": {"glyphs": [".", ",", "'"], "density": 0.18},
    "road_clutter_local": {"glyphs": ['"', ".", ";"], "density": 0.10},
    # A road over water is a bridge, drawn from the same bed: a ``deck`` where the bed lies over water and ``wall``
    # railings in the band as wide again beside it.
    "bridge_glyphs": {"deck": ":", "wall": "#"},
    # Colours of the road bed and bridges at the detail scales. ``*_bg`` fills the cell (shaded by the hillshade),
    # ``*_fg`` the glyph.
    "detail_colors": {
        "road_bg": [122, 102, 70],
        "road_fg": [92, 74, 48],
        "deck_bg": [150, 96, 50],
        "deck_fg": [104, 66, 34],
        "wall_bg": [104, 66, 34],
        "wall_fg": [70, 44, 22],
    },
    "default_view": "onetoone",  # "fit" (whole map downsampled) or "onetoone" (1:1 panning)
    "status_height": 15,  # rows reserved below the map for the status/legend panel
    "panel_events": 4,  # events the panel lists in the political view: the latest at the cursor, then the realm's
    "legend_rows": 3,  # rows the panel's legend always takes; it grows past this only when what is on screen needs more
    # The explorer's render cache (render/cache.py). At the zoom, local and site scales the terrain layers are drawn
    # once into chunks of chunk_cols x chunk_rows cells and reused while panning; at most max_cells cells are kept
    # (about 14 bytes each), the least recently shown dropped first. The map scales keep their last map_frames frames.
    "cache": {
        "chunk_cols": 32,
        "chunk_rows": 16,
        "max_cells": 4_000_000,
        "map_frames": 8,
        # While it waits for a key the explorer draws the chunks round the screen, out to this many screens on every
        # side (0 = off), and builds the ground-floor plans of the sites within prefetch_site_km of the cursor.
        "prefetch_screens": 1.0,
        "prefetch_site_km": 600.0,
    },
    "show_legend": True,
    # Layered renderer (phase 4). A view is an ordered list of layer names (see render.layers) for the map
    # scale, an optional ``detail_layers`` list for the zoom and local scales (empty = the map list), and the
    # name of the colour ramp its ``tint`` layer applies ("" = no tint). Drop or reorder layers freely.
    "views": {
        "terrain": {
            "layers": ["terrain", "relief", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "clutter", "water", "roads", "sites", "markers"],
            "tint": "",
        },
        "political": {
            "layers": [
                "terrain",
                "relief",
                "tint",
                "water",
                "borders",
                "roads",
                "sites",
                "markers",
                "labels",
                "compass",
            ],
            "detail_layers": ["terrain", "relief", "clutter", "tint", "water", "borders", "roads", "sites", "markers"],
            "tint": "realm",
        },
        "elevation": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "clutter", "tint", "water", "roads", "sites", "markers"],
            "tint": "elevation",
        },
        "temperature": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "clutter", "tint", "water", "roads", "sites", "markers"],
            "tint": "temperature",
        },
        "rainfall": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "clutter", "tint", "water", "roads", "sites", "markers"],
            "tint": "rainfall",
        },
    },
    # Realm tint (``tint = "realm"`` in a view): land is desaturated toward its own grey by ``desaturate`` (1 = grey)
    # and mixed toward the colour of its realm by ``mix``. Land no realm holds is that grey scaled by ``wild_scale``
    # plus ``wild_offset`` (0..255), a flat dull ground.
    "realm_tint": {"desaturate": 1.0, "mix": 0.62, "wild_scale": 0.5, "wild_offset": 40},
    # Borders layer: the cell on one side of a border between two realms (the one with the larger id; wild land counts
    # as -1) is lightened toward white by ``lighten``, or by ``vassal_lighten`` when the two belong to the same
    # overlord. Where ``World.front`` marks a war, the line is mixed toward ``front_color`` by ``front_mix`` instead.
    "borders": {"lighten": 0.5, "vassal_lighten": 0.2, "front_color": [200, 25, 25], "front_mix": 0.85},
    # Fit-to-screen map: when a cell covers a block of tiles it shows the block's most salient tile. A tile's
    # priority is the larger of its biome's and relief's ``priority`` (data/biomes.toml), raised to ``road`` on a
    # road tile and ``poi`` on a point of interest; rivers count as ``river``. Higher wins, first tile on a tie.
    "fit_priority": {"poi": 100, "road": 90, "river": 75},
    # Clutter layer (zoom and local). A detail row's ``factor`` scales its density per cell: moisture (0..1)
    # or relative elevation (0..1, over the world's highest point) is mapped to ``base + slope * value`` and
    # clamped to [min, max]. The rows themselves are ``tables.detail`` / ``tables.detail_relief``.
    "clutter_factors": {
        "moisture": {"base": 0.4, "slope": 1.4, "min": 0.25, "max": 1.8},
        "elevation": {"base": 0.4, "slope": 1.3, "min": 0.25, "max": 1.8},
    },
    # Data-view colour ramps, named by the ``tint`` of a view. ``field`` is the World array coloured;
    # ``stops`` are ``[value, [r, g, b]]`` in ascending value order, blended linearly. elevation is in
    # metres, temperature in degrees C, rainfall in mm per year; ``label`` and ``unit`` (``unit_ascii`` for
    # ascii output) title the legend bar. Optional keys: ``shade`` (hillshade the
    # land), ``keep_relief`` (keep relief glyphs; otherwise glyphs are blanked), ``keep_clutter`` (at the zoom and
    # local scales keep the clutter glyphs, dimmed against the ramp colour, so the tint lies over the ground's
    # texture; the floor glyph is still blanked), ``water_scale`` (dim water cells by this factor) and
    # ``water_color`` (paint water cells this colour).
    "ramps": {
        "elevation": {
            "field": "elevation_m",
            "label": "Elevation",
            "keep_clutter": True,
            "unit": "m",
            "shade": True,
            "keep_relief": True,
            "stops": [
                [-6000, [8, 20, 60]],
                [-3000, [16, 40, 96]],
                [-1000, [28, 66, 130]],
                [-200, [46, 100, 165]],
                [0, [90, 150, 196]],
                [1, [64, 132, 72]],
                [300, [122, 170, 92]],
                [800, [200, 194, 120]],
                [1700, [178, 134, 86]],
                [3200, [140, 112, 98]],
                [5000, [236, 236, 240]],
                [8000, [255, 255, 255]],
            ],
        },
        "temperature": {
            "field": "temperature_c",
            "label": "Temperature, mean annual",
            "keep_clutter": True,
            "unit": "°C",
            "unit_ascii": "degC",
            "water_scale": 0.6,
            "stops": [
                [-25, [120, 60, 170]],
                [-10, [70, 110, 220]],
                [0, [150, 200, 240]],
                [8, [120, 200, 120]],
                [16, [230, 220, 100]],
                [24, [240, 150, 60]],
                [32, [200, 40, 40]],
            ],
        },
        "rainfall": {
            "field": "rain_mm",
            "label": "Rainfall, mean annual",
            "keep_clutter": True,
            "unit": "mm/yr",
            "water_color": [16, 30, 60],
            "stops": [
                [0, [200, 160, 100]],
                [250, [225, 205, 130]],
                [600, [170, 200, 110]],
                [1200, [80, 165, 95]],
                [2000, [40, 130, 150]],
                [3200, [40, 70, 170]],
            ],
        },
    },
    # Explorer info panel under the map: ``fg`` is the text colour, ``head`` the island line, ``dim`` the controls and
    # divider, ``bg`` the fill (the panel paints its own background). ``help_*`` colour the ``?`` overlay.
    "panel": {
        "fg": [220, 215, 200],
        "head": [255, 225, 150],
        "dim": [150, 145, 135],
        "bg": [18, 18, 22],
        "help_fg": [235, 230, 215],
        "help_bg": [34, 34, 44],
    },
    "tint_relief_fg": 0.55,  # relief glyphs on a data-ramp fill are the fill darkened by this factor
    # Terrain layer. Hillshade lights each land cell from the north-west: the height difference between
    # its south-east and north-west neighbours, over ``relief_m`` metres, times ``strength``, is added
    # to a brightness of 1 and clamped to [min, max]. Sea brightness uses ``sea_depth_m`` (the depth that
    # draws as full deep ocean). ``sparse_density`` is the share of cells of a sparse biome that show
    # their glyph; ``sea_sparkle`` is the share of deep-ocean cells that show a wave glyph.
    "shade": {"strength": 3.5, "relief_m": 4000.0, "min": 0.72, "max": 1.25},
    "sea_depth_m": 4000.0,
    "sparse_density": 0.45,
    "sea_sparkle": {"density": 0.05, "glyph": "~", "ascii": "~", "boost": 1.6},
    # Relief layer: how each relief class recolours the terrain under its glyph. ``scale`` darkens the
    # fill; ``mix`` blends the fill toward a colour by ``mix_t``; ``bg`` / ``fg`` replace outright.
    # Mountains below ``snow_below_c`` degrees C are snow-capped (``snow_*`` keys).
    "relief_tints": {
        "hills": {"scale": 0.9},
        "mountain": {
            "mix": [128, 114, 100],
            "mix_t": 0.55,
            "snow_below_c": 0.0,
            "snow_mix": [235, 238, 245],
            "snow_t": 0.55,
            "snow_fg": [90, 90, 110],
        },
        "peak": {"bg": [214, 218, 228], "fg": [110, 110, 130]},
        "volcano": {"bg": [80, 40, 34]},
    },
    # Water layer: fresh water over land (rivers) is a glyph tinted toward ``river_mix``; the tint is
    # weaker over a data-view ramp (``river_mix_t_tinted``) so the ramp stays readable.
    "water": {
        "river_glyph": "~",
        "river_ascii": "~",
        "river_fg": [150, 205, 255],
        "river_mix": [40, 100, 180],
        "river_mix_t": 0.6,
        "river_mix_t_tinted": 0.35,
    },
    # Roads layer: a road cell draws the glyph for which of its eight neighbours are also road. With only
    # orthogonal neighbours (north 1, east 2, south 4, west 8) ``glyphs`` / ``ascii`` are indexed by that 0..15
    # mask (box drawing, U+2500 block). With only diagonal neighbours ``diagonal`` gives a rising line, a falling
    # line and a crossing (U+2571-2573). With both kinds, ``junction`` marks three or more meeting neighbours; it is the
    # box-drawing cross, the same small glyph as an orthogonal crossroads, so the set stays cohesive.
    "roads": {
        "fg": [96, 58, 30],
        "glyphs": ["·", "│", "─", "╰", "│", "│", "╭", "├", "─", "╯", "─", "┴", "╮", "┤", "┬", "┼"],
        "ascii": ["+", "|", "-", "+", "|", "|", "+", "+", "-", "+", "-", "+", "+", "+", "+", "+"],
        "diagonal": {"glyphs": ["╱", "╲", "╳"], "ascii": ["/", "\\", "X"]},
        "junction": {"glyphs": "┼", "ascii": "+"},
    },
    # Markers layer: points of interest draw their ``markers`` glyph (below) in bold with this colour pair. At the
    # detail scales only those listed in ``detail_marker_scales`` draw it: the zoom scale shows the POI's kind over
    # its small plan, while the local and site scales show the plan itself, so a marker would only cover it.
    "marker_style": {"fg": [255, 130, 255], "bg": [70, 20, 70]},
    "detail_marker_scales": ["zoom"],
    # Geography labels. ``mode`` of a draw is set by the caller ("all" or "none"). Landmass names are drawn
    # in capitals, letter-spaced unless that would exceed a third of the map width. ``candidates`` is how many
    # positions near a feature's centre (or deepest inland cells) are tried before the label is dropped. In the
    # political view the landmass and range names give way to realm names: the short name in capitals of each
    # realm of a kind in ``realm_kinds`` and of at least ``realm_min_area_km2``, largest first, in the realm's colour
    # lightened toward white by ``realm_lighten``, tried at ``realm_candidates`` positions near the realm's centre.
    "labels": {
        "landmass_fg": [255, 236, 180],
        "range_fg": [235, 222, 205],
        "sea_fg": [170, 210, 255],
        "lake_fg": [190, 225, 255],
        "max_landmasses": 6,
        "max_ranges": 6,
        "max_lakes": 3,
        "landmass_candidates": 80,
        "range_candidates": 40,
        "lake_candidates": 10,
        # A sea's name goes in the middle of its water: among the salt-water tiles nearest that sea's anchor, those
        # farthest from both land and the map edge come first; this many are tried, and every letter must be on water.
        "sea_candidates": 60,
        "fill_scale": 0.5,  # label cells use the terrain fill darkened by this factor
        "realm_kinds": ["major", "tribal"],
        "realm_min_area_km2": 25000.0,
        "realm_candidates": 80,
        "realm_lighten": 0.6,
    },
    # Legend and gazetteer text for a static map: colours, the swatch column width, and how many features
    # of each kind are listed. ``continent_km2`` is the area above which a landmass is called a continent.
    "legend": {
        "header_fg": [255, 225, 150],
        "text_fg": [220, 215, 200],
        "dim_fg": [160, 155, 145],
        "column_width": 24,
        "max_landmasses": 6,
        "max_ranges": 5,
        "max_lakes": 3,
        "continent_km2": 1500000.0,
        # The realms and diplomacy sections of a political legend: the swatch glyph before each realm name, the
        # width the relation tag is padded to, and each relation kind's tag and colour.
        "realm_swatch": "■",
        "realm_swatch_ascii": "#",
        "relation_tag_width": 11,
        "relations": {
            "war": {"tag": "WAR", "fg": [255, 90, 80]},
            "rivalry": {"tag": "RIVALRY", "fg": [255, 170, 80]},
            "alliance": {"tag": "ALLIANCE", "fg": [120, 220, 120]},
            "trade": {"tag": "TRADE PACT", "fg": [120, 200, 255]},
        },
    },
    # Frame furniture around a static map. ``margin`` is the width of the latitude gutter. Graticule ticks
    # use the first step in ``lat_steps`` / ``lon_steps`` (degrees) that leaves at least ``lat_tick_rows``
    # rows / ``lon_tick_cols`` columns between ticks. The scale bar picks the ``scale_km`` length nearest
    # to 1/``scale_fraction`` of the map width. ``frame_unicode`` / ``frame_ascii`` list, in order: horizontal,
    # vertical, four corners (tl tr bl br), left tick, right tick, bottom tick. The compass rose is drawn
    # in the first corner of the map that is open sea.
    "furniture": {
        "margin": 6,
        "frame_fg": [150, 140, 120],
        "dim_fg": [130, 125, 115],
        "frame_unicode": "═║╔╗╚╝╟╢╧",
        "frame_ascii": "-|+++++++",
        "title": " The World of {name}{sep}seed {seed}{sep}{style}{sep}{km_w} x {km_h} km ",
        "title_sep": {"unicode": " · ", "ascii": " - "},
        "lat_steps": [1, 2, 5, 10, 15, 30],
        "lat_tick_rows": 4,
        "lon_steps": [1, 2, 5, 10, 15, 20, 30, 45],
        "lon_tick_cols": 12,
        "scale_km": [100, 200, 250, 500, 1000, 1500, 2000, 3000],
        "scale_fraction": 6,
        "compass_fg": [240, 230, 200],
        "compass": {"unicode": ["  N  ", "W─┼─E", "  S  "], "ascii": ["  N  ", "W-+-E", "  S  "]},
    },
    # Overlay glyphs drawn on top of biome cells for the kinds that are not settlement tiers (a tier's marker comes
    # from its tables.tiers row).
    "markers": {
        "tower": "I",
        "dungeon": "D",
        "ruin": "r",
        "camp": "a",
        "boat": "b",
        "battlefield": "x",
        "watchtower": "W",
        "shrine": "s",
        "bridge": "=",
    },
    # Glyphs for interior Cell values (drawn by the interiors layer).
    "interior_glyphs": {
        "floor": ".",
        "wall": "#",
        "door": "/",
        "stairs_up": ">",
        "stairs_down": "<",
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
        "rubble": ",",
        "campfire": "*",
        "wagon": "W",
        "tree": "t",
        "rock": "o",
        "bush": '"',
        "cargo": "$",
        "void": " ",
        "bridge": ":",
        "bridge_wall": "#",
        "solid": " ",
        "stone": "▓",
        "hull": "=",
        "wheel": "○",
        "axle_h": "═",
        "axle_v": "║",
        "grave": "∩",
        "banner": "⚑",
        "bones": "x",
        "wheat": '"',
        "log": "=",
        "post": "●",
        "tarp": "^",
        "tarp_lift": "~",
    },
    # ASCII output replaces any interior glyph that is not 7-bit with the entry here.
    "interior_glyphs_ascii": {
        "stone": "#",
        "wheel": "O",
        "axle_h": "=",
        "axle_v": "|",
        "grave": "n",
        "banner": "P",
        "post": "!",
    },
    # Thin walls: a wall cell draws the line glyph for which of its four neighbours (north 1, east 2, south 4, west 8)
    # are also wall or door, so adjoining walls join into box-drawing lines.
    "interior_walls": {
        "glyphs": ["+", "│", "─", "└", "│", "│", "┌", "├", "─", "┘", "─", "┴", "┐", "┤", "┬", "┼"],
        "ascii": ["+", "|", "-", "+", "|", "|", "+", "+", "-", "+", "-", "+", "+", "+", "+", "+"],
    },
    # Interior glyphs are drawn in the cell colour times this factor on top of the plain cell colour fill.
    "interior_fg_scale": 1.45,
    # Clutter that should not draw the eye: these cells take the floor fill, and a glyph only this factor brighter.
    "interior_subtle": ["rubble", "rock", "barrel", "crate", "cargo"],
    "interior_subtle_fg_scale": 1.2,
    # Marks on the ground that must stay easy to read: they take the floor fill and keep their own glyph colour.
    "interior_on_floor": ["bones"],
    # Interior Cell -> RGB base colour, used when a detail cell belongs to a POI interior (the
    # single colour authority for interiors, shared with SVG/PNG export later). ``void`` is never
    # drawn (the surrounding terrain shows through), so it has no colour entry.
    "interior_palette": {
        "floor": [78, 66, 55],
        "wall": [96, 88, 80],
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
        "campfire": [230, 130, 60],
        "wagon": [150, 110, 70],
        "tree": [60, 130, 60],
        "rock": [130, 124, 116],
        "bush": [110, 150, 90],
        "cargo": [200, 170, 90],
        "reserved": [128, 128, 128],
        "solid": [30, 27, 26],
        "stone": [118, 112, 104],
        "hull": [128, 92, 58],
        "wheel": [150, 104, 64],
        "axle_h": [128, 88, 52],
        "axle_v": [128, 88, 52],
        "grave": [122, 114, 100],
        "banner": [200, 62, 62],
        "bones": [206, 200, 184],
        "wheat": [214, 184, 70],
        "log": [140, 100, 62],
        "post": [112, 78, 48],
        "tarp": [196, 184, 140],
        "tarp_lift": [168, 156, 114],
    },
}
