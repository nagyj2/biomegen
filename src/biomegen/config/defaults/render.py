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
    # Roads & bridges at the detail (zoom/local) scales. Roads render as a thin meandering BED, not
    # a full tile: a detail cell is road when it lies within ``road_half_width`` world tiles of the
    # straight line joining two adjacent road-tile centres. Because that test is a pure function of
    # world position, zoom and local are the same shape at different scales (exactly like rivers). A
    # small coherent ``road_warp`` (in tiles) wobbles the bed so it meanders organically rather than
    # reading as straight segments. ``road_clutter`` scatters small glyphs along the bed at both
    # detail scales; ``road_clutter_local`` adds extra fine detail only at the close (local) scale.
    "road_half_width": 0.30,
    "road_warp": 0.18,
    "road_glyph": ":",
    "road_clutter": {"glyphs": [".", ",", "'"], "density": 0.18},
    "road_clutter_local": {"glyphs": ['"', ".", ";"], "density": 0.10},
    # Bridges render as a straight deck between the two road pieces they join (at any real angle): a
    # brown ``deck`` walkway one cell wide flanked by ``wall`` railings on either side. The deck is
    # extended ``bridge_overhang`` tiles past each end so it overlaps the road bed and leaves no gap.
    "bridge_glyphs": {"deck": ":", "wall": "#"},
    "bridge_overhang": 0.6,
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
        # Surface overlays drawn at the detail scales (see road/bridge keys below).
        "road": [122, 102, 70],  # packed-earth road bed
        "bridge": [150, 96, 50],  # bridge deck (brown walkway)
        "bridge_wall": [104, 66, 34],  # bridge railing / wall (darker brown)
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
        "bridge": ":",
        "bridge_wall": "#",
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
}
