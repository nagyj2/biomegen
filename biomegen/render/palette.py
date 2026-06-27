"""The single colour authority for the terminal renderer.

Maps biomes, regions and markers to curses attributes via a **capability ladder** so the app looks
its best on capable terminals and still works on poor ones:

* ``rgb``      - the terminal can redefine colours (``can_change_color``) and has >256 slots
                 (e.g. Windows conhost via windows-curses, COLORS=768): we allocate a true RGB
                 colour per region / biome via ``init_color``.
* ``palette256``- 256-colour fixed palette: colours are mapped to the nearest xterm-256 slot (the
                 6×6×6 cube + greyscale ramp) using ``init_pair`` only, no ``init_color``.  Works
                 on every ``xterm-256color`` terminal including WSL / Windows Terminal where
                 ``can_change_color`` is True but ``init_color`` OSC-4 sequences are unreliable.
* ``basic``    - 8/16 fixed colours: region/biome colour snapped to the nearest ANSI colour.
* ``mono``     - no colour: rely on glyphs alone.

The exact RGB values come from ``render.palette`` and the per-region ``base_color`` computed by the
regions stage - the same numbers the SVG/PNG exporter will use, so the two views agree.
"""

from __future__ import annotations

import curses

from ..config.model import Config
from ..world.tile import (
    BIOME_NAME,
    INTERIOR_COLOR_BASE,
    OVERLAY_COLOR_BASE,
    OVERLAY_COLOR_NAMES,
    Biome,
    Cell,
)
from ..world.world import World

# RGB approximations of all 16 ANSI colours (8 base + 8 bright), for nearest-colour snapping in 'basic' mode.
_ANSI16 = {
    # Base 8 colours
    curses.COLOR_BLACK: (0, 0, 0),
    curses.COLOR_RED: (205, 0, 0),
    curses.COLOR_GREEN: (0, 205, 0),
    curses.COLOR_YELLOW: (205, 205, 0),
    curses.COLOR_BLUE: (40, 90, 220),
    curses.COLOR_MAGENTA: (205, 0, 205),
    curses.COLOR_CYAN: (0, 205, 205),
    curses.COLOR_WHITE: (229, 229, 229),
    # Bright variants (8-15)
    8: (127, 127, 127),  # Bright Black / Gray
    9: (255, 0, 0),  # Bright Red
    10: (0, 255, 0),  # Bright Green
    11: (255, 255, 0),  # Bright Yellow
    12: (85, 170, 255),  # Bright Blue
    13: (255, 0, 255),  # Bright Magenta
    14: (0, 255, 255),  # Bright Cyan
    15: (255, 255, 255),  # Bright White
}

# The six intensity levels used by the xterm 6×6×6 colour cube (indices 16-231).
_CUBE_STEPS = (0, 95, 135, 175, 215, 255)


def _xterm256_index(r: int, g: int, b: int) -> int:
    """Return the closest xterm-256 colour index (16-255) for an sRGB triple without init_color.

    Searches both the 6×6×6 colour cube (16-231) and the 24-step greyscale ramp (232-255) and
    returns whichever minimises squared Euclidean distance.
    """
    ri = min(range(6), key=lambda i: abs(r - _CUBE_STEPS[i]))
    gi = min(range(6), key=lambda i: abs(g - _CUBE_STEPS[i]))
    bi = min(range(6), key=lambda i: abs(b - _CUBE_STEPS[i]))
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_dist = (r - _CUBE_STEPS[ri]) ** 2 + (g - _CUBE_STEPS[gi]) ** 2 + (b - _CUBE_STEPS[bi]) ** 2

    # Greyscale ramp: values 8, 18, 28, …, 238 (24 steps, indices 232-255).
    grey = round(0.299 * r + 0.587 * g + 0.114 * b)
    grey_n = max(0, min(23, round((grey - 8) / 10)))
    grey_actual = 8 + grey_n * 10
    grey_dist = (r - grey_actual) ** 2 + (g - grey_actual) ** 2 + (b - grey_actual) ** 2

    return cube_idx if cube_dist <= grey_dist else 232 + grey_n


def _nearest_ansi(rgb: tuple[int, int, int]) -> int:
    """Return the ANSI colour constant closest to ``rgb`` (squared-distance nearest neighbour, from all 16)."""
    r, g, b = rgb
    best = curses.COLOR_WHITE
    best_d = None
    for color, (cr, cg, cb) in _ANSI16.items():
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = color
    return best


