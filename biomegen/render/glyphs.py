"""Glyph lookup tables built from config.

All glyphs are data-driven (``render.glyphs`` / ``render.markers`` / ``render.interior_glyphs``), so a
user can switch to a unicode tileset without touching code. This module turns those config tables
into fast int-indexed lookups for the renderers.
"""

from __future__ import annotations

from ..config.model import Config
from ..world.tile import BIOME_NAME, Biome, Cell


def interior_glyph_table(config: Config) -> dict:
    """Cell int -> interior glyph from ``render.interior_glyphs`` (used by every interior stamp)."""
    icfg = config.get("render.interior_glyphs")
    return {int(c): icfg.get(c.name.lower(), "?") for c in Cell}


class Glyphs:
    """Resolved glyph tables for one config."""

    def __init__(self, config: Config) -> None:
        glyph_cfg = config.get("render.glyphs")
        # Biome int -> single display character. Fall back to '?' for any unmapped biome.
        self.biome = {int(b): glyph_cfg.get(BIOME_NAME[int(b)], "?") for b in Biome}
        self.markers = dict(config.get("render.markers"))
        # Interior Cell name -> glyph (used by the zoom view).
        self.interior = interior_glyph_table(config)

    def biome_glyph(self, biome_int: int) -> str:
        return self.biome.get(int(biome_int), "?")

    def marker(self, name: str, default: str = "?") -> str:
        return self.markers.get(name, default)

    def interior_glyph(self, cell_int: int) -> str:
        return self.interior.get(int(cell_int), "?")
