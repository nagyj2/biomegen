"""Defaults for the ``render`` section (rendering / UI)."""

from __future__ import annotations

from typing import Any, Dict

VALUES: Dict[str, Any] = {
    # Detail views. There are three view scales: the biome map, "zoom" (mid), and "local" (close).
    # Both detail scales are aspect-corrected: cell HEIGHT sets the magnification and cell width is
    # widened by cell_aspect so a biome tile reads ~square (terminal cells are taller than wide).
    "zoom_scale": 5,  # ZOOM scale: detail-cell height per biome tile (width = x cell_aspect)
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
    # (about one row at zoom, two or three at the site view). ``road_min_rows`` keeps it at least that many rows thick
    # when the magnification is low. Because the test is a pure function of world position, every scale draws the same
    # shape. A small coherent ``road_warp`` (in tiles) wobbles the bed so it meanders rather than reading as straight
    # segments. ``road_clutter`` scatters small glyphs along the bed at the detail scales; ``road_clutter_local`` adds
    # extra fine detail at the local scale only.
    "road_half_width": 0.07,
    "road_min_rows": 1.0,
    "road_warp": 0.05,
    "road_bed": {
        "glyphs": {"horizontal": "─", "vertical": "│", "rising": "╱", "falling": "╲"},
        "ascii": {"horizontal": "-", "vertical": "|", "rising": "/", "falling": "\\"},
    },
    "road_clutter": {"glyphs": [".", ",", "'"], "density": 0.18},
    "road_clutter_local": {"glyphs": ['"', ".", ";"], "density": 0.10},
    # Bridges render as a straight deck between the two road pieces they join (at any real angle): a brown ``deck``
    # walkway ``bridge_half_width`` tiles to each side of the span (never under ``road_min_rows`` thick), flanked by
    # ``wall`` railings as wide again. The deck is extended ``bridge_overhang`` tiles past each end so it overlaps the
    # road bed and leaves no gap.
    "bridge_half_width": 0.1,
    "bridge_glyphs": {"deck": ":", "wall": "#"},
    "bridge_overhang": 0.6,
    # Colours of the road bed and bridges at the detail scales (the layered renderer's replacement for the
    # ``palette`` road / bridge entries). ``*_bg`` fills the cell (shaded by the hillshade), ``*_fg`` the glyph.
    "detail_colors": {
        "road_bg": [122, 102, 70],
        "road_fg": [92, 74, 48],
        "deck_bg": [150, 96, 50],
        "deck_fg": [104, 66, 34],
        "wall_bg": [104, 66, 34],
        "wall_fg": [70, 44, 22],
    },
    "default_view": "fit",  # "fit" (whole map downsampled) or "onetoone" (1:1 panning)
    "status_height": 12,  # rows reserved below the map for the status/legend panel
    "show_legend": True,
    # Biome -> RGB base colour (0-255), read by the region stage for each region's base colour (until realms
    # replace regions in phase 6). The renderer's colours come from tables.biomes, not from here.
    "palette": {
        "deep": [28, 70, 140],
        "shallow": [52, 104, 172],
        "seaice": [200, 214, 230],
        "lake": [60, 120, 205],
        "beach": [240, 226, 165],
        "grass": [120, 190, 92],
        "savanna": [200, 196, 110],
        "forest": [46, 135, 60],
        "jungle": [24, 110, 44],
        "taiga": [96, 142, 112],
        "desert": [226, 200, 124],
        "tundra": [176, 184, 174],
        "swamp": [82, 110, 84],
        "snow": [244, 246, 250],
    },
    # Layered renderer (phase 4). A view is an ordered list of layer names (see render.layers) for the map
    # scale, an optional ``detail_layers`` list for the zoom and local scales (empty = the map list), and the
    # name of the colour ramp its ``tint`` layer applies ("" = no tint). Drop or reorder layers freely.
    "views": {
        "terrain": {
            "layers": ["terrain", "relief", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "clutter", "water", "roads", "bridges", "markers", "sites"],
            "tint": "",
        },
        "elevation": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "tint", "water", "roads", "bridges", "markers"],
            "tint": "elevation",
        },
        "temperature": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "tint", "water", "roads", "bridges", "markers"],
            "tint": "temperature",
        },
        "rainfall": {
            "layers": ["terrain", "relief", "tint", "water", "roads", "sites", "markers", "labels", "compass"],
            "detail_layers": ["terrain", "relief", "tint", "water", "roads", "bridges", "markers"],
            "tint": "rainfall",
        },
    },
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
    # land), ``keep_relief`` (keep relief glyphs; otherwise glyphs are blanked), ``water_scale`` (dim
    # water cells by this factor) and ``water_color`` (paint water cells this colour).
    "ramps": {
        "elevation": {
            "field": "elevation_m",
            "label": "Elevation",
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
    # line and a crossing (U+2571-2573). With both kinds, ``junction`` marks three or more meeting neighbours.
    "roads": {
        "fg": [96, 58, 30],
        "glyphs": ["·", "│", "─", "╰", "│", "│", "╭", "├", "─", "╯", "─", "┴", "╮", "┤", "┬", "┼"],
        "ascii": ["+", "|", "-", "+", "|", "|", "+", "+", "-", "+", "-", "+", "+", "+", "+", "+"],
        "diagonal": {"glyphs": ["╱", "╲", "╳"], "ascii": ["/", "\\", "X"]},
        "junction": {"glyphs": "✱", "ascii": "*"},
    },
    # Markers layer: points of interest draw their ``markers`` glyph (below) in bold with this colour pair.
    "marker_style": {"fg": [255, 130, 255], "bg": [70, 20, 70]},
    # Geography labels. ``mode`` of a draw is set by the caller ("all" or "none"). Landmass names are drawn
    # in capitals, letter-spaced unless that would exceed a third of the map width. ``candidates`` is how many
    # positions near a feature's centre (or deepest inland cells) are tried before the label is dropped.
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
        "fill_scale": 0.5,  # label cells use the terrain fill darkened by this factor
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
        "bridge": "=",
    },
    # Glyphs for interior Cell values (drawn by the interiors layer).
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
        "bridge": ":",
        "bridge_wall": "#",
    },
    # Interior glyphs are drawn in the cell colour times this factor on top of the plain cell colour fill.
    "interior_fg_scale": 1.45,
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
}