class Palette:
    """Resolves tiles/regions/markers to curses attributes for the active terminal."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.mode = "mono"
        self._region_attr: dict[int, int] = {}
        self._biome_attr: dict[int, int] = {}
        self._interior_attr: dict[int, int] = {}  # Cell int -> attr (POI interior colours)
        self._overlay_attr: dict[int, int] = {}  # overlay colour id -> attr (road / bridge)
        self._ocean_attr = 0
        self._marker_attr = curses.A_BOLD
        self._cursor_attr = curses.A_REVERSE | curses.A_BOLD
        self._next_color = 16  # leave the 16 standard slots alone
        self._next_pair = 1

    # ------------------------------------------------------------------ setup
    def setup(self, world: World) -> None:
        """Probe terminal colour capabilities and allocate pairs. Call once at curses startup."""
        try:
            curses.start_color()
        except Exception:
            self.mode = "mono"
            return
        try:
            curses.use_default_colors()
            self._bg = -1
        except Exception:
            self._bg = curses.COLOR_BLACK

        colors = getattr(curses, "COLORS", 0)
        can_change = False
        try:
            can_change = curses.can_change_color()
        except Exception:
            pass

        # Capability ladder (best → worst):
        #   rgb       : init_color for exact per-region RGB.  Only when COLORS > 256 (conhost
        #               reports 768; standard xterm-256color reports 256).  Terminals that report
        #               can_change_color=True but only have 256 slots often accept init_color
        #               without error yet display the unmodified xterm-256 defaults — falling back
        #               to palette256 avoids that silent-no-op problem entirely.
        #   palette256: map each colour to the closest fixed xterm-256 slot (no init_color).
        #               Works correctly on any xterm-256color terminal including WSL.
        #   basic     : nearest ANSI-8 colour.
        #   mono      : glyphs only.
        try:
            if self.config.get("render.try_truecolor", True) and can_change and colors > 256:
                self._setup_rgb(world)
                self.mode = "rgb"
            elif colors >= 256:
                self._setup_256(world)
                self.mode = "palette256"
            elif colors >= 8:
                self._setup_basic(world)
                self.mode = "basic"
            else:
                self.mode = "mono"
        except Exception:
            self.mode = "mono"

    def _alloc_pair_rgb(self, rgb: tuple[int, int, int]) -> int:
        """Allocate a custom colour + colour pair for an exact RGB; return the pair index."""
        cidx = self._next_color
        pidx = self._next_pair
        curses.init_color(cidx, int(rgb[0] / 255 * 1000), int(rgb[1] / 255 * 1000), int(rgb[2] / 255 * 1000))
        curses.init_pair(pidx, cidx, self._bg)
        self._next_color += 1
        self._next_pair += 1
        return pidx

    def _alloc_pair_256(self, rgb: tuple[int, int, int]) -> int:
        """Allocate a colour pair using the nearest fixed xterm-256 slot; return the pair index."""
        pidx = self._next_pair
        curses.init_pair(pidx, _xterm256_index(*rgb), self._bg)
        self._next_pair += 1
        return pidx

    def _alloc_pair_basic(self, rgb: tuple[int, int, int]) -> int:
        pidx = self._next_pair
        curses.init_pair(pidx, _nearest_ansi(rgb), self._bg)
        self._next_pair += 1
        return pidx

    def _setup_rgb(self, world: World) -> None:
        palette = self.config.get("render.palette")
        # Biome colours (used by the zoom-view floor).
        for biome in Biome:
            rgb = palette.get(BIOME_NAME[int(biome)], [128, 128, 128])
            self._biome_attr[int(biome)] = curses.color_pair(self._alloc_pair_rgb(rgb))
        self._ocean_attr = self._biome_attr[int(Biome.OCEAN)]
        # Per-region colours (the headline feature of this mode).
        for region in world.regions:
            self._region_attr[region.id] = curses.color_pair(self._alloc_pair_rgb(region.base_color))
        # Markers/cursor in bright white / reverse.
        self._marker_attr = curses.color_pair(self._alloc_pair_rgb((255, 255, 255))) | curses.A_BOLD
        self._setup_interior_colors(self._alloc_pair_rgb)
        self._setup_overlay_colors(self._alloc_pair_rgb)

    def _setup_256(self, world: World) -> None:
        palette = self.config.get("render.palette")
        for biome in Biome:
            rgb = palette.get(BIOME_NAME[int(biome)], [128, 128, 128])
            self._biome_attr[int(biome)] = curses.color_pair(self._alloc_pair_256(tuple(rgb)))
        self._ocean_attr = self._biome_attr[int(Biome.OCEAN)]
        for region in world.regions:
            self._region_attr[region.id] = curses.color_pair(self._alloc_pair_256(region.base_color))
        self._marker_attr = curses.color_pair(self._alloc_pair_256((255, 255, 255))) | curses.A_BOLD
        self._setup_interior_colors(self._alloc_pair_256)
        self._setup_overlay_colors(self._alloc_pair_256)

    def _setup_overlay_colors(self, alloc) -> None:
        """Allocate a colour pair per overlay colour id (road / bridge deck / bridge wall).

        ``alloc`` is the mode-appropriate pair allocator; the RGB comes from ``render.palette`` under the
        same names the biome colours use (road, bridge, bridge_wall).
        """
        palette = self.config.get("render.palette")
        for color_id, name in OVERLAY_COLOR_NAMES.items():
            rgb = palette.get(name)
            if rgb is None:
                continue
            self._overlay_attr[color_id] = curses.color_pair(alloc(tuple(rgb)))

    def _setup_interior_colors(self, alloc) -> None:
        """Allocate a colour pair per interior :class:`Cell` from ``render.interior_palette``.

        ``alloc`` is the mode-appropriate pair allocator. VOID is intentionally skipped: it is
        never drawn, so the terrain shows through the gaps in a structure.
        """
        ipal = self.config.get("render.interior_palette")
        for cell in Cell:
            if cell == Cell.VOID:
                continue
            rgb = ipal.get(cell.name.lower())
            if rgb is None:
                continue
            self._interior_attr[int(cell)] = curses.color_pair(alloc(tuple(rgb)))

    def _setup_basic(self, world: World) -> None:
        palette = self.config.get("render.palette")
        for biome in Biome:
            rgb = palette.get(BIOME_NAME[int(biome)], [128, 128, 128])
            self._biome_attr[int(biome)] = curses.color_pair(self._alloc_pair_basic(rgb))
        self._ocean_attr = self._biome_attr[int(Biome.OCEAN)]
        for region in world.regions:
            self._region_attr[region.id] = curses.color_pair(self._alloc_pair_basic(region.base_color))
        self._marker_attr = curses.A_BOLD
        self._setup_interior_colors(self._alloc_pair_basic)
        self._setup_overlay_colors(self._alloc_pair_basic)

    # ------------------------------------------------------------------ queries
    def tile_attr(self, world: World, x: int, y: int) -> int:
        """Attribute for a biome-map tile: coloured by its region (so regions are distinguishable)."""
        if self.mode == "mono":
            return curses.A_NORMAL
        if world.biome[y, x] == int(Biome.OCEAN):
            return self._ocean_attr
        rid = int(world.region_id[y, x])
        if rid in self._region_attr:
            return self._region_attr[rid]
        return self._ocean_attr  # unregioned water (river, lake)

    def biome_attr(self, biome_int: int) -> int:
        """Attribute for a biome floor colour (zoom view)."""
        if self.mode == "mono":
            return curses.A_NORMAL
        return self._biome_attr.get(int(biome_int), curses.A_NORMAL)

    def interior_attr(self, cell_int: int) -> int:
        """Attribute for a POI interior :class:`Cell` colour (detail views)."""
        if self.mode == "mono":
            return curses.A_NORMAL
        return self._interior_attr.get(int(cell_int), curses.A_NORMAL)

    def overlay_attr(self, color_id: int) -> int:
        """Attribute for an overlay colour id (road / bridge); falls back to normal if unmapped."""
        if self.mode == "mono":
            return curses.A_NORMAL
        return self._overlay_attr.get(int(color_id), curses.A_NORMAL)

    def zoom_attr(self, color_id: int) -> int:
        """Resolve a detail-cell colour id to an attribute.

        Ids below :data:`~biomegen.world.tile.INTERIOR_COLOR_BASE` are biome floor colours; ids in the
        interior range are :class:`Cell` colours (``INTERIOR_COLOR_BASE + cell_int``); ids at or above
        :data:`~biomegen.world.tile.OVERLAY_COLOR_BASE` are road/bridge overlay colours (see
        :mod:`biomegen.render.zoom_view`). One dispatcher keeps the renderer's per-cell lookup trivial.
        """
        if color_id >= OVERLAY_COLOR_BASE:
            return self.overlay_attr(color_id)
        if color_id >= INTERIOR_COLOR_BASE:
            return self.interior_attr(color_id - INTERIOR_COLOR_BASE)
        return self.biome_attr(color_id)

    @property
    def marker_attr(self) -> int:
        return self._marker_attr

    @property
    def cursor_attr(self) -> int:
        return self._cursor_attr
