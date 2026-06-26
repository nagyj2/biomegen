"""Rasterise an export *grid* to a PNG via Pillow (an optional dependency).

PNG output is a convenience on top of the always-available SVG: Pillow is imported lazily inside
:func:`grid_to_png` so the package imports cleanly without it, and the function returns ``False``
(rather than raising) when Pillow is absent so the caller can fall back to SVG-only with a friendly
notice. The grid is the same :data:`~biomegen.export.svg.Cell` intermediate the SVG renderer uses, so
the two outputs are pixel-faithful to one another: a filled rectangle per cell with the glyph centred
on top.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

RGB = Tuple[int, int, int]
Cell = Tuple[Optional[RGB], str, RGB, bool]


def pillow_available() -> bool:
    """Return True if Pillow can be imported (so callers can decide before doing work)."""
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:
        return False


def _load_font(size: int):
    """Return a monospace PIL font at ~``size`` px, falling back to the bundled default.

    Pillow's default bitmap font ignores ``size`` on older versions; we try a common monospace
    TrueType first (crisp at any ``cell_px``) and degrade gracefully through the default font.
    """
    from PIL import ImageFont

    for name in ("DejaVuSansMono.ttf", "consola.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10
    except TypeError:
        return ImageFont.load_default()


def grid_to_png(grid: List[List[Cell]], cell_px: int, background: RGB, path: str) -> bool:
    """Render ``grid`` to ``path`` as a PNG. Return ``True`` on success, ``False`` if Pillow is absent."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    img = Image.new("RGB", (max(1, cols * cell_px), max(1, rows * cell_px)), background)
    draw = ImageDraw.Draw(img)
    font = _load_font(max(1, round(cell_px * 0.82)))
    half = cell_px / 2

    for ry, row in enumerate(grid):
        y0 = ry * cell_px
        for cx, (fill, glyph, glyph_rgb, _bold) in enumerate(row):
            x0 = cx * cell_px
            if fill is not None:
                draw.rectangle([x0, y0, x0 + cell_px - 1, y0 + cell_px - 1], fill=fill)
            if glyph and glyph != " ":
                draw.text((x0 + half, y0 + half), glyph, fill=glyph_rgb, font=font, anchor="mm")

    img.save(path)
    return True
