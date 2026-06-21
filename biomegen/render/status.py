"""The status / info / legend panel drawn beneath the map.

Shows everything the spec asks for: the tile under the cursor and its coordinates, the biome and POI
there, a colour legend, the current view indicators, and the most recent status message. It is a pure
consumer of the world + view state and draws defensively (never writing outside the panel).
"""

from __future__ import annotations

import curses
from typing import Optional

import numpy as np

from ..config.model import Config
from ..world.tile import BIOME_NAME, Cell
from ..world.world import World
from .glyphs import Glyphs
from .palette import Palette
from .state import ViewState


def safe_addstr(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that silently clips to the screen and ignores the bottom-right-corner curses quirk."""
    if y < 0 or x < 0:
        return
    max_y, max_x = stdscr.getmaxyx()
    if y >= max_y or x >= max_x:
        return
    text = text[: max_x - x]
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass  # writing the final cell raises in curses; harmless to ignore


def _legend_entries(biome_ints: set[int], glyphs: Glyphs) -> list[tuple[str, str, int]]:
    """Return (glyph, name, biome_int) for the given biome ints, in stable display order."""
    return [(glyphs.biome_glyph(b), BIOME_NAME[b], b) for b in sorted(biome_ints)]


def _interior_legend_entries(cell_ints: set[int], glyphs: Glyphs) -> list[tuple[str, str, int]]:
    """Return (glyph, name, cell_int) for interior Cell ints, skipping VOID, in stable order."""
    return [(glyphs.interior_glyph(c), Cell(c).name.lower(), c) for c in sorted(cell_ints) if c != int(Cell.VOID)]


def draw(
    stdscr: curses.window,
    world: World,
    config: Config,
    vs: ViewState,
    glyphs: Glyphs,
    palette: Palette,
    top: int,
    height: int,
    width: int,
    visible_biomes: Optional[set[int]] = None,
    visible_cells: Optional[set[int]] = None,
) -> None:
    """Render the status panel into rows [top, top+height).

    ``visible_biomes`` is the set of biome ints currently on screen; the legend lists only those (so
    it reflects what you can actually see). If omitted, every biome present in the world is shown.
    ``visible_cells`` is the set of interior :class:`~biomegen.world.tile.Cell` ints on screen; when
    non-empty a second legend row is drawn beneath the biome row.
    """
    if height <= 0:
        return
    # A divider line marks the top of the panel.
    safe_addstr(stdscr, top, 0, "-" * width)

    if vs.scale != "biome":
        view_label = vs.scale.upper()  # ZOOM or LOCAL
    else:
        view_label = "1:1" if vs.mode == "onetoone" else "FIT"
    island = world.island_name or "(unnamed isle)"
    safe_addstr(
        stdscr, top + 1, 0, f" {island}   seed {world.seed}   view {view_label}   floor {vs.floor}", curses.A_BOLD
    )

    # Tile under the cursor.
    tv = world.view(vs.cx, vs.cy)
    safe_addstr(
        stdscr,
        top + 2,
        0,
        f" cursor ({vs.cx},{vs.cy})  biome {tv.biome_name}  water {tv.water_type.name.lower()}"
        f"  elev {tv.elevation:.2f}  temp {tv.temperature:.2f}  moist {tv.moisture:.2f}",
    )

    # Region under the cursor + a line of its lore.
    region = world.region_at(vs.cx, vs.cy)
    if region is not None:
        rname = region.name or f"region #{region.id}"
        safe_addstr(stdscr, top + 3, 0, f" {rname}  (mostly {BIOME_NAME[region.biome_class]}, {region.size} tiles)")
        if region.lore:
            safe_addstr(stdscr, top + 4, 1, region.lore[0][: max(0, width - 2)], curses.A_DIM)
    else:
        safe_addstr(stdscr, top + 3, 0, " region: open ocean")

    # POI under the cursor.
    poi = world.poi_at(vs.cx, vs.cy)
    if poi is not None:
        pname = poi.name or poi.kind
        safe_addstr(stdscr, top + 5, 0, f" POI: {pname} ({poi.kind})")
    else:
        safe_addstr(stdscr, top + 5, 0, " POI: -")

    # Legend (colour swatches + names), wrapped across the remaining rows above the last line.
    legend_top = top + 6
    legend_bottom = top + height - 1  # leave the final row for the message/controls line
    if config.get("render.show_legend", True) and legend_top < legend_bottom:
        safe_addstr(stdscr, legend_top, 0, " legend:")
        x = 9
        y = legend_top
        if visible_biomes is None:
            visible_biomes = {int(v) for v in np.unique(world.biome)}
        for glyph, name, biome_int in _legend_entries(visible_biomes, glyphs):
            entry = f"{glyph} {name}  "
            if x + len(entry) >= width:
                y += 1
                x = 9
                if y >= legend_bottom:
                    break
            safe_addstr(stdscr, y, x, glyph, palette.biome_attr(biome_int))
            safe_addstr(stdscr, y, x + 1, f" {name}  ")
            x += len(entry)

        # Interior items row — only shown when interior cells are visible (zoom/local scale).
        interior_entries = _interior_legend_entries(visible_cells or set(), glyphs)
        if interior_entries:
            y += 1
            if y < legend_bottom:
                safe_addstr(stdscr, y, 0, " items: ")
                x = 9
                for glyph, name, cell_int in interior_entries:
                    entry = f"{glyph} {name}  "
                    if x + len(entry) >= width:
                        y += 1
                        x = 9
                        if y >= legend_bottom:
                            break
                    safe_addstr(stdscr, y, x, glyph, palette.interior_attr(cell_int))
                    safe_addstr(stdscr, y, x + 1, f" {name}  ")
                    x += len(entry)

    # Controls + most recent message on the bottom line.
    controls = "[arrows] move  [space] zoom  [z] local  [f] fit/1:1  [r] new  [e/E] export  [q] quit"
    msg = vs.last_message
    bottom = top + height - 1
    safe_addstr(stdscr, bottom, 0, controls, curses.A_DIM)
    if msg:
        safe_addstr(stdscr, bottom, max(0, width - len(msg) - 1), msg, curses.A_BOLD)
