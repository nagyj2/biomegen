"""The single colour authority for the terminal renderer.

Maps biomes, regions and markers to curses attributes via a **capability ladder** so the app looks
its best on capable terminals and still works on poor ones:

* ``rgb``   - the terminal can redefine colours (``can_change_color``) and has enough slots: we
              allocate a true RGB colour per region (its jittered base colour) and per biome via
              ``init_color``. This is the "attempt true per-region colour" path.
* ``basic`` - 8/16 fixed colours: each region/biome colour is snapped to the nearest ANSI colour.
* ``mono``  - no colour: rely on glyphs alone.

The exact RGB values come from ``render.palette`` and the per-region ``base_color`` computed by the
regions stage - the same numbers the SVG/PNG exporter will use, so the two views agree.
"""

from __future__ import annotations

import curses

from ..config.model import Config
from ..world.tile import BIOME_NAME, INTERIOR_COLOR_BASE, Biome, Cell
from ..world.world import World

# RGB approximations of the 8 base ANSI colours, for nearest-colour snapping in 'basic' mode.
_ANSI8 = {
    curses.COLOR_BLACK: (0, 0, 0),
    curses.COLOR_RED: (205, 0, 0),
    curses.COLOR_GREEN: (0, 205, 0),
    curses.COLOR_YELLOW: (205, 205, 0),
    curses.COLOR_BLUE: (40, 90, 220),
    curses.COLOR_MAGENTA: (205, 0, 205),
    curses.COLOR_CYAN: (0, 205, 205),
    curses.COLOR_WHITE: (229, 229, 229),
}


def _nearest_ansi(rgb: tuple[int, int, int]) -> int:
    """Return the ANSI colour constant closest to ``rgb`` (squared-distance nearest neighbour)."""
    r, g, b = rgb
    best = curses.COLOR_WHITE
    best_d = None
    for color, (cr, cg, cb) in _ANSI8.items():
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
        self._ocean_attr = 0
        self._marker_attr = curses.A_BOLD
        self._cursor_attr = curses.A_REVERSE | curses.A_BOLD
        self._next_color = 16  # leave the 16 standard slots alone
        self._next_pair = 1

    # ------------------------------------------------------------------ setup
    def setup(self, world: World) -> None:
        """Probe terminal colour capabilities and allocate pairs. Safe to call once at startup."""
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
            can_change = False

        try:
            if self.config.get("render.try_truecolor", True) and can_change and colors >= 64:
                self._setup_rgb(world)
                self.mode = "rgb"
            elif colors >= 8:
                self._setup_basic(world)
                self.mode = "basic"
            else:
                self.mode = "mono"
        except Exception:
            # Any allocation failure (e.g. init_color silently rejected) -> degrade gracefully.
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

    def _setup_interior_colors(self, alloc) -> None:
        """Allocate a colour pair per interior :class:`Cell` from ``render.interior_palette``.

        ``alloc`` is the mode-appropriate pair allocator (RGB or nearest-ANSI). VOID is intentionally
        skipped: it is never drawn, so the terrain shows through the gaps in a structure.
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

    def zoom_attr(self, color_id: int) -> int:
        """Resolve a detail-cell colour id to an attribute.

        Ids below :data:`~biomegen.world.tile.INTERIOR_COLOR_BASE` are biome floor colours; ids at or
        above it are interior :class:`Cell` colours encoded as ``INTERIOR_COLOR_BASE + cell_int`` (see
        :mod:`biomegen.render.zoom_view`). One dispatcher keeps the renderer's per-cell lookup trivial.
        """
        if color_id >= INTERIOR_COLOR_BASE:
            return self.interior_attr(color_id - INTERIOR_COLOR_BASE)
        return self.biome_attr(color_id)

    @property
    def marker_attr(self) -> int:
        return self._marker_attr

    @property
    def cursor_attr(self) -> int:
        return self._cursor_attr
