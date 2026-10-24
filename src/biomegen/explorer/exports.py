"""The ``e`` and ``E`` keys: write the screen's map or the whole world to SVG (and PNG when Pillow is present).

Both go through the render back-ends, so an exported image has the layers, colours and glyphs of the screen.
Files are named by ``export.filename_pattern`` (``{name}``, ``{seed}``, ``{view}``) in ``export.dir``.
"""

from __future__ import annotations

import os
from typing import Optional

from ..config.model import Config
from ..render.backends.png import render_png
from ..render.backends.svg import render_svg
from ..render.grid import RGB, CellGrid
from ..render.static import render_static
from ..world.overlay import Overlay
from ..world.reader import WorldReader
from ..world.world import World


def _sanitize(text: str) -> str:
    """Make ``text`` safe for a filename: keep word characters, turn runs of others into one ``_``."""
    out: list[str] = []
    previous_underscore = False
    for char in text:
        if char.isalnum() or char in "-.":
            out.append(char)
            previous_underscore = False
        elif not previous_underscore:
            out.append("_")
            previous_underscore = True
    return "".join(out).strip("_") or "island"


def base_name(config: Config, world: World, label: str) -> str:
    """Resolve ``export.filename_pattern`` for this world and ``label`` into a safe basename (no extension)."""
    pattern = config.get("export.filename_pattern", "{name}_{seed}_{view}")
    name = _sanitize(world.island_name or "island")
    return _sanitize(pattern.format(name=name, seed=world.seed, view=label))


def write_grid(grid: CellGrid, config: Config, world: World, label: str) -> list[str]:
    """Write ``grid`` as SVG (always) and PNG (when ``export.png`` is set and Pillow is installed).

    Returns the written paths; the PNG is simply absent from the list when it could not be written.
    """
    out_dir = str(config.get("export.dir", "./images"))
    os.makedirs(out_dir, exist_ok=True)
    cell_px = max(1, int(config.get("export.cell_px", 12)))
    background: RGB = tuple(int(v) for v in config.get("export.background"))  # type: ignore[assignment]
    base = os.path.join(out_dir, base_name(config, world, label))
    written = [base + ".svg"]
    with open(written[0], "w", encoding="utf-8") as handle:
        handle.write(render_svg(grid, cell_px, background))
    if config.get("export.png", True) and render_png(grid, cell_px, background, base + ".png"):
        written.append(base + ".png")
    return written


def export_screen(world: World, config: Config, grid: CellGrid, scale: str, view_name: str) -> list[str]:
    """Export the map grid as drawn on screen (no cursor, no panel), labelled by scale and view."""
    label = scale if view_name == "terrain" else f"{scale}-{view_name}"
    return write_grid(grid, config, world, label)


def export_world(
    world: World,
    config: Config,
    view_name: str = "terrain",
    overlay: Optional[Overlay] = None,
    reader: Optional[WorldReader] = None,
) -> list[str]:
    """Export the whole world at one cell per tile, in the named view (as the simulation's ``reader`` sees it)."""
    grid = render_static(world, config, view_name, legend=False, overlay=overlay, reader=reader).grid
    label = "world" if view_name == "terrain" else f"world-{view_name}"
    return write_grid(grid, config, world, label)
