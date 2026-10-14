"""Curses-free RGB colour authority for the SVG/PNG exporters.

The terminal renderer's :class:`~biomegen.render.palette.Palette` resolves every tile to a *curses
attribute* (a colour-pair index), which is useless outside a live terminal. The exporters need the
raw ``(r, g, b)`` triples instead. Both read the **same source numbers** - ``render.palette`` (biome
base colours), each region's ``base_color`` (computed by the regions stage), and
``render.interior_palette`` (interior :class:`Cell` colours) - so an exported image is colour-faithful
to what the TUI shows. The resolution *rules* here mirror :class:`Palette` method-for-method:

* :meth:`ExportPalette.tile_rgb` mirrors ``Palette.tile_attr`` (biome map: coloured by region).
* :meth:`ExportPalette.biome_rgb` mirrors ``Palette.biome_attr`` (detail-view biome floor).
* :meth:`ExportPalette.interior_rgb` mirrors ``Palette.interior_attr`` (interior cells).
* :meth:`ExportPalette.zoom_rgb` mirrors ``Palette.zoom_attr`` (decodes a detail colour id).
"""

from __future__ import annotations

from typing import Optional, Tuple

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

RGB = Tuple[int, int, int]

# Page/letterbox background for exports (terminals default to black behind glyphs; out-of-bounds
# cells in a 1:1 / detail view get this). A dark slate keeps a coloured map legible against it.
BACKGROUND: RGB = (12, 12, 16)


def _as_rgb(value, fallback: RGB = (128, 128, 128)) -> RGB:
    """Coerce a config colour (list/tuple of 3 ints) to an ``(r, g, b)`` tuple."""
    if value is None:
        return fallback
    r, g, b = (int(value[0]), int(value[1]), int(value[2]))
    return (r, g, b)


def contrast_rgb(fill: RGB) -> RGB:
    """Return near-black or near-white, whichever reads better as a glyph over ``fill``.

    Uses the Rec. 601 luma; the same heuristic keeps every glyph legible regardless of its tile's
    colour (light glyph on dark terrain, dark glyph on snow/beach/desert).
    """
    luma = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
    return (20, 20, 20) if luma > 140 else (236, 236, 236)


class ExportPalette:
    """Resolves tiles / regions / interior cells to ``(r, g, b)`` for the image exporters."""

    def __init__(self, config: Config, world: World) -> None:
        palette = config.get("render.palette")
        self._biome: dict[int, RGB] = {int(b): _as_rgb(palette.get(BIOME_NAME[int(b)])) for b in Biome}
        self._ocean = self._biome[int(Biome.OCEAN)]
        # Per-region colours (the headline of the biome map); region id -> base_color.
        self._region: dict[int, RGB] = {r.id: _as_rgb(r.base_color) for r in world.regions}
        # Interior Cell colours. VOID has no entry (it is never drawn - terrain shows through).
        ipal = config.get("render.interior_palette")
        self._interior: dict[int, RGB] = {}
        for cell in Cell:
            if cell == Cell.VOID:
                continue
            rgb = ipal.get(cell.name.lower())
            if rgb is not None:
                self._interior[int(cell)] = _as_rgb(rgb)
        # Overlay colours (road / bridge), keyed by colour id; RGB from render.palette by name.
        self._overlay: dict[int, RGB] = {}
        for color_id, name in OVERLAY_COLOR_NAMES.items():
            rgb = palette.get(name)
            if rgb is not None:
                self._overlay[color_id] = _as_rgb(rgb)

    # ------------------------------------------------------------------ queries
    def tile_rgb(self, world: World, x: int, y: int) -> RGB:
        """Biome-map tile colour: by region (mirrors ``Palette.tile_attr``).

        Ocean tiles and unregioned water (river / lake with ``region_id == -1``) take the ocean
        colour; every land tile takes its region's ``base_color``.
        """
        if int(world.biome[y, x]) == int(Biome.OCEAN):
            return self._ocean
        rid = int(world.region_id[y, x])
        return self._region.get(rid, self._ocean)

    def biome_rgb(self, biome_int: int) -> RGB:
        """Biome floor colour for the detail views (mirrors ``Palette.biome_attr``)."""
        return self._biome.get(int(biome_int), (128, 128, 128))

    def interior_rgb(self, cell_int: int) -> Optional[RGB]:
        """Interior :class:`Cell` colour, or ``None`` for an undrawn cell (e.g. VOID)."""
        return self._interior.get(int(cell_int))

    def overlay_rgb(self, color_id: int) -> Optional[RGB]:
        """Overlay (road / bridge) colour for an overlay colour id, or ``None`` if unmapped."""
        return self._overlay.get(int(color_id))

    def zoom_rgb(self, color_id: int) -> Optional[RGB]:
        """Resolve a detail-cell colour id (mirrors ``Palette.zoom_attr``).

        Ids below :data:`~biomegen.world.tile.INTERIOR_COLOR_BASE` are biome floor colours; ids in the
        interior range are cells encoded as ``INTERIOR_COLOR_BASE + cell_int``; ids at or above
        :data:`~biomegen.world.tile.OVERLAY_COLOR_BASE` are road/bridge overlay colours. Returns ``None``
        for a colour with no palette entry (the caller leaves it transparent).
        """
        if color_id >= OVERLAY_COLOR_BASE:
            return self.overlay_rgb(color_id)
        if color_id >= INTERIOR_COLOR_BASE:
            return self.interior_rgb(color_id - INTERIOR_COLOR_BASE)
        return self.biome_rgb(color_id)
